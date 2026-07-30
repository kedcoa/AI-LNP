"""Run one cached, evidence-bounded request that may add omitted records."""

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
from openai.lib._pydantic import to_strict_json_schema

from src.extraction.compact_contracts import ReportedField
from src.extraction.missing_record_contracts import (
    MissingRecordFragment,
    MissingRecordTask,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data/staging/extraction/missing_record_repair_v1"
PROMPT_VERSION = "missing-record-repair-prompt-1.0.0"
PROMPT = """Recover only the atomic candidate facts and experiment context in
the supplied task. Candidate IDs are opaque labels: use candidate_facts as the
required fact definitions and the supplied evidence as their only support.
Account for every candidate ID exactly once as recovered or unresolved. Do not
merge distinct cells, relationships, endpoints, values, polarities, or
experiments into a broad record. A candidate is recovered only when at least one
returned outcome preserves its specific facts and cites its evidence; shared
evidence alone is not coverage. Do not repeat existing records. Return unresolved
with a specific reason when evidence is insufficient. Never invent identifiers,
values, units, comparisons, or evidence labels. For v1.2 tasks, return one
candidate resolution for every candidate and explicitly link each returned
outcome to its resolved candidate and experiment."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def load_task(path: Path) -> MissingRecordTask:
    raw = json.loads(path.read_text(encoding="utf-8"))
    task = MissingRecordTask.model_validate(raw)
    unsigned = {key: value for key, value in raw.items() if key != "task_checksum"}
    if _sha(_canonical(unsigned)) != task.task_checksum:
        raise ValueError("Missing-record task checksum mismatch")
    return task


def validate_response(
    response: MissingRecordFragment,
    task: MissingRecordTask,
) -> None:
    recovered = set(response.recovered_candidate_ids)
    unresolved = set(response.unresolved_candidate_ids)
    expected = set(task.candidate_ids)
    if recovered & unresolved:
        raise ValueError("A candidate cannot be both recovered and unresolved")
    if recovered | unresolved != expected:
        raise ValueError("Response must account for every candidate ID exactly once")
    if response.disposition == "recovered" and not recovered:
        raise ValueError("Recovered disposition must name a recovered candidate")
    if response.disposition == "unresolved" and unresolved != expected:
        raise ValueError("Unresolved disposition must leave every candidate unresolved")
    if len(response.experiments) > task.permitted_new_experiments:
        raise ValueError("Response exceeds permitted new experiment count")
    if len(response.outcomes) > task.permitted_new_outcomes:
        raise ValueError("Response exceeds permitted new outcome count")
    new_experiment_ids = [row.experiment_id for row in response.experiments]
    new_outcome_ids = [row.outcome_id for row in response.outcomes]
    if len(set(new_experiment_ids)) != len(new_experiment_ids):
        raise ValueError("New experiment IDs must be unique")
    if len(set(new_outcome_ids)) != len(new_outcome_ids):
        raise ValueError("New outcome IDs must be unique")
    if set(new_experiment_ids) & set(task.existing_experiment_ids):
        raise ValueError("Response reuses an existing experiment ID")
    if set(new_outcome_ids) & set(task.existing_outcome_ids):
        raise ValueError("Response reuses an existing outcome ID")
    allowed_experiments = set(task.existing_experiment_ids) | set(new_experiment_ids)
    if any(row.experiment_id not in allowed_experiments for row in response.outcomes):
        raise ValueError("New outcome references an unknown experiment")
    if any(
        row.formulation_id not in set(task.existing_formulation_ids)
        for row in response.experiments
    ):
        raise ValueError("New experiment references an unknown formulation")
    allowed_evidence = {row.evidence_id for row in task.evidence}
    for record in [*response.experiments, *response.outcomes]:
        for field_name in record.__class__.model_fields:
            value = getattr(record, field_name)
            if isinstance(value, ReportedField):
                unknown = set(value.evidence_ids) - allowed_evidence
                if unknown:
                    raise ValueError(
                        f"{record.__class__.__name__}.{field_name} cites unknown "
                        f"evidence IDs: {sorted(unknown)}"
                    )
    if task.task_version != "missing-record-task-1.2.0":
        return

    resolution_ids = [row.candidate_id for row in response.candidate_resolutions]
    if len(set(resolution_ids)) != len(resolution_ids):
        raise ValueError("candidate resolution IDs must be unique")
    if set(resolution_ids) != expected:
        raise ValueError("Response must include one candidate resolution per candidate")

    known_outcomes = set(task.existing_outcome_ids) | set(new_outcome_ids)
    resolution_by_candidate = {
        row.candidate_id: row for row in response.candidate_resolutions
    }
    resolved_candidates = {
        candidate_id
        for candidate_id, resolution in resolution_by_candidate.items()
        if resolution.status != "unresolved"
    }
    unresolved_candidates = expected - resolved_candidates
    if recovered != resolved_candidates or unresolved != unresolved_candidates:
        raise ValueError(
            "recovered and unresolved candidate IDs must agree with candidate resolutions"
        )
    if (response.disposition == "recovered") != bool(resolved_candidates):
        raise ValueError(
            "response disposition must agree with candidate resolutions"
        )
    existing_outcome_experiments = {
        summary.outcome_id: summary.experiment_id
        for summary in task.existing_outcome_summaries
    }
    returned_outcome_experiments = {
        outcome.outcome_id: outcome.experiment_id for outcome in response.outcomes
    }
    for resolution in response.candidate_resolutions:
        outcome_ids = set(resolution.outcome_ids)
        experiment_ids = set(resolution.experiment_ids)
        if len(outcome_ids) != len(resolution.outcome_ids):
            raise ValueError("candidate resolution outcome IDs must be unique")
        if len(experiment_ids) != len(resolution.experiment_ids):
            raise ValueError("candidate resolution experiment IDs must be unique")
        if resolution.status == "unresolved":
            if outcome_ids or experiment_ids:
                raise ValueError("unresolved candidate resolutions cannot reference records")
            if not resolution.reason:
                raise ValueError("unresolved candidate resolutions require a reason")
            continue
        if not outcome_ids or not experiment_ids:
            raise ValueError(
                "resolved candidate resolutions require outcome and experiment IDs"
            )
        if resolution.reason:
            raise ValueError(
                "resolved candidate resolutions cannot include an unresolved reason"
            )
        if outcome_ids - known_outcomes:
            raise ValueError("candidate resolution references an unknown outcome")
        if experiment_ids - allowed_experiments:
            raise ValueError("candidate resolution references an unknown experiment")
        for outcome_id in outcome_ids:
            if outcome_id in task.existing_outcome_ids:
                linked_experiment_id = existing_outcome_experiments.get(outcome_id)
                if linked_experiment_id is None:
                    raise ValueError(
                        "candidate resolution outcome summary is unavailable"
                    )
            else:
                linked_experiment_id = returned_outcome_experiments[outcome_id]
            if linked_experiment_id not in experiment_ids:
                raise ValueError(
                    "candidate resolution outcome summary does not match an experiment"
                )
        linked_returned_outcomes = [
            outcome
            for outcome in response.outcomes
            if outcome.outcome_id in outcome_ids
            and outcome.experiment_id in experiment_ids
        ]
        if resolution.status == "already_represented":
            if outcome_ids - set(task.existing_outcome_ids):
                raise ValueError("already represented candidates require existing outcomes")
            if experiment_ids - set(task.existing_experiment_ids):
                raise ValueError("already represented candidates require existing experiments")
        elif resolution.status == "recovered_existing_experiment":
            if experiment_ids - set(task.existing_experiment_ids):
                raise ValueError(
                    "recovered existing experiment candidates require existing experiments"
                )
            if not linked_returned_outcomes:
                raise ValueError(
                    "recovered existing experiment candidates require a new outcome"
                )
        elif resolution.status == "recovered_new_experiment":
            if not any(
                outcome.experiment_id in set(new_experiment_ids)
                for outcome in linked_returned_outcomes
            ):
                raise ValueError(
                    "recovered new experiment candidates require a new experiment outcome"
                )

    for outcome in response.outcomes:
        if not any(
            outcome.outcome_id in resolution.outcome_ids
            and outcome.experiment_id in resolution.experiment_ids
            for resolution in response.candidate_resolutions
        ):
            raise ValueError(
                "Every returned outcome requires an explicit candidate resolution link"
            )


def fingerprint(task: MissingRecordTask, model: str) -> str:
    return _sha(
        _canonical(
            {
                "task_checksum": task.task_checksum,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": _sha(PROMPT),
                "schema": to_strict_json_schema(MissingRecordFragment),
                "model": model,
            }
        )
    )


def build_openai_request(
    task: MissingRecordTask,
    *,
    model: str,
    max_output_tokens: int = 4_000,
) -> dict[str, Any]:
    """Build the exact bounded request shared by preflight and generation."""

    return {
        "model": model,
        "reasoning": {"effort": "medium"},
        "store": False,
        "service_tier": "default",
        "max_output_tokens": max_output_tokens,
        "input": [
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": _canonical(task.model_dump(mode="json")),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "MissingRecordFragment",
                "schema": to_strict_json_schema(MissingRecordFragment),
                "strict": True,
            }
        },
    }


def persist_raw_response(run_dir: Path, api_response: Any) -> Path:
    """Persist the provider envelope before inspecting structured output."""

    raw_response_path = run_dir / "response.raw.json"
    raw_response_path.write_text(
        json.dumps(
            api_response.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return raw_response_path


def run(
    task: MissingRecordTask,
    *,
    model: str,
    client: OpenAI,
    output_root: Path = OUTPUT_ROOT,
    max_output_tokens: int = 4_000,
) -> dict[str, Any]:
    run_fingerprint = fingerprint(task, model)
    task_key = _sha(task.task_checksum)[:16]
    run_dir = output_root / task.paper_id / task_key / run_fingerprint
    result_path = run_dir / "result.json"
    manifest_path = run_dir / "manifest.json"
    if result_path.exists() and manifest_path.exists():
        result = MissingRecordFragment.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        validate_response(result, task)
        return {
            **json.loads(manifest_path.read_text(encoding="utf-8")),
            "cache_hit": True,
            "paid_api_requests_this_run": 0,
        }
    if run_dir.exists():
        raise FileExistsError("Incomplete run exists; refusing an automatic paid retry")
    run_dir.mkdir(parents=True)
    request = build_openai_request(
        task, model=model, max_output_tokens=max_output_tokens
    )
    (run_dir / "request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    started = datetime.now(timezone.utc)
    api_response = client.responses.create(**request)
    persist_raw_response(run_dir, api_response)
    if not api_response.output_text:
        raise RuntimeError("Missing-record request returned no structured output")
    response = MissingRecordFragment.model_validate_json(api_response.output_text)
    validate_response(response, task)
    (run_dir / "response.json").write_text(
        json.dumps(api_response.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    result_path.write_text(response.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest = {
        "status": "completed_pending_merge",
        "paper_id": task.paper_id,
        "candidate_ids": task.candidate_ids,
        "fingerprint": run_fingerprint,
        "model_requested": model,
        "model_returned": api_response.model,
        "response_id": api_response.id,
        "paid_api_requests": 1,
        "cache_hit": False,
        "started_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "usage": (
            api_response.usage.model_dump(mode="json") if api_response.usage else None
        ),
        "disposition": response.disposition,
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
    model = os.getenv("MISSING_RECORD_MODEL", "gpt-5.6-terra")
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=300,
        max_retries=0,
    )
    print(json.dumps(run(load_task(args.task), model=model, client=client), indent=2))


if __name__ == "__main__":
    main()
