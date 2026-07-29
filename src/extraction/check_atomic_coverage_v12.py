"""Gold-blind one-to-one coverage for selected atomic candidates."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.extraction.build_provisional_experiments import CELL_PATTERNS
from src.extraction.freeze_v12_baseline import _result_path
from src.extraction.select_atomic_candidates_v12 import relevance_score
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


ROOT = Path(__file__).resolve().parents[2]
ATOMIC_ROOT = ROOT / "data/staging/extraction/v12_atomic_inventory"
OUTPUT_ROOT = ROOT / "data/staging/extraction/v12_atomic_coverage"
MATCH_THRESHOLD = 7
PREDICATE_SIGNALS = {
    "expressed": r"\b(?:express|reporter|GFP|eGFP|luciferase)\w*\b",
    "delivered_to": r"\b(?:deliver|transfect|express|mRNA)\w*\b",
    "uptake_by": r"\b(?:uptake|internaliz)\w*\b",
    "edited": r"\b(?:edit|insert|delet|indel)\w*\b",
    "increased": r"\b(?:increase|higher|enhanc)\w*\b",
    "decreased": r"\b(?:decrease|lower)\w*\b",
    "reduced": r"\b(?:reduc|attenuat|damage|fibrosis)\w*\b",
    "reached": r"\b(?:reach|achiev|activity)\w*\b",
    "maintained": r"\b(?:maintain|sustain|activity)\w*\b",
    "colocalized_with": r"\b(?:colocali[sz]|co-stain|marker)\w*\b",
    "localized_to": r"\b(?:locali[sz]|cell marker)\w*\b",
    "recognized": r"\brecogniz\w*\b",
    "phagocytosed": r"\bphagocyt\w*\b",
    "eliminated": r"\b(?:eliminat|eradicate|killing)\w*\b",
}


def _value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def _outcome_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(_value(value))
        for key, value in row.items()
        if key != "outcome_id" and _value(value) is not None
    )


def _evidence_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value.get("evidence_ids", []))
        for child in value.values():
            found |= _evidence_ids(child)
        return found
    if isinstance(value, list):
        found = set()
        for child in value:
            found |= _evidence_ids(child)
        return found
    return set()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) >= 2
    }


def _candidate_semantic_text(candidate: AtomicOutcomeCandidateV12) -> str:
    return " ".join(
        str(value)
        for value in (
            candidate.subject_text,
            candidate.predicate,
            candidate.object_text,
            candidate.endpoint_text,
            candidate.qualitative_result,
            candidate.numeric_value,
            candidate.unit,
        )
        if value is not None
    )


def _cell_keys(text: str) -> set[str]:
    return {
        value
        for value, pattern in CELL_PATTERNS.items()
        if pattern.search(text)
    }


def match_score(
    candidate: AtomicOutcomeCandidateV12,
    outcome: dict[str, Any],
) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    outcome_text = _outcome_text(outcome)
    overlap = _tokens(_candidate_semantic_text(candidate)) & _tokens(outcome_text)
    if overlap:
        score += min(5, len(overlap))
        reasons.append(f"semantic_overlap:{len(overlap)}")
    if set(candidate.evidence_ids) & _evidence_ids(outcome):
        score += 4
        reasons.append("shared_evidence")
    if re.search(PREDICATE_SIGNALS[candidate.predicate], outcome_text, re.I):
        score += 3
        reasons.append("compatible_relationship")
    candidate_cells = _cell_keys(_candidate_semantic_text(candidate))
    outcome_cells = _cell_keys(outcome_text)
    if candidate_cells:
        if candidate_cells & outcome_cells:
            score += 3
            reasons.append("compatible_cell_target")
        elif outcome_cells:
            score -= 7
            reasons.append("different_cell_target")
        else:
            score -= 5
            reasons.append("missing_cell_target")
    outcome_number = _value(outcome.get("outcome_value"))
    if candidate.numeric_value is not None and isinstance(
        outcome_number, (int, float)
    ):
        if abs(candidate.numeric_value - float(outcome_number)) < 0.011:
            score += 6
            reasons.append("exact_numeric_value")
        else:
            score -= 4
            reasons.append("different_numeric_value")
    return score, reasons


def _matches(candidates, outcomes):
    potential = sorted(
        (
            (*match_score(candidate, outcome), candidate_index, outcome_index)
            for candidate_index, candidate in enumerate(candidates)
            for outcome_index, outcome in enumerate(outcomes)
        ),
        key=lambda row: row[0],
        reverse=True,
    )
    used_candidates = set()
    used_outcomes = set()
    matches = []
    for score, reasons, candidate_index, outcome_index in potential:
        if score < MATCH_THRESHOLD:
            break
        if candidate_index in used_candidates or outcome_index in used_outcomes:
            continue
        used_candidates.add(candidate_index)
        used_outcomes.add(outcome_index)
        matches.append((candidate_index, outcome_index, score, reasons))
    return matches


def _bounded_actionable(unmatched, maximum: int = 8):
    pool = [
        row
        for row in unmatched
        if row[1].confidence == "high"
        and row[1].provisional_experiment_id is not None
        and row[2][0] >= 8
    ]
    selected = []
    seen_predicates = set()
    for row in pool:
        predicate = row[1].predicate
        if predicate in seen_predicates:
            continue
        selected.append(row)
        seen_predicates.add(predicate)
        if len(selected) == maximum:
            return selected
    selected_ids = {row[1].candidate_id for row in selected}
    for row in pool:
        if row[1].candidate_id in selected_ids:
            continue
        selected.append(row)
        if len(selected) == maximum:
            break
    return selected


def check_paper(paper_id: str) -> dict:
    candidates = [
        AtomicOutcomeCandidateV12.model_validate(row)
        for row in json.loads(
            (
                ATOMIC_ROOT / paper_id / "selected_candidates.json"
            ).read_text(encoding="utf-8")
        )
    ]
    result_path = _result_path(paper_id)
    if result_path is None:
        raise FileNotFoundError(f"No current result for {paper_id}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    outcomes = result.get("outcomes", [])
    matches = _matches(candidates, outcomes)
    matched_candidate_indexes = {row[0] for row in matches}
    matched_outcome_indexes = {row[1] for row in matches}
    unmatched = [
        (index, candidate, relevance_score(candidate))
        for index, candidate in enumerate(candidates)
        if index not in matched_candidate_indexes
    ]
    unmatched.sort(key=lambda row: row[2][0], reverse=True)
    actionable = _bounded_actionable(unmatched)
    actionable_ids = {row[1].candidate_id for row in actionable}
    report = {
        "coverage_version": "atomic-outcome-coverage-1.2.0",
        "paper_id": paper_id,
        "source_result_path": str(result_path.relative_to(ROOT)),
        "selected_candidate_count": len(candidates),
        "extracted_outcome_count": len(outcomes),
        "matches": [
            {
                "candidate_id": candidates[candidate_index].candidate_id,
                "outcome_id": str(outcomes[outcome_index].get("outcome_id")),
                "score": score,
                "reasons": reasons,
            }
            for candidate_index, outcome_index, score, reasons in matches
        ],
        "unmatched_extracted_outcome_ids": [
            str(outcome.get("outcome_id"))
            for index, outcome in enumerate(outcomes)
            if index not in matched_outcome_indexes
        ],
        "missing_text_record_candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "provisional_experiment_id": (
                    candidate.provisional_experiment_id
                ),
                "predicate": candidate.predicate,
                "subject_text": candidate.subject_text,
                "object_text": candidate.object_text,
                "endpoint_text": candidate.endpoint_text,
                "qualitative_result": candidate.qualitative_result,
                "numeric_value": candidate.numeric_value,
                "evidence_ids": candidate.evidence_ids,
                "relevance_score": score,
                "relevance_reasons": reasons,
            }
            for _, candidate, (score, reasons) in actionable
        ],
        "review_candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "reason": (
                    "not_in_bounded_actionable_set"
                    if candidate.candidate_id not in actionable_ids
                    else "actionable"
                ),
                "relevance_score": score,
            }
            for _, candidate, (score, _) in unmatched
            if candidate.candidate_id not in actionable_ids
        ],
        "status": (
            "missing_text_records"
            if actionable
            else ("review" if unmatched else "complete")
        ),
        "paid_api_requests": 0,
    }
    destination = OUTPUT_ROOT / paper_id
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    args = parser.parse_args()
    paper_ids = args.paper_id or [
        path.name for path in ATOMIC_ROOT.glob("GP-*") if path.is_dir()
    ]
    reports = [check_paper(paper_id) for paper_id in sorted(paper_ids)]
    summary = {
        "coverage_version": "atomic-outcome-coverage-summary-1.2.0",
        "papers": len(reports),
        "selected_candidates": sum(
            row["selected_candidate_count"] for row in reports
        ),
        "matched_candidates": sum(len(row["matches"]) for row in reports),
        "missing_text_record_candidates": sum(
            len(row["missing_text_record_candidates"]) for row in reports
        ),
        "review_candidates": sum(
            len(row["review_candidates"]) for row in reports
        ),
        "paid_api_requests": 0,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
