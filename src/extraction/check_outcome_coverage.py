"""Compare local outcome groups with saved first-call outcomes without API use."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.extraction.assess_outcome_complexity import assess
from src.extraction.build_outcome_candidates import ENDPOINT_PATTERNS, build_candidates
from src.extraction.outcome_coverage_contracts import (
    CandidateMatch,
    CoverageReport,
    OutcomeCandidate,
    ReviewCandidate,
    UnmatchedCandidate,
)
from src.rag.compact_api_packet import CompactApiPacket


def _value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def _outcome_text(row: dict[str, Any]) -> str:
    values = [
        _value(row.get("endpoint")),
        _value(row.get("assay")),
        _value(row.get("qualitative_outcome")),
        _value(row.get("outcome_value")),
        _value(row.get("outcome_unit")),
    ]
    return " ".join(str(value) for value in values if value is not None)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _families(text: str) -> set[str]:
    return {
        name for name, pattern in ENDPOINT_PATTERNS.items() if re.search(pattern, text, re.I)
    }


def _evidence_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value.get("evidence_ids", []))
        for child in value.values():
            found |= _evidence_ids(child)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found |= _evidence_ids(child)
        return found
    return set()


def _score(candidate, outcome: dict[str, Any]) -> float:
    if set(candidate.evidence_ids) & _evidence_ids(outcome):
        return 1.0
    outcome_text = _outcome_text(outcome)
    if candidate.endpoint_family not in _families(outcome_text):
        return 0.0
    candidate_tokens = _tokens(candidate.evidence_text)
    outcome_tokens = _tokens(outcome_text)
    lexical = len(candidate_tokens & outcome_tokens) / max(1, len(outcome_tokens))
    number_bonus = 0.0
    value = _value(outcome.get("outcome_value"))
    if isinstance(value, (int, float)) and str(value) in candidate.evidence_text:
        number_bonus = 0.35
    return min(1.0, lexical + number_bonus)


def check(
    packet: CompactApiPacket,
    result: dict[str, Any],
    *,
    assessment=None,
    candidates: list[OutcomeCandidate] | None = None,
) -> CoverageReport:
    assessment = assessment or assess(packet)
    if result.get("eligibility", {}).get("decision") != "eligible":
        return CoverageReport(
            coverage_version="outcome-coverage-1.1.0",
            paper_id=packet.paper_id,
            complexity_route=assessment.route,
            candidate_groups=0,
            extracted_outcomes=len(result.get("outcomes", [])),
            matched_candidates=[],
            unmatched_candidates=[],
            review_candidates=[],
            status="not_applicable",
        )
    candidates = candidates if candidates is not None else build_candidates(packet)
    outcomes = result.get("outcomes", [])
    potential = sorted(
        (
            (_score(candidate, outcome), candidate, outcome)
            for candidate in candidates
            for outcome in outcomes
        ),
        key=lambda row: row[0],
        reverse=True,
    )
    used_candidates: set[str] = set()
    used_outcomes: set[str] = set()
    matches: list[CandidateMatch] = []
    for score, candidate, outcome in potential:
        outcome_id = str(outcome.get("outcome_id"))
        if score < 0.30:
            break
        if (
            candidate.candidate_id in used_candidates
            or outcome_id in used_outcomes
        ):
            continue
        used_candidates.add(candidate.candidate_id)
        used_outcomes.add(outcome_id)
        matches.append(
            CandidateMatch(
                candidate_id=candidate.candidate_id,
                outcome_id=outcome_id,
                score=round(score, 4),
            )
        )
    unmatched_rows = [
        row for row in candidates if row.candidate_id not in used_candidates
    ]
    high_rows = [row for row in unmatched_rows if row.confidence == "high"]
    actionable_rows = []
    duplicate_rows = []
    for row in high_rows:
        duplicate_of = next(
            (
                kept
                for kept in actionable_rows
                if kept.endpoint_family == row.endpoint_family
                and set(kept.evidence_ids) & set(row.evidence_ids)
            ),
            None,
        )
        if duplicate_of:
            duplicate_rows.append(row)
        else:
            actionable_rows.append(row)
    unmatched = [
        UnmatchedCandidate(
            candidate_id=row.candidate_id,
            endpoint_family=row.endpoint_family,
            route_hint=row.route_hint,
            evidence_ids=row.evidence_ids,
            figure_or_table=row.figure_or_table,
            confidence=row.confidence,
        )
        for row in actionable_rows
    ]
    review = [
        ReviewCandidate(
            candidate_id=row.candidate_id,
            endpoint_family=row.endpoint_family,
            route_hint=row.route_hint,
            evidence_ids=row.evidence_ids,
            figure_or_table=row.figure_or_table,
            reason="medium_confidence_candidate_not_allowed_to_trigger_repair",
        )
        for row in unmatched_rows
        if row.confidence != "high"
    ]
    review.extend(
        ReviewCandidate(
            candidate_id=row.candidate_id,
            endpoint_family=row.endpoint_family,
            route_hint=row.route_hint,
            evidence_ids=row.evidence_ids,
            figure_or_table=row.figure_or_table,
            reason="duplicate_or_overlapping_high_confidence_group",
        )
        for row in duplicate_rows
    )
    return CoverageReport(
        coverage_version="outcome-coverage-1.1.0",
        paper_id=packet.paper_id,
        complexity_route=assessment.route,
        candidate_groups=len(candidates),
        extracted_outcomes=len(outcomes),
        matched_candidates=matches,
        unmatched_candidates=unmatched,
        review_candidates=review,
        status=(
            "complete"
            if not unmatched and not review
            else "review_unmatched_groups"
        ),
    )


def check_paths(packet_path: Path, result_path: Path) -> CoverageReport:
    packet = CompactApiPacket.model_validate_json(packet_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    return check(packet, result)
