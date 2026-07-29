"""Structurally deduplicate atomic claims without merging shared evidence IDs."""

from __future__ import annotations

import hashlib
import json
import re

from src.extraction.build_provisional_experiments import (
    CELL_PATTERNS,
    _payload_signature,
)
from src.extraction.v12_structure_contracts import (
    AtomicClaimV12,
    AtomicOutcomeCandidateV12,
)


def _normalized(value: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def _cell_keys(text: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            value
            for value, pattern in CELL_PATTERNS.items()
            if pattern.search(text)
        )
    )


def structural_signature(claim: AtomicClaimV12) -> str:
    evidence_text = " ".join(reference.quote for reference in claim.evidence)
    cells = _cell_keys(
        " ".join(
            filter(
                None,
                (claim.subject_text, claim.object_text, evidence_text),
            )
        )
    )
    payload = _payload_signature(evidence_text) or ""
    value = (
        f"{claim.numeric_value:g}"
        if claim.numeric_value is not None
        else _normalized(claim.value_text)
    )
    parts = [
        claim.provisional_experiment_id or "UNASSIGNED",
        claim.predicate,
        claim.polarity,
        payload,
        "|".join(cells),
        _normalized(claim.endpoint_text),
        value,
        _normalized(claim.unit),
        _normalized(claim.qualitative_result),
    ]
    if not cells and not claim.endpoint_text and not value:
        parts.extend(
            [_normalized(claim.subject_text), _normalized(claim.object_text)]
        )
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def build_atomic_candidates(
    paper_id: str,
    claims: list[AtomicClaimV12],
) -> list[AtomicOutcomeCandidateV12]:
    grouped: dict[str, list[AtomicClaimV12]] = {}
    for claim in claims:
        if claim.claim_kind != "outcome":
            continue
        grouped.setdefault(structural_signature(claim), []).append(claim)

    candidates = []
    for signature, rows in sorted(grouped.items()):
        first = rows[0]
        digest = hashlib.sha256(
            f"{paper_id}:{signature}".encode()
        ).hexdigest()[:16]
        evidence_ids = list(
            dict.fromkeys(
                reference.evidence_id
                for row in rows
                for reference in row.evidence
            )
        )
        source_ids = list(
            dict.fromkeys(
                reference.source_id
                for row in rows
                for reference in row.evidence
            )
        )
        review_reasons = []
        if first.provisional_experiment_id is None:
            review_reasons.append("experiment_assignment_unresolved")
        if any(row.review_status == "needs_review" for row in rows):
            review_reasons.append("claim_requires_review")
        candidates.append(
            AtomicOutcomeCandidateV12(
                candidate_id=f"AOC-{digest}",
                paper_id=paper_id,
                claim_ids=[row.claim_id for row in rows],
                provisional_experiment_id=first.provisional_experiment_id,
                subject_text=first.subject_text,
                predicate=first.predicate,
                object_text=first.object_text,
                endpoint_text=first.endpoint_text,
                qualitative_result=first.qualitative_result,
                numeric_value=first.numeric_value,
                value_text=first.value_text,
                unit=first.unit,
                polarity=first.polarity,
                evidence_ids=evidence_ids,
                source_ids=source_ids,
                route_hint="text",
                confidence="medium" if review_reasons else "high",
                review_reasons=review_reasons,
                structural_signature=signature,
            )
        )
    return candidates
