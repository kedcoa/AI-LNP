"""Assign atomic claims to coarse experiments, abstaining on context ties."""

from __future__ import annotations

from src.extraction.build_provisional_experiments import (
    ASSAY_PATTERNS,
    CELL_PATTERNS,
    _context,
    _payload_signature,
)
from src.extraction.v12_structure_contracts import (
    AtomicClaimV12,
    ProvisionalExperimentInventoryV12,
    ProvisionalExperimentV12,
)
from src.rag.compact_api_packet import CompactApiPacket


def _anchor_values(
    experiment: ProvisionalExperimentV12,
    anchor_type: str,
) -> set[str]:
    return {
        anchor.value
        for anchor in experiment.anchors
        if anchor.anchor_type == anchor_type
    }


def _anchor_evidence(
    experiment: ProvisionalExperimentV12,
    anchor_type: str | None = None,
) -> set[str]:
    return {
        evidence_id
        for anchor in experiment.anchors
        if anchor_type is None or anchor.anchor_type == anchor_type
        for evidence_id in anchor.evidence_ids
    }


def _claim_text(claim: AtomicClaimV12) -> str:
    return " ".join(reference.quote for reference in claim.evidence)


def _score(
    claim: AtomicClaimV12,
    experiment: ProvisionalExperimentV12,
    *,
    evidence_sources: dict[str, set[str]],
) -> tuple[int, list[str]]:
    text = _claim_text(claim)
    evidence_ids = {reference.evidence_id for reference in claim.evidence}
    score = 0
    reasons = []
    if evidence_ids & _anchor_evidence(experiment, "payload"):
        score += 10
        reasons.append("same_payload_anchor_evidence")
    elif evidence_ids & _anchor_evidence(experiment):
        score += 5
        reasons.append("same_experiment_anchor_evidence")
    claim_source_ids = {
        reference.source_id for reference in claim.evidence
    }
    anchor_source_ids = {
        source_id
        for evidence_id in _anchor_evidence(experiment)
        for source_id in evidence_sources.get(evidence_id, set())
    }
    if claim_source_ids & anchor_source_ids:
        score += 8
        reasons.append("same_source_block")

    signature = _payload_signature(text)
    if signature and signature in _anchor_values(experiment, "payload"):
        score += 6
        reasons.append("payload_signature")

    context = _context(text)
    if context != "unknown" and context in _anchor_values(experiment, "model"):
        score += 4
        reasons.append("experimental_context")

    for value, pattern in CELL_PATTERNS.items():
        if pattern.search(text) and value in _anchor_values(
            experiment, "cell_context"
        ):
            score += 2
            reasons.append(f"cell_context:{value}")
    for value, pattern in ASSAY_PATTERNS.items():
        if pattern.search(text) and value in _anchor_values(experiment, "assay"):
            score += 1
            reasons.append(f"assay:{value}")
    return score, reasons


def assign_claims(
    claims: list[AtomicClaimV12],
    inventory: ProvisionalExperimentInventoryV12,
    *,
    packet: CompactApiPacket | None = None,
) -> tuple[list[AtomicClaimV12], dict[str, list[str]]]:
    evidence_sources = (
        {
            evidence.evidence_id: set(evidence.source_ids)
            for evidence in packet.evidence
        }
        if packet is not None
        else {}
    )
    assigned = []
    diagnostics: dict[str, list[str]] = {}
    for claim in claims:
        text = _claim_text(claim)
        payload = _payload_signature(text)
        context = _context(text)
        direct_matches = [
            experiment
            for experiment in inventory.experiments
            if (
                {reference.evidence_id for reference in claim.evidence}
                & _anchor_evidence(experiment, "payload")
                or {
                    reference.source_id for reference in claim.evidence
                }
                & {
                    source_id
                    for evidence_id in _anchor_evidence(experiment)
                    for source_id in evidence_sources.get(evidence_id, set())
                }
            )
        ]
        same_payload = [
            experiment
            for experiment in inventory.experiments
            if payload and payload in _anchor_values(experiment, "payload")
        ]
        if (
            not direct_matches
            and context == "unknown"
            and len(same_payload) > 1
        ):
            assigned.append(
                claim.model_copy(update={"review_status": "needs_review"})
            )
            diagnostics[claim.claim_id] = [
                "abstained_multiple_contexts_for_same_payload"
            ]
            continue

        scored = [
            (
                *_score(
                    claim,
                    experiment,
                    evidence_sources=evidence_sources,
                ),
                experiment,
            )
            for experiment in inventory.experiments
        ]
        scored.sort(key=lambda row: row[0], reverse=True)
        if not scored or scored[0][0] < 6:
            assigned.append(
                claim.model_copy(update={"review_status": "needs_review"})
            )
            diagnostics[claim.claim_id] = ["no_supported_experiment_assignment"]
            continue
        top_score = scored[0][0]
        winners = [row for row in scored if row[0] == top_score]
        if len(winners) != 1:
            assigned.append(
                claim.model_copy(update={"review_status": "needs_review"})
            )
            diagnostics[claim.claim_id] = [
                "abstained_tied_experiment_assignment"
            ]
            continue
        score, reasons, experiment = winners[0]
        assigned.append(
            claim.model_copy(
                update={
                    "provisional_experiment_id": (
                        experiment.provisional_experiment_id
                    )
                }
            )
        )
        diagnostics[claim.claim_id] = [
            f"assigned_score:{score}",
            *reasons,
        ]
    return assigned, diagnostics
