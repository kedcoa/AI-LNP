"""Persist and locally validate exact OpenAI requests without sending them."""

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
from src.extraction.run_missing_record_repair import (
    build_openai_request,
    load_task,
)


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
            f"Task audit failed before request construction: "
            f"{task_audit['issues']}"
        )
    if output_root.exists():
        raise FileExistsError(
            "Preflight output already exists; refusing to overwrite exact "
            "request audit artifacts"
        )
    allowed_create_keys = set(inspect.signature(Responses.create).parameters)
    allowed_create_keys -= {"self", "extra_headers", "extra_query", "extra_body", "timeout"}
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    for task_path in sorted(run_root.glob("GP-*/structural_repair_tasks/task_*.json")):
        task = load_task(task_path)
        request = build_openai_request(task, model=model)
        unknown_keys = sorted(set(request) - allowed_create_keys)
        if unknown_keys:
            issues.append(
                f"{task_path}:unsupported_sdk_keys:{unknown_keys}"
            )
        schema_issues = strict_schema_issues(
            request["text"]["format"]["schema"]
        )
        issues.extend(f"{task_path}:{issue}" for issue in schema_issues)
        serialized = _canonical(request)
        gold = sorted(set(GOLD_IDENTIFIER.findall(serialized)))
        if gold:
            issues.append(f"{task_path}:gold_identifiers:{gold}")
        paper_root = output_root / task.paper_id
        paper_root.mkdir(parents=True, exist_ok=True)
        output_path = paper_root / task_path.name
        output_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rows.append(
            {
                "paper_id": task.paper_id,
                "task_path": str(task_path.relative_to(ROOT)),
                "request_path": str(output_path.relative_to(ROOT)),
                "task_checksum": task.task_checksum,
                "request_sha256": _sha(serialized),
                "candidate_count": len(task.candidate_ids),
                "evidence_count": len(task.evidence),
                "request_bytes": len(serialized.encode("utf-8")),
                "estimated_input_tokens_upper_bound": (
                    len(serialized.encode("utf-8")) + 2
                ) // 3,
                "sdk_create_keys_valid": not unknown_keys,
                "strict_schema_valid": not schema_issues,
            }
        )
    report = {
        "preflight_version": "missing-record-request-preflight-1.0.0",
        "model": model,
        "task_audit_passed": task_audit["passed"],
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
