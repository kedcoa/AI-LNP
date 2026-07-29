"""Evaluate the deterministic candidate gate against frozen local controls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.extraction.deterministic_coverage_v12 import (
    assess_candidate_eligibility,
)
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = (
    ROOT
    / "tests/fixtures/v12_candidate_eligibility/benchmark_cases.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "reports/extraction/v12_candidate_eligibility/evaluation.json"
)
GOLD_MATCH_REPORT = (
    ROOT / "reports/extraction/v12_atomic_inventory_eval/evaluation.json"
)
ATOMIC_ROOT = ROOT / "data/staging/extraction/v12_atomic_inventory"


def _candidate(case_id: str, changes: dict[str, Any]) -> AtomicOutcomeCandidateV12:
    values: dict[str, Any] = {
        "candidate_id": f"AOC-{case_id}",
        "paper_id": "GP-FIXTURE",
        "claim_ids": [f"ACL-{case_id}"],
        "provisional_experiment_id": "PEX-FIXTURE",
        "subject_text": "reported subject",
        "predicate": "expressed",
        "object_text": "reported object",
        "endpoint_text": None,
        "qualitative_result": None,
        "numeric_value": None,
        "value_text": None,
        "unit": None,
        "polarity": "positive",
        "evidence_ids": [f"E-{case_id}"],
        "source_ids": [f"S-{case_id}"],
        "route_hint": "text",
        "confidence": "high",
        "review_reasons": [],
        "structural_signature": case_id,
    }
    values.update(changes)
    return AtomicOutcomeCandidateV12.model_validate(values)


def evaluate(fixture_path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    rows = []
    for case in fixture["cases"]:
        candidate = _candidate(case["case_id"], case["candidate"])
        assessment = assess_candidate_eligibility(candidate)
        expected = bool(case["expected_eligible"])
        rows.append(
            {
                "case_id": case["case_id"],
                "expected_eligible": expected,
                "observed_eligible": assessment["eligible"],
                "passed": expected == assessment["eligible"],
                "reasons": assessment["reasons"],
            }
        )
    positives = [row for row in rows if row["expected_eligible"]]
    negatives = [row for row in rows if not row["expected_eligible"]]
    true_positive = sum(row["observed_eligible"] for row in positives)
    true_negative = sum(not row["observed_eligible"] for row in negatives)
    gold_rows = []
    if GOLD_MATCH_REPORT.exists():
        gold_report = json.loads(GOLD_MATCH_REPORT.read_text(encoding="utf-8"))
        candidates_by_key = {
            (path.parent.name, row["candidate_id"]): row
            for path in ATOMIC_ROOT.glob("GP-*/candidates.json")
            for row in json.loads(path.read_text(encoding="utf-8"))
        }
        for result in gold_report.get("results", []):
            candidate_id = result.get("candidate_id")
            key = (result["paper_id"], candidate_id)
            if not result.get("recalled") or not candidate_id or key not in candidates_by_key:
                continue
            assessment = assess_candidate_eligibility(
                AtomicOutcomeCandidateV12.model_validate(candidates_by_key[key])
            )
            gold_rows.append(
                {
                    "gold_outcome_id": result["gold_outcome_id"],
                    "paper_id": result["paper_id"],
                    "candidate_id": candidate_id,
                    "observed_eligible": assessment["eligible"],
                    "reasons": assessment["reasons"],
                }
            )
    gold_accepted = sum(row["observed_eligible"] for row in gold_rows)
    return {
        "evaluation_version": "candidate-eligibility-eval-1.2.0",
        "fixture_version": fixture["fixture_version"],
        "positive_controls": len(positives),
        "positive_controls_accepted": true_positive,
        "positive_recall": true_positive / len(positives) if positives else 0.0,
        "negative_controls": len(negatives),
        "negative_controls_rejected": true_negative,
        "negative_rejection_rate": (
            true_negative / len(negatives) if negatives else 0.0
        ),
        "gold_matched_positive_controls": len(gold_rows),
        "gold_matched_positive_controls_accepted": gold_accepted,
        "gold_matched_positive_recall": (
            gold_accepted / len(gold_rows) if gold_rows else None
        ),
        "gate_passed": (
            all(row["passed"] for row in rows)
            and all(row["observed_eligible"] for row in gold_rows)
        ),
        "rows": rows,
        "gold_positive_rows": gold_rows,
        "paid_api_requests": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate(args.fixture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
