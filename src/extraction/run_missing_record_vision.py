"""Cached record-level vision recovery; never auto-accept visual estimates."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema

from src.extraction.missing_record_contracts import (
    MissingRecordTask,
    MissingRecordVisionResponse,
    MissingRecordVisionTask,
)
from src.extraction.run_missing_record_repair import (
    persist_raw_response,
    validate_response,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data/staging/extraction/missing_record_vision_v1"
PROMPT_VERSION = "missing-record-vision-prompt-1.0.0"
PROMPT = """Inspect only this targeted scientific page and supplied text.
Recover omitted experiment/outcome records only from exact printed table cells,
labels, legends, or explicitly derivable values. Report the exact cell or panel.
Never turn an axis estimate into an accepted value. Account for every candidate
ID as recovered or unresolved, and use only supplied evidence IDs plus the crop
evidence ID."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def load_task(path: Path) -> MissingRecordVisionTask:
    raw = json.loads(path.read_text(encoding="utf-8"))
    task = MissingRecordVisionTask.model_validate(raw)
    unsigned = {
        key: value for key, value in raw.items() if key != "task_checksum"
    }
    if _sha(_canonical(unsigned)) != task.task_checksum:
        raise ValueError("Missing-record vision task checksum mismatch")
    if _sha(Path(task.crop_path).read_bytes()) != task.crop_sha256:
        raise ValueError("Missing-record vision crop checksum mismatch")
    return task


def _as_text_task(task: MissingRecordVisionTask) -> MissingRecordTask:
    return MissingRecordTask(
        task_version=(
            "missing-record-task-1.2.0"
            if task.task_version
            in {
                "missing-record-vision-task-1.1.0",
                "missing-record-vision-task-1.2.0",
            }
            else "missing-record-task-1.0.0"
        ),
        paper_id=task.paper_id,
        route_ids=task.route_ids,
        candidate_ids=task.candidate_ids,
        experiment_context=task.experiment_context,
        candidate_facts=task.candidate_facts,
        evidence=task.evidence,
        existing_formulation_ids=task.existing_formulation_ids,
        existing_experiment_ids=task.existing_experiment_ids,
        existing_outcome_ids=task.existing_outcome_ids,
        existing_experiment_summaries=task.existing_experiment_summaries,
        existing_outcome_summaries=task.existing_outcome_summaries,
        permitted_new_experiments=task.permitted_new_experiments,
        permitted_new_outcomes=task.permitted_new_outcomes,
        source_result_sha256=task.source_result_sha256,
        source_inventory_sha256=task.source_inventory_sha256,
        task_checksum="vision-adapter",
    )


def validate(result: MissingRecordVisionResponse, task: MissingRecordVisionTask) -> None:
    text_task = _as_text_task(task)
    if task.crop_evidence_id not in {
        row.evidence_id for row in text_task.evidence
    }:
        text_task.evidence.append(
            type(text_task.evidence[0])(
                evidence_id=task.crop_evidence_id,
                text=(
                    f"Rendered {task.figure_or_table}, page "
                    f"{task.page_number or 'unknown'}"
                ),
                source_ids=[],
            )
        )
    validate_response(result.fragment, text_task)


def _image(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def build_openai_request(
    task: MissingRecordVisionTask,
    *,
    model: str,
    max_output_tokens: int = 4_000,
) -> dict[str, Any]:
    """Build the exact visual request shared by preflight and generation."""

    return {
        "model": model,
        "reasoning": {"effort": "low"},
        "store": False,
        "service_tier": "default",
        "max_output_tokens": max_output_tokens,
        "input": [
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": _canonical(task.model_dump(mode="json")),
                    },
                    {
                        "type": "input_image",
                        "image_url": _image(Path(task.crop_path)),
                        "detail": "original",
                    },
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "MissingRecordVisionResponse",
                "schema": to_strict_json_schema(MissingRecordVisionResponse),
                "strict": True,
            }
        },
    }


def run(
    task: MissingRecordVisionTask,
    *,
    model: str,
    client: OpenAI,
    output_root: Path = OUTPUT_ROOT,
    max_output_tokens: int = 4_000,
) -> dict:
    fingerprint = _sha(
        _canonical(
            {
                "task_checksum": task.task_checksum,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": _sha(PROMPT),
                "model": model,
                "schema": to_strict_json_schema(
                    MissingRecordVisionResponse
                ),
            }
        )
    )
    run_dir = output_root / task.paper_id / fingerprint
    result_path = run_dir / "result.json"
    manifest_path = run_dir / "manifest.json"
    if result_path.exists() and manifest_path.exists():
        result = MissingRecordVisionResponse.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        validate(result, task)
        return {
            **json.loads(manifest_path.read_text(encoding="utf-8")),
            "cache_hit": True,
            "paid_api_requests_this_run": 0,
        }
    if run_dir.exists():
        raise FileExistsError("Incomplete vision run exists; refusing paid retry")
    run_dir.mkdir(parents=True)
    request = build_openai_request(
        task, model=model, max_output_tokens=max_output_tokens
    )
    (run_dir / "request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    response = client.responses.create(**request)
    persist_raw_response(run_dir, response)
    if not response.output_text:
        raise RuntimeError("Missing-record vision returned no structured output")
    result = MissingRecordVisionResponse.model_validate_json(response.output_text)
    validate(result, task)
    (run_dir / "response.json").write_text(
        json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest = {
        "status": "completed_pending_merge",
        "paper_id": task.paper_id,
        "candidate_ids": task.candidate_ids,
        "fingerprint": fingerprint,
        "response_id": response.id,
        "model_returned": response.model,
        "paid_api_requests": 1,
        "cache_hit": False,
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
        "disposition": result.fragment.disposition,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--confirm-paid-call", action="store_true")
    args = parser.parse_args()
    if not args.confirm_paid_call:
        parser.error("--confirm-paid-call is required")
    load_dotenv(ROOT / ".env")
    model = os.getenv("MISSING_RECORD_VISION_MODEL", "gpt-5.6-terra")
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=300,
        max_retries=0,
    )
    print(json.dumps(run(load_task(args.task), model=model, client=client), indent=2))


if __name__ == "__main__":
    main()
