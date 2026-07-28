"""Run one independently cached, field-level OpenAI repair request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import TypeAdapter

from src.extraction.build_repair_tasks import COLLECTION_MODELS
from src.extraction.repair_contracts import RepairResponse, RepairTask


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data" / "staging" / "extraction" / "narrow_repair_v1"
PROMPT_VERSION = "narrow-repair-prompt-1.0.0"
REPAIR_PROMPT = """You repair exactly one invalid biomedical extraction field.
Use only the supplied record, validation finding, cited evidence, targeted
passages, and schema fragment. Do not infer unsupported values or change any
other field. Return one corrected fragment, or explicitly return missing or
ambiguous. Evidence IDs must come from the supplied repair task."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _unsigned_task(task: RepairTask) -> dict[str, Any]:
    return task.model_dump(mode="json", exclude={"task_checksum"})


def load_task(path: Path) -> RepairTask:
    task = RepairTask.model_validate_json(path.read_text(encoding="utf-8"))
    actual = _sha256(_canonical_json(_unsigned_task(task)))
    if actual != task.task_checksum:
        raise ValueError(
            f"Repair task checksum mismatch: expected {task.task_checksum}, got {actual}"
        )
    return task


def response_schema(task: RepairTask) -> dict[str, Any]:
    field_name = task.finding.field_name
    assert field_name is not None
    fragment = task.expected_schema_fragment
    return {
        "type": "object",
        "properties": {
            "finding_id": {"type": "string"},
            "disposition": {
                "type": "string",
                "enum": ["corrected", "missing", "ambiguous"],
            },
            "corrected_fragment": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {field_name: fragment["schema"]},
                        "required": [field_name],
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ]
            },
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "explanation": {"type": "string"},
        },
        "required": [
            "finding_id",
            "disposition",
            "corrected_fragment",
            "evidence_ids",
            "explanation",
        ],
        "additionalProperties": False,
        "$defs": fragment.get("$defs", {}),
    }


def validate_response(response: RepairResponse, task: RepairTask) -> None:
    if response.finding_id != task.finding.finding_id:
        raise ValueError("Repair response finding_id does not match its task")
    allowed_evidence_ids = {
        row.evidence_id
        for row in [
            *task.relevant_cited_evidence,
            *task.additional_targeted_passages,
        ]
    }
    unknown = set(response.evidence_ids) - allowed_evidence_ids
    if unknown:
        raise ValueError(f"Repair response cites unknown evidence: {sorted(unknown)}")
    if response.disposition != "corrected":
        return
    field_name = task.finding.field_name
    collection = task.finding.record_collection
    assert field_name is not None and collection is not None
    if set(response.corrected_fragment or {}) != {field_name}:
        raise ValueError("Repair may return exactly one corrected field")
    annotation = COLLECTION_MODELS[collection].model_fields[field_name].annotation
    TypeAdapter(annotation).validate_python(response.corrected_fragment[field_name])
    corrected_value = response.corrected_fragment[field_name]
    corrected_evidence_ids = (
        set(corrected_value.get("evidence_ids", []))
        if isinstance(corrected_value, dict)
        else set()
    )
    unknown_corrected = corrected_evidence_ids - allowed_evidence_ids
    if unknown_corrected:
        raise ValueError(
            "Corrected fragment cites unknown evidence: "
            f"{sorted(unknown_corrected)}"
        )
    if corrected_evidence_ids != set(response.evidence_ids):
        raise ValueError(
            "Response evidence_ids must match the corrected field's evidence_ids"
        )


def repair_fingerprint(task: RepairTask, model: str) -> str:
    return _sha256(
        _canonical_json(
            {
                "task_checksum": task.task_checksum,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": _sha256(REPAIR_PROMPT),
                "response_schema": response_schema(task),
                "model": model,
            }
        )
    )


def run_repair(
    task: RepairTask,
    *,
    model: str,
    client: OpenAI,
    output_root: Path = OUTPUT_ROOT,
    max_output_tokens: int = 1_500,
) -> dict[str, Any]:
    fingerprint = repair_fingerprint(task, model)
    run_dir = output_root / task.paper_id / task.finding.finding_id / fingerprint
    result_path = run_dir / "result.json"
    manifest_path = run_dir / "manifest.json"
    if result_path.exists() and manifest_path.exists():
        saved = RepairResponse.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        validate_response(saved, task)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {**manifest, "cache_hit": True, "paid_api_requests_this_run": 0}
    if run_dir.exists():
        raise FileExistsError("Incomplete repair directory exists; refusing a paid retry")
    run_dir.mkdir(parents=True)

    request_payload = task.model_payload()
    request_snapshot = {
        "model": model,
        "reasoning_effort": "low",
        "store": False,
        "max_output_tokens": max_output_tokens,
        "repair_fingerprint": fingerprint,
        "prompt_version": PROMPT_VERSION,
        "system_prompt": REPAIR_PROMPT,
        "repair_task": request_payload,
    }
    (run_dir / "request.json").write_text(
        json.dumps(request_snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    started_at = datetime.now(timezone.utc)
    api_response = client.responses.create(
        model=model,
        reasoning={"effort": "low"},
        store=False,
        service_tier="default",
        max_output_tokens=max_output_tokens,
        prompt_cache_key=_sha256(
            _canonical_json([PROMPT_VERSION, _sha256(REPAIR_PROMPT), model])
        ),
        input=[
            {"role": "system", "content": REPAIR_PROMPT},
            {"role": "user", "content": _canonical_json(request_payload)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "NarrowRepairResponse",
                "schema": response_schema(task),
                "strict": True,
            }
        },
    )
    completed_at = datetime.now(timezone.utc)
    (run_dir / "response.json").write_text(
        json.dumps(api_response.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    if not api_response.output_text:
        raise RuntimeError("Repair request returned no structured output")
    result = RepairResponse.model_validate_json(api_response.output_text)
    validate_response(result, task)
    result_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest = {
        "status": "completed_pending_merge",
        "paper_id": task.paper_id,
        "finding_id": task.finding.finding_id,
        "field_name": task.finding.field_name,
        "repair_fingerprint": fingerprint,
        "model_requested": model,
        "model_returned": api_response.model,
        "response_id": api_response.id,
        "paid_api_requests": 1,
        "cache_hit": False,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "usage": (
            api_response.usage.model_dump(mode="json")
            if api_response.usage
            else None
        ),
        "disposition": result.disposition,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--confirm-paid-call", action="store_true")
    args = parser.parse_args()
    if not args.confirm_paid_call:
        parser.error("--confirm-paid-call is required")
    load_dotenv(ROOT / ".env")
    model = os.getenv("NARROW_REPAIR_MODEL", "gpt-5.6-terra")
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=300.0,
        max_retries=0,
    )
    print(
        json.dumps(
            run_repair(load_task(args.task), model=model, client=client),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
