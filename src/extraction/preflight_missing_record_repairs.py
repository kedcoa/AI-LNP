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
MAX_INPUT_TOKENS = 6_000


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


def _resolved_request_path(value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def find_signed_preflight_manifest(request_path: Path) -> Path:
    """Find the signed preflight manifest that lists one approved request."""

    resolved_request_path = request_path.resolve()
    for parent in (resolved_request_path.parent, *resolved_request_path.parents):
        manifest_path = parent / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        matches = [
            row
            for row in manifest.get("requests", [])
            if isinstance(row, dict)
            and isinstance(row.get("request_path"), str)
            and _resolved_request_path(row["request_path"])
            == resolved_request_path
        ]
        if matches:
            return manifest_path
    raise ValueError(
        "Signed preflight manifest for approved request was not found"
    )


def _has_prompt_content(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_prompt_content(item) for item in value)
    if isinstance(value, dict):
        return any(
            _has_prompt_content(item)
            for key, item in value.items()
            if key in {"content", "text"}
        )
    return False


def load_approved_request(
    path: Path,
    *,
    expected_sha256: str,
    manifest_path: Path,
    expected_task_checksum: str | None = None,
    expected_paper_id: str | None = None,
    expected_route: str | None = None,
) -> dict[str, Any]:
    """Validate and return the exact dictionary approved in a signed preflight."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Signed preflight manifest must be a JSON object")
    supplied_checksum = manifest.get("manifest_checksum")
    unsigned_manifest = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_checksum"
    }
    if (
        manifest.get("preflight_version")
        != "missing-record-request-preflight-1.2.0"
        or not isinstance(supplied_checksum, str)
        or _sha(_canonical(unsigned_manifest)) != supplied_checksum
    ):
        raise ValueError("Signed preflight manifest checksum is invalid")
    if manifest.get("local_preflight_passed") is not True:
        raise ValueError("Signed manifest local preflight did not pass")

    resolved_path = path.resolve()
    matches = [
        row
        for row in manifest.get("requests", [])
        if isinstance(row, dict)
        and isinstance(row.get("request_path"), str)
        and _resolved_request_path(row["request_path"]) == resolved_path
    ]
    if len(matches) != 1:
        raise ValueError(
            "Signed preflight must list the approved request exactly once"
        )
    approved_row = matches[0]
    if (
        expected_task_checksum is not None
        and approved_row.get("task_checksum") != expected_task_checksum
    ):
        raise ValueError(
            "Approved request task checksum does not match current task"
        )
    if (
        expected_paper_id is not None
        and approved_row.get("paper_id") != expected_paper_id
    ):
        raise ValueError(
            "Approved request paper does not match current task"
        )
    if (
        expected_route is not None
        and approved_row.get("route") != expected_route
    ):
        raise ValueError(
            "Approved request route does not match current runner"
        )
    estimated_input_tokens = approved_row.get(
        "estimated_input_tokens"
    )
    if (
        type(estimated_input_tokens) is not int
        or estimated_input_tokens < 0
        or estimated_input_tokens > MAX_INPUT_TOKENS
    ):
        raise ValueError(
            "Approved request estimated input must be at most 6,000 tokens"
        )
    row_sha256 = approved_row.get("request_sha256")
    if row_sha256 != expected_sha256:
        raise ValueError(
            "Supplied approved request SHA-256 does not match signed preflight"
        )
    try:
        request_bytes = resolved_path.read_bytes()
    except OSError as exc:
        raise ValueError("approved request bytes are unavailable") from exc
    if _sha(request_bytes) != expected_sha256:
        raise ValueError(
            "approved request bytes do not match the supplied SHA-256"
        )
    try:
        request = json.loads(request_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("Approved request is not valid JSON") from exc
    if not isinstance(request, dict):
        raise ValueError("Approved request must be a JSON object")
    if not isinstance(request.get("model"), str) or not request["model"].strip():
        raise ValueError("Approved request must name a model")
    if not isinstance(request.get("input"), list) or not _has_prompt_content(
        request["input"]
    ):
        raise ValueError("Approved request must contain prompt-bearing input")
    schema = request.get("text", {}).get("format", {}).get("schema")
    if not isinstance(schema, dict) or not schema:
        raise ValueError("Approved request must contain a response schema")
    max_output_tokens = request.get("max_output_tokens")
    if type(max_output_tokens) is not int or max_output_tokens != 4_000:
        raise ValueError(
            "Approved request max_output_tokens must be exactly 4,000"
        )
    return request


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
    if estimated_input_tokens > MAX_INPUT_TOKENS:
        issues.append("input_token_cap_exceeded")
    persisted_request = (
        json.dumps(request, ensure_ascii=False, indent=2) + "\n"
    )
    payload_bytes = persisted_request.encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload_bytes)
    return (
        {
            "paper_id": task.paper_id,
            "route": route,
            "task_path": _display(task_path),
            "request_path": _display(output_path),
            "task_checksum": task.task_checksum,
            "request_sha256": _sha(payload_bytes),
            "candidate_count": len(task.candidate_ids),
            "evidence_count": len(task.evidence),
            "request_bytes": len(payload_bytes),
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
    visual_human_review_object_ids: set[str] = set()
    visual_human_review: list[dict[str, Any]] = []

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
        for review_row in vision_manifest.get(
            "visual_human_review", []
        ):
            object_id = review_row.get("visual_object_id")
            if object_id:
                visual_human_review_object_ids.add(object_id)
            visual_human_review.append(
                {
                    "paper_id": run_dir.name,
                    "source_task_path": review_row.get(
                        "source_task_path"
                    ),
                    "candidate_ids": review_row.get(
                        "candidate_ids", []
                    ),
                    "visual_object_id": object_id,
                    "reason": review_row.get("reason"),
                }
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

    rows.sort(key=lambda row: row["request_path"])
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
    unsigned_report = {
        "preflight_version": "missing-record-request-preflight-1.2.0",
        "model": model,
        "pricing_status": "pricing_not_configured",
        "task_audit_passed": task_audit["passed"],
        "local_match_count": local_match_count,
        "missing_candidate_count": missing_candidate_count,
        "text_candidate_count": text_candidate_count,
        "text_request_count": text_request_count,
        "visual_candidate_count": visual_candidate_count,
        "sendable_visual_candidate_count": visual_candidate_count,
        "visual_object_count": len(visual_object_ids),
        "visual_human_review_candidate_ids": sorted(
            visual_human_review_candidate_ids
        ),
        "visual_human_review_candidate_count": len(
            visual_human_review_candidate_ids
        ),
        "visual_human_review_object_count": len(
            visual_human_review_object_ids
        ),
        "visual_human_review": visual_human_review,
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
    report = {
        **unsigned_report,
        "manifest_checksum": _sha(_canonical(unsigned_report)),
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
