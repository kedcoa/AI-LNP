"""Controlled, user-facing labels for import review reasons."""

from __future__ import annotations

import re

from src.database.import_contracts import ImportBundle


REVIEW_TAGS = {
    "missing_dose": "Missing dose",
    "missing_formulation_ratio": "Missing formulation ratio",
    "missing_outcome_value": "Missing outcome value",
    "missing_evidence_excerpt": "Missing evidence excerpt",
    "source_file_unavailable": "Source file unavailable",
    "conflicting_formulation": "Conflicting formulation",
    "conflicting_target_cell": "Conflicting target cell",
    "conflicting_outcome": "Conflicting outcome",
    "experiment_link_unclear": "Experiment link unclear",
    "outcome_link_unclear": "Outcome link unclear",
    "unsupported_value": "Unsupported value",
}
FALLBACK_REVIEW_TAG = "Needs human verification"


def review_tag_for_reason(reason_code: str) -> str:
    """Translate a machine reason without exposing internal pipeline language."""

    normalized = re.sub(r"[^a-z0-9]+", "_", reason_code.lower()).strip("_")
    return REVIEW_TAGS.get(normalized, FALLBACK_REVIEW_TAG)


def derive_review_tags(bundle: ImportBundle) -> tuple[str, ...]:
    """Return de-duplicated controlled tags in first-seen review order."""

    tags: list[str] = []
    for review in bundle.reviews:
        tag = review_tag_for_reason(review.reason_code)
        if tag not in tags:
            tags.append(tag)
    return tuple(tags)


__all__ = [
    "FALLBACK_REVIEW_TAG",
    "REVIEW_TAGS",
    "derive_review_tags",
    "review_tag_for_reason",
]
