"""Submit or inspect the prepared Day 8 OpenAI Batch API workload."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI

from .prepare_day8_final_gate import OUTPUT
from .run_abstract_first import ROOT


STATE = OUTPUT / "batch_state.json"


def client() -> OpenAI:
    load_dotenv(ROOT / ".env")
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=300.0, max_retries=2)


def submit() -> dict:
    if STATE.exists():
        prior = json.loads(STATE.read_text())
        counts = prior.get("request_counts") or {}
        safely_retryable = (
            prior.get("status") == "failed"
            or (
                prior.get("status") == "completed"
                and counts.get("completed", 0) == 0
            )
        )
        if not safely_retryable:
            raise RuntimeError(f"Active batch state already exists: {STATE}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        STATE.rename(OUTPUT / f"batch_state.failed.{stamp}.json")
    workload = OUTPUT / "object_extraction_batch.jsonl"
    api = client()
    with workload.open("rb") as handle:
        uploaded = api.files.create(file=handle, purpose="batch")
    batch = api.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/responses",
        completion_window="24h",
        metadata={"pipeline": "day8_final_gate", "scope": "nine_gold_papers"},
    )
    state = {
        "input_file_id": uploaded.id,
        "batch_id": batch.id,
        "status": batch.status,
        "output_file_id": batch.output_file_id,
        "error_file_id": batch.error_file_id,
    }
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    return state


def inspect(download: bool = True) -> dict:
    state = json.loads(STATE.read_text())
    api = client()
    batch = api.batches.retrieve(state["batch_id"])
    state.update({
        "status": batch.status,
        "request_counts": (
            batch.request_counts.model_dump() if batch.request_counts else None
        ),
        "output_file_id": batch.output_file_id,
        "error_file_id": batch.error_file_id,
        "errors": batch.errors.model_dump() if batch.errors else None,
    })
    if download and batch.output_file_id:
        (OUTPUT / "batch_output.jsonl").write_bytes(
            api.files.content(batch.output_file_id).read()
        )
    if download and batch.error_file_id:
        (OUTPUT / "batch_errors.jsonl").write_bytes(
            api.files.content(batch.error_file_id).read()
        )
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("submit", "inspect"))
    args = parser.parse_args()
    print(json.dumps(submit() if args.action == "submit" else inspect(), indent=2))
