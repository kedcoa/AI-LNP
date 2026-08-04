"""Score shadow attempts against the blinded 62-fact application pilot."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.extraction.evaluate_application_requirements import (
    ApplicationScore,
    evaluate_application_requirements,
)
from src.extraction.merge_full_paper_results import merge_full_paper_results
from src.extraction.shadow_benchmark_contracts import (
    ApplicationRequirement,
    AttemptResult,
    AuditResponse,
    BenchmarkDecision,
    RequirementResult,
    RouteEvaluation,
)


ROOT = Path(__file__).resolve().parents[2]
PILOT_REPORT = ROOT / "reports/extraction/application_pilot_final.json"
MAP_FIXTURE_ROOT = (
    ROOT / "tests/fixtures/codex_ollama_shadow/application_pilot_maps"
)
SHADOW_REPORT_ROOT = ROOT / "reports/extraction/codex_ollama_shadow"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _reference_document(reference_root: Path) -> dict[str, Any]:
    papers = [_load(path) for path in sorted(reference_root.glob("PILOT-*.json"))]
    return {"papers": papers}


def build_requirements(
    reference_root: Path,
) -> list[ApplicationRequirement]:
    requirements = []
    for paper in _reference_document(reference_root)["papers"]:
        for row in paper["reference_facts"]:
            locator = row.get("source_locator") or {}
            evidence_ids = [locator["evidence_id"]] if locator.get("evidence_id") else []
            requirements.append(
                ApplicationRequirement(
                    requirement_id=row["reference_id"],
                    requirement_type=row["category"],
                    paper_id=paper["paper_id"],
                    evidence_ids=evidence_ids,
                    expected=row,
                )
            )
    ids = [row.requirement_id for row in requirements]
    if len(requirements) != 62:
        raise ValueError(f"Expected 62 pilot requirements, found {len(requirements)}")
    if len(ids) != len(set(ids)):
        raise ValueError("Pilot requirement IDs must be unique")
    return requirements


def aggregate_usage(attempts: list[AttemptResult]) -> dict[str, int | float]:
    return {
        "known_input_tokens": sum(row.input_tokens or 0 for row in attempts),
        "known_output_tokens": sum(row.output_tokens or 0 for row in attempts),
        "attempts_missing_token_measurement": sum(
            row.input_tokens is None or row.output_tokens is None for row in attempts
        ),
        "duration_seconds": sum(row.duration_seconds for row in attempts),
    }


def _complete_arms(missing_ids: set[str], report: dict[str, Any]) -> tuple[int, int]:
    by_experiment: dict[str, set[str]] = defaultdict(set)
    for row in report["reference_bindings"]:
        by_experiment[row["experiment_id"]].add(row["reference_id"])
    complete = sum(not (reference_ids & missing_ids) for reference_ids in by_experiment.values())
    return complete, len(by_experiment)


def _requirement_results(
    requirements: list[ApplicationRequirement], score: ApplicationScore
) -> list[RequirementResult]:
    missing = set(score.missing_reference_ids)
    return [
        RequirementResult(
            requirement_id=row.requirement_id,
            status="missing" if row.requirement_id in missing else "full",
            matched_record_ids=[],
            evidence_ids=row.evidence_ids,
            explanation=(
                "No compatible evidence-grounded fact matched."
                if row.requirement_id in missing
                else "A compatible evidence-grounded fact matched."
            ),
        )
        for row in requirements
    ]


def _safety_findings(
    score: ApplicationScore, attempts: list[AttemptResult]
) -> dict[str, int]:
    return {
        "schema_invalid_accepted": 0,
        "invented_ids": score.invented_id_count,
        "unsupported_exact_numbers": score.unsupported_numeric_count,
        "wrong_arm_links": score.wrong_arm_link_count,
        "missing_candidate_dispositions": sum(
            "missing_candidate" in issue
            for attempt in attempts
            for issue in attempt.validation_issues
        ),
        "production_writes": sum(row.production_writes for row in attempts),
    }


def _route_evaluation(
    *,
    route: str,
    attempts: list[AttemptResult],
    expected_attempts: int,
    score: ApplicationScore,
    requirements: list[ApplicationRequirement],
    report: dict[str, Any],
) -> RouteEvaluation:
    complete_arms, total_arms = _complete_arms(
        set(score.missing_reference_ids), report
    )
    infrastructure_complete = len(attempts) == expected_attempts and not any(
        row.terminal_disposition
        in {"schema_failure", "timeout_or_runtime_failure"}
        for row in attempts
    )
    return RouteEvaluation(
        route=route,
        issued_attempts=expected_attempts,
        terminal_attempts=len(attempts),
        full_requirements=score.matched_reference_count,
        total_requirements=score.reference_denominator,
        full_recall=score.overall_recall,
        complete_arms=complete_arms,
        total_arms=total_arms,
        safety_findings=_safety_findings(score, attempts),
        infrastructure_complete=infrastructure_complete,
        requirement_results=_requirement_results(requirements, score),
    )


def evaluate_auditor(
    attempts: list[AttemptResult],
    *,
    reference_root: Path,
    report_path: Path = PILOT_REPORT,
) -> RouteEvaluation:
    papers = []
    for attempt in attempts:
        if attempt.parsed_result is None:
            continue
        response = AuditResponse.model_validate(attempt.parsed_result)
        papers.append(
            {
                "paper_id": attempt.case_id.removeprefix("audit-"),
                "facts": [
                    observation.model_dump(mode="json")
                    for observation in response.observations
                ],
            }
        )
    reference = _reference_document(reference_root)
    score = evaluate_application_requirements(
        {"papers": papers}, reference, evidence_grounded=True
    )
    requirements = build_requirements(reference_root)
    return _route_evaluation(
        route="audit",
        attempts=attempts,
        expected_attempts=3,
        score=score,
        requirements=requirements,
        report=_load(report_path),
    )


def evaluate_extractor(
    attempts: list[AttemptResult],
    *,
    reference_root: Path,
    report_path: Path = PILOT_REPORT,
    map_root: Path = MAP_FIXTURE_ROOT,
) -> RouteEvaluation:
    by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        if attempt.parsed_result is not None and attempt.terminal_disposition in {
            "accepted",
            "model_abstained",
        }:
            paper_id = attempt.case_id.split("-req-")[0].removeprefix("gate-b-")
            by_paper[paper_id].append(attempt.parsed_result)
    papers = []
    for paper_id in ("PILOT-001", "PILOT-002", "PILOT-003"):
        paper_map = _load(map_root / f"{paper_id}.json")["response"]
        merged = merge_full_paper_results(paper_map, by_paper[paper_id], [])
        papers.append({"paper_id": paper_id, **merged.model_dump(mode="json")})
    reference = _reference_document(reference_root)
    score = evaluate_application_requirements(
        {"papers": papers}, reference, evidence_grounded=True
    )
    requirements = build_requirements(reference_root)
    return _route_evaluation(
        route="gate_b",
        attempts=attempts,
        expected_attempts=14,
        score=score,
        requirements=requirements,
        report=_load(report_path),
    )


def decide(
    auditor: RouteEvaluation,
    extractor: RouteEvaluation,
    *,
    hosted_recall: float,
) -> BenchmarkDecision:
    auditor_safety = sum(auditor.safety_findings.values())
    if not auditor.infrastructure_complete:
        auditor_recommendation = "insufficient_evidence"
        auditor_reasons = ["The three-case audit run did not complete cleanly."]
    elif (
        auditor.full_recall >= 0.90
        and auditor.complete_arms >= 5
        and auditor_safety == 0
    ):
        auditor_recommendation = "adopt_shadow_auditor"
        auditor_reasons = ["Auditor quality and safety gates passed."]
    else:
        auditor_recommendation = "do_not_adopt_auditor"
        auditor_reasons = ["Auditor quality or safety gates did not pass."]

    extractor_safety = sum(extractor.safety_findings.values())
    if not extractor.infrastructure_complete:
        extractor_recommendation = "insufficient_evidence"
        extractor_reasons = [
            "The fourteen-case local extraction run did not complete cleanly; retain OpenAI operationally."
        ]
    elif (
        extractor.full_recall >= hosted_recall * 0.85
        and extractor.complete_arms >= 5
        and extractor_safety == 0
    ):
        extractor_recommendation = "continue_low_risk_shadow"
        extractor_reasons = ["Local extraction quality and safety gates passed."]
    else:
        extractor_recommendation = "retain_openai"
        extractor_reasons = ["Local extraction quality or safety gates did not pass."]
    return BenchmarkDecision(
        auditor_recommendation=auditor_recommendation,
        extractor_recommendation=extractor_recommendation,
        auditor_reasons=auditor_reasons,
        extractor_reasons=extractor_reasons,
        paid_api_requests=0,
    )


def _load_attempts(path: Path) -> list[AttemptResult]:
    return [
        AttemptResult.model_validate_json(attempt.read_text(encoding="utf-8"))
        for attempt in sorted(path.glob("attempts/*/attempt.json"))
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    args = parser.parse_args()
    run_root = SHADOW_REPORT_ROOT / args.run_id
    evaluation_path = run_root / "evaluation.json"
    decision_path = run_root / "decision.json"
    if evaluation_path.exists() or decision_path.exists():
        raise FileExistsError("Refusing to overwrite shadow evaluation artifacts")
    audit_attempts = _load_attempts(run_root / "audit-codex")
    extractor_attempts = _load_attempts(run_root / "gate_b-ollama")
    auditor = evaluate_auditor(
        audit_attempts, reference_root=args.reference_root
    )
    extractor = evaluate_extractor(
        extractor_attempts, reference_root=args.reference_root
    )
    hosted_recall = _load(PILOT_REPORT)["evidence_grounded_score"]["overall_recall"]
    decision = decide(auditor, extractor, hosted_recall=hosted_recall)
    evaluation = {
        "benchmark_version": "codex-ollama-shadow-1.0.0",
        "authoritative_requirement_count": 62,
        "hosted_cached_recall": hosted_recall,
        "auditor": auditor.model_dump(mode="json"),
        "extractor": extractor.model_dump(mode="json"),
        "usage": {
            "auditor": aggregate_usage(audit_attempts),
            "extractor": aggregate_usage(extractor_attempts),
        },
        "paid_api_requests": 0,
    }
    evaluation_path.write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    decision_path.write_text(
        decision.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print(decision.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
