"""Select bounded, high-value atomic candidates for coverage and API packets."""

from __future__ import annotations

import re

from src.extraction.build_provisional_experiments import CELL_PATTERNS
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


GENERIC_SUBJECT = re.compile(
    r"^(?:reported outcome|results?|images?|analysis|data|table|figure)\b",
    re.I,
)
STRONG_RELATION = {
    "expressed",
    "uptake_by",
    "edited",
    "increased",
    "decreased",
    "reduced",
    "reached",
    "maintained",
    "colocalized_with",
    "localized_to",
    "recognized",
    "phagocytosed",
    "eliminated",
}


def relevance_score(candidate: AtomicOutcomeCandidateV12) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    combined = " ".join(
        filter(
            None,
            (
                candidate.subject_text,
                candidate.object_text,
                candidate.endpoint_text,
            ),
        )
    )
    if candidate.numeric_value is not None:
        score += 5
        reasons.append("numeric_result")
    if candidate.qualitative_result:
        score += 3
        reasons.append("qualitative_result")
    if candidate.endpoint_text:
        score += 3
        reasons.append("explicit_endpoint")
    if candidate.predicate in STRONG_RELATION:
        score += 3
        reasons.append("strong_relationship")
    if any(pattern.search(combined) for pattern in CELL_PATTERNS.values()):
        score += 3
        reasons.append("cell_context")
    if candidate.provisional_experiment_id:
        score += 2
        reasons.append("experiment_assigned")
    if candidate.polarity == "negative":
        score += 1
        reasons.append("negative_result")
    if GENERIC_SUBJECT.search(candidate.subject_text):
        score -= 4
        reasons.append("generic_subject_penalty")
    if len(candidate.object_text or "") > 220:
        score -= 2
        reasons.append("long_object_penalty")
    return score, reasons


def select_candidates(
    candidates: list[AtomicOutcomeCandidateV12],
    *,
    maximum: int = 24,
) -> tuple[list[AtomicOutcomeCandidateV12], list[dict]]:
    ranked = sorted(
        (
            (relevance_score(candidate), candidate)
            for candidate in candidates
        ),
        key=lambda row: (
            row[0][0],
            row[1].confidence == "high",
            row[1].candidate_id,
        ),
        reverse=True,
    )
    selected = []
    seen_predicates = set()
    for (score, _), candidate in ranked:
        if score < 5 or candidate.predicate in seen_predicates:
            continue
        selected.append(candidate)
        seen_predicates.add(candidate.predicate)
        if len(selected) == maximum:
            break
    selected_ids = {candidate.candidate_id for candidate in selected}
    for _, candidate in ranked:
        if candidate.candidate_id in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.candidate_id)
        if len(selected) == maximum:
            break
    audit = [
        {
            "candidate_id": candidate.candidate_id,
            "selected": candidate.candidate_id in selected_ids,
            "score": score,
            "reasons": reasons,
        }
        for (score, reasons), candidate in ranked
    ]
    return selected, audit
