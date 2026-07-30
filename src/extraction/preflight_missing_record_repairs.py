"""Persist and locally validate exact text and vision repair requests."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
from pathlib import Path
from typing import Any

from openai.resources.responses.responses import Responses

from src.extraction.audit_v12_structural_tasks import audit
from src.extraction.build_missing_record_vision_tasks import (
    matching_accepted_visual_claims,
    vision_task_binding_issues,
)
from src.extraction.run_missing_record_repair import (
    build_openai_request as build_text_request,
)
from src.extraction.run_missing_record_repair import load_task
from src.extraction.run_missing_record_vision import (
    build_openai_request as build_vision_request,
)
from src.extraction.run_missing_record_vision import (
    load_task as load_vision_task,
)
from src.rag.compact_api_packet import estimate_tokens


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "data/staging/extraction/v12_structural_primary_v6"
OUTPUT_ROOT = (
    ROOT / "data/staging/extraction/v12_structural_primary_v6_preflight"
)
REPORT_PATH = (
    ROOT
    / "reports/extraction/v12_structural_primary_v6/request_preflight.json"
)
GOLD_IDENTIFIER = re.compile(r"\bG[OX]-\d+\b")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _display(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def strict_schema_issues(schema: Any, path: str = "$") -> list[str]:
    issues: list[str] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is not False:
                issues.append(f"{path}:additionalProperties_must_be_false")
            if set(schema.get("required", [])) != set(properties):
                issues.append(f"{path}:all_properties_must_be_required")
        for key, value in schema.items():
            issues.extend(strict_schema_issues(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            issues.extend(strict_schema_issues(value, f"{path}[{index}]"))
    return issues


def _source_hash_issues(task: Any, run_dir: Path) -> list[str]:
    issues: list[str] = []
    result_path = run_dir / "result.json"
    request_path = run_dir / "request.json"
    if not result_path.is_file():
        issues.append("source_result_missing")
    elif _sha(result_path.read_bytes()) != task.source_result_sha256:
        issues.append("source_result_sha256_mismatch")
    if not request_path.is_file():
        issues.append("source_inventory_missing")
    else:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        support = request.get("request_payload", {}).get(
            "outcome_recall_support"
        )
        if support is None:
            issues.append("source_inventory_missing")
        elif _sha(_canonical(support)) != task.source_inventory_sha256:
            issues.append("source_inventory_sha256_mismatch")
    return issues


def _request_row(
    *,
    route: str,
    task: Any,
    task_path: Path,
    request: dict[str, Any],
    output_path: Path,
    allowed_create_keys: set[str],
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    unknown_keys = sorted(set(request) - allowed_create_keys)
    if unknown_keys:
        issues.append(f"unsupported_sdk_keys:{unknown_keys}")
    schema_issues = strict_schema_issues(
        request["text"]["format"]["schema"]
    )
    issues.extend(schema_issues)
    serialized = _canonical(request)
    gold = sorted(set(GOLD_IDENTIFIER.findall(serialized)))
    if gold:
        issues.append(f"gold_identifiers:{gold}")
    token_estimate_request = json.loads(serialized)
    image_input_bytes = 0
    if route == "vision":
        image_input_bytes = Path(task.crop_path).stat().st_size
        for message in token_estimate_request.get("input", []):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if item.get("type") == "input_image":
                    item["image_url"] = ""
    estimated_input_tokens = estimate_tokens(
        _canonical(token_estimate_request)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return (
        {
            "paper_id": task.paper_id,
            "route": route,
            "task_path": _display(task_path),
            "request_path": _display(output_path),
            "task_checksum": task.task_checksum,
            "request_sha256": _sha(serialized),
            "candidate_count": len(task.candidate_ids),
            "evidence_count": len(task.evidence),
            "request_bytes": len(serialized.encode("utf-8")),
            "estimated_input_tokens": estimated_input_tokens,
            "image_input_bytes": image_input_bytes,
            "estimated_image_tokens": None,
            "max_output_tokens": request["max_output_tokens"],
            "sdk_create_keys_valid": not unknown_keys,
            "strict_schema_valid": not schema_issues,
        },
        issues,
    )


def preflight(
    *,
    run_root: Path = RUN_ROOT,
    output_root: Path = OUTPUT_ROOT,
    model: str = "gpt-5.6-terra",
) -> dict[str, Any]:
    run_root = run_root.resolve()
    output_root = output_root.resolve()
    task_audit = audit(run_root)
    if not task_audit["passed"]:
        raise ValueError(
            "Task audit failed before request construction: "
            f"{task_audit['issues']}"
        )
    if output_root.exists():
        raise FileExistsError(
            "Preflight output already exists; refusing to overwrite exact "
            "request audit artifacts"
        )
    allowed_create_keys = set(inspect.signature(Responses.create).parameters)
    allowed_create_keys -= {
        "self",
        "extra_headers",
        "extra_query",
        "extra_body",
        "timeout",
    }
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    text_candidate_count = 0
    visual_candidate_count = 0
    visual_object_ids: set[str] = set()
    visual_human_review_candidate_ids: set[str] = set()

    for run_dir in sorted(path for path in run_root.glob("GP-*") if path.is_dir()):
        source_request = json.loads(
            (run_dir / "request.json").read_text(encoding="utf-8")
        )
        accepted_visual_claims = source_request["request_payload"][
            "outcome_recall_support"
        ].get("accepted_visual_claims", [])
        structural_root = run_dir / "structural_repair_tasks"
        manifest = json.loads(
            (structural_root / "manifest.json").read_text(encoding="utf-8")
        )
        task_paths = sorted(structural_root.glob("task_*.json"))
        metadata_rows = manifest.get("tasks", [])
        if len(task_paths) != len(metadata_rows):
            issues.append(f"{run_dir.name}:task_manifest_count_mismatch")
            continue
        vision_root = run_dir / "missing_record_vision_tasks"
        vision_paths = {
            path.name: path for path in vision_root.glob("task_*.json")
        }
        vision_manifest_path = vision_root / "manifest.json"
        vision_manifest = (
            json.loads(vision_manifest_path.read_text(encoding="utf-8"))
            if vision_manifest_path.is_file()
            else {}
        )
        paper_visual_human_review_ids = set(
            vision_manifest.get(
                "visual_human_review_candidate_ids", []
            )
        )
        visual_human_review_candidate_ids |= (
            paper_visual_human_review_ids
        )
        expected_vision_names: set[str] = set()

        for task_path, metadata in zip(
            task_paths, metadata_rows, strict=True
        ):
            route = metadata.get("repair_route")
            if route == "text":
                task = load_task(task_path)
                text_candidate_count += len(task.candidate_ids)
                request = build_text_request(task, model=model)
            elif route == "vision":
                candidate_ids = set(metadata.get("candidate_ids", []))
                quarantined = (
                    candidate_ids & paper_visual_human_review_ids
                )
                if quarantined:
                    if quarantined != candidate_ids:
                        issues.append(
                            f"{run_dir.name}:{task_path.name}:"
                            "partial_visual_human_review_scope"
                        )
                    continue
                expected_vision_names.add(task_path.name)
                visual_object_id = metadata.get("visual_object_id")
                if visual_object_id:
                    visual_object_ids.add(visual_object_id)
                vision_path = vision_paths.get(task_path.name)
                if vision_path is None:
                    issues.append(
                        f"{run_dir.name}:{task_path.name}:"
                        "missing_vision_task"
                    )
                    continue
                source_task = load_task(task_path)
                task = load_vision_task(vision_path)
                matching_claims = matching_accepted_visual_claims(
                    text_task=source_task,
                    visual_object_id=visual_object_id,
                    claims=accepted_visual_claims,
                )
                if len(matching_claims) != 1:
                    issues.append(
                        f"{run_dir.name}:{task_path.name}:"
                        "accepted_visual_claim_binding_mismatch"
                    )
                    continue
                binding_issues = vision_task_binding_issues(
                    vision_task=task,
                    text_task=source_task,
                    accepted_visual_claim=matching_claims[0],
                )
                if binding_issues:
                    issues.extend(
                        f"{run_dir.name}:{task_path.name}:"
                        f"{binding_issue}"
                        for binding_issue in binding_issues
                    )
                    continue
                visual_candidate_count += len(task.candidate_ids)
                request = build_vision_request(task, model=model)
                task_path = vision_path
            else:
                issues.append(
                    f"{run_dir.name}:{task_path.name}:"
                    f"invalid_repair_route:{route}"
                )
                continue

            issues.extend(
                f"{run_dir.name}:{task_path.name}:{issue}"
                for issue in _source_hash_issues(task, run_dir)
            )
            output_path = (
                output_root / run_dir.name / route / task_path.name
            )
            row, row_issues = _request_row(
                route=route,
                task=task,
                task_path=task_path,
                request=request,
                output_path=output_path,
                allowed_create_keys=allowed_create_keys,
            )
            rows.append(row)
            issues.extend(
                f"{run_dir.name}:{task_path.name}:{issue}"
                for issue in row_issues
            )

        extra_vision = set(vision_paths) - expected_vision_names
        if extra_vision:
            issues.append(
                f"{run_dir.name}:unexpected_vision_tasks:"
                f"{sorted(extra_vision)}"
            )

    text_request_count = sum(row["route"] == "text" for row in rows)
    vision_request_count = sum(row["route"] == "vision" for row in rows)
    total_paid_request_count = text_request_count + vision_request_count
    local_match_count = sum(
        paper.get("confirmed_candidate_count", 0)
        for paper in task_audit.get("papers", [])
    )
    missing_candidate_count = task_audit.get(
        "repair_candidate_count",
        text_candidate_count + visual_candidate_count,
    )
    report = {
        "preflight_version": "missing-record-request-preflight-1.1.0",
        "model": model,
        "pricing_status": "pricing_not_configured",
        "task_audit_passed": task_audit["passed"],
        "local_match_count": local_match_count,
        "missing_candidate_count": missing_candidate_count,
        "text_candidate_count": text_candidate_count,
        "text_request_count": text_request_count,
        "visual_candidate_count": visual_candidate_count,
        "visual_object_count": len(visual_object_ids),
        "visual_human_review_candidate_ids": sorted(
            visual_human_review_candidate_ids
        ),
        "vision_request_count": vision_request_count,
        "total_paid_request_count": total_paid_request_count,
        "estimated_input_tokens": sum(
            row["estimated_input_tokens"] for row in rows
        ),
        "image_input_bytes": sum(
            row["image_input_bytes"] for row in rows
        ),
        "estimated_image_tokens": None,
        "image_token_estimate_status": "not_configured",
        "max_output_tokens": sum(
            row["max_output_tokens"] for row in rows
        ),
        "estimated_cost": None,
        "request_paths": [row["request_path"] for row in rows],
        "request_count": len(rows),
        "requests": rows,
        "issues": issues,
        "local_preflight_passed": not issues,
        "server_request_sent": False,
        "generation_requests": 0,
        "paid_api_requests": 0,
        "ready_for_paid_calls": False,
        "human_approval_required": True,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--model", default="gpt-5.6-terra")
    args = parser.parse_args()
    report = preflight(
        run_root=args.run_root,
        output_root=args.output_root,
        model=args.model,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["local_preflight_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
