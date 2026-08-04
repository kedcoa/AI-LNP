import json
import re
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.extraction.build_shadow_benchmark import (
    build_all_cases,
    build_audit_cases,
    build_gate_b_cases,
    write_case_manifest,
)
from src.extraction.shadow_benchmark_contracts import AttemptResult


ROOT = Path(__file__).resolve().parents[1]


def valid_attempt_payload() -> dict:
    return {
        "case_id": "gate-b-GP-004-task-01",
        "route": "gate_b",
        "backend": "ollama",
        "model": "qwen3:8b",
        "source_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "started_at": "2026-08-04T01:00:00Z",
        "completed_at": "2026-08-04T01:00:01Z",
        "duration_seconds": 1.0,
        "exit_code": 0,
        "terminal_disposition": "accepted",
        "input_tokens": None,
        "output_tokens": None,
        "token_measurement_reason": "Codex CLI did not report usage.",
        "stdout_path": "attempts/case/stdout.txt",
        "stderr_path": "attempts/case/stderr.txt",
        "parsed_result": {"disposition": "unresolved"},
        "validation_issues": [],
        "paid_api_requests": 0,
        "production_writes": 0,
    }


def test_attempt_rejects_unknown_terminal_disposition():
    payload = valid_attempt_payload()
    payload["terminal_disposition"] = "skipped"

    with pytest.raises(ValidationError):
        AttemptResult.model_validate(payload)


def test_attempt_requires_reason_when_tokens_are_unmeasured():
    payload = valid_attempt_payload()
    payload["token_measurement_reason"] = None

    with pytest.raises(ValidationError, match="token_measurement_reason"):
        AttemptResult.model_validate(payload)


def test_attempt_rejects_non_sha256_source_digest():
    payload = valid_attempt_payload()
    payload["source_sha256"] = "short"

    with pytest.raises(ValidationError, match="64 characters"):
        AttemptResult.model_validate(payload)


def test_arm_fixture_has_seven_unique_requirements():
    rows = json.loads(
        (
            ROOT
            / "tests/fixtures/codex_ollama_shadow/arm_requirements.json"
        ).read_text(encoding="utf-8")
    )

    assert len(rows) == 7
    assert len({row["requirement_id"] for row in rows}) == 7
    assert {row["paper_id"] for row in rows} == {"GP-004", "GP-006", "GP-008"}


def test_builds_three_audit_and_twelve_gate_b_cases():
    assert [row.paper_id for row in build_audit_cases(ROOT)] == [
        "GP-004",
        "GP-006",
        "GP-008",
    ]
    gate_b = build_gate_b_cases(ROOT)
    assert len(gate_b) == 12
    assert Counter(row.paper_id for row in gate_b) == {
        "GP-004": 4,
        "GP-006": 4,
        "GP-008": 4,
    }


def test_case_payloads_do_not_contain_gold_paths_or_ids():
    serialized = json.dumps(
        [row.model_dump(mode="json") for row in build_all_cases(ROOT)]
    ).lower()

    assert "data/annotations/gold_v1" not in serialized
    assert "gold_" not in serialized
    assert not re.search(r"\b(?:gf|gx|go|gc)-\d{3}\b", serialized)


def test_case_manifest_is_append_only_and_records_zero_paid_calls(tmp_path):
    destination = tmp_path / "case_manifest.json"
    cases = build_all_cases(ROOT)

    assert write_case_manifest(cases, destination) == destination
    manifest = json.loads(destination.read_text(encoding="utf-8"))
    assert manifest["case_count"] == 15
    assert manifest["route_counts"] == {"audit": 3, "gate_b": 12}
    assert manifest["paid_api_requests"] == 0
    with pytest.raises(FileExistsError):
        write_case_manifest(cases, destination)
