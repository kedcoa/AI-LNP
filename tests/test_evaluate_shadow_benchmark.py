from collections import Counter
from pathlib import Path

from src.extraction.evaluate_shadow_benchmark import (
    aggregate_usage,
    build_requirements,
    decide,
    evaluate_auditor,
)
from src.extraction.shadow_benchmark_contracts import (
    AttemptResult,
    RouteEvaluation,
)


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = ROOT / "data/benchmarks/application_pilot"


def _route(
    route: str,
    *,
    recall: float,
    complete_arms: int,
    infrastructure_complete: bool = True,
    safety_findings: dict[str, int] | None = None,
) -> RouteEvaluation:
    return RouteEvaluation(
        route=route,
        issued_attempts=3 if route == "audit" else 14,
        terminal_attempts=3 if route == "audit" else 14,
        full_requirements=round(recall * 62),
        total_requirements=62,
        full_recall=recall,
        complete_arms=complete_arms,
        total_arms=7,
        safety_findings=safety_findings
        or {
            "schema_invalid_accepted": 0,
            "invented_ids": 0,
            "unsupported_exact_numbers": 0,
            "wrong_arm_links": 0,
            "missing_candidate_dispositions": 0,
            "production_writes": 0,
        },
        infrastructure_complete=infrastructure_complete,
        requirement_results=[],
    )


def _attempt(input_tokens: int | None, output_tokens: int | None) -> AttemptResult:
    return AttemptResult(
        case_id="audit-PILOT-001",
        route="audit",
        backend="codex",
        model="hosted-default",
        source_sha256="a" * 64,
        prompt_sha256="b" * 64,
        started_at="2026-08-04T01:00:00Z",
        completed_at="2026-08-04T01:00:01Z",
        duration_seconds=1,
        exit_code=0,
        terminal_disposition="accepted",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        token_measurement_reason=(
            "Codex CLI did not report usage"
            if input_tokens is None or output_tokens is None
            else None
        ),
        stdout_path="attempts/a/stdout.txt",
        stderr_path="attempts/a/stderr.txt",
        parsed_result={},
        validation_issues=[],
        paid_api_requests=0,
        production_writes=0,
    )


def test_authoritative_pilot_requirement_denominator_is_62():
    requirements = build_requirements(REFERENCE_ROOT)

    assert len(requirements) == 62
    assert Counter(row.requirement_type for row in requirements) == {
        "formulation": 22,
        "payload_administration": 10,
        "biological_model": 9,
        "assay": 7,
        "qualitative_outcome": 10,
        "exact_numeric": 4,
    }
    assert len({row.requirement_id for row in requirements}) == 62


def test_missing_token_measurement_is_not_counted_as_zero_usage():
    summary = aggregate_usage([_attempt(None, None), _attempt(100, 20)])

    assert summary == {
        "known_input_tokens": 100,
        "known_output_tokens": 20,
        "attempts_missing_token_measurement": 1,
        "duration_seconds": 2.0,
    }


def test_unsafe_extractor_retains_openai_without_blocking_auditor():
    unsafe = {
        "schema_invalid_accepted": 0,
        "invented_ids": 0,
        "unsupported_exact_numbers": 1,
        "wrong_arm_links": 1,
        "missing_candidate_dispositions": 0,
        "production_writes": 0,
    }

    decision = decide(
        _route("audit", recall=0.92, complete_arms=5),
        _route("gate_b", recall=0.70, complete_arms=6, safety_findings=unsafe),
        hosted_recall=0.6451612903225806,
    )

    assert decision.auditor_recommendation == "adopt_shadow_auditor"
    assert decision.extractor_recommendation == "retain_openai"


def test_incomplete_ollama_run_is_insufficient_evidence():
    decision = decide(
        _route("audit", recall=0.92, complete_arms=5),
        _route(
            "gate_b",
            recall=0.0,
            complete_arms=0,
            infrastructure_complete=False,
        ),
        hosted_recall=0.6451612903225806,
    )

    assert decision.extractor_recommendation == "insufficient_evidence"


def test_failed_audit_attempt_scores_zero_without_losing_paper_denominator():
    failed = _attempt(None, None).model_copy(
        update={
            "parsed_result": None,
            "terminal_disposition": "timeout_or_runtime_failure",
            "exit_code": None,
        }
    )

    result = evaluate_auditor(
        [failed],
        reference_root=REFERENCE_ROOT,
        report_path=ROOT / "reports/extraction/application_pilot_final.json",
    )

    assert result.full_requirements == 0
    assert result.total_requirements == 62
    assert result.infrastructure_complete is False
