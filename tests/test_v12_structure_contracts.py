import pytest
from pydantic import ValidationError

from src.extraction.v12_structure_contracts import (
    AtomicClaimV12,
    EvidenceReferenceV12,
    MentionV12,
    ProvisionalExperimentInventoryV12,
    ProvisionalExperimentV12,
)


def evidence(quote: str = "Few Kupffer cells expressed eGFP."):
    return [
        EvidenceReferenceV12(
            evidence_id="E1",
            source_id="S1",
            quote=quote,
        )
    ]


def experiment(identifier: str = "PEX-001", claim_ids: list[str] | None = None):
    return ProvisionalExperimentV12(
        provisional_experiment_id=identifier,
        label="Reporter expression in liver cells",
        anchors=[
            {
                "anchor_type": "payload",
                "value": "eGFP mRNA",
                "evidence_ids": ["E1"],
            }
        ],
        claim_ids=claim_ids or [],
        boundary_status="inferred",
        boundary_reason="A reporter payload and result cluster identify this activity.",
        confidence="medium",
    )


def test_a_cell_mention_is_grounded_but_not_an_outcome_candidate():
    mention = MentionV12(
        mention_id="MEN-CELL-1",
        mention_type="cell",
        text="Kupffer cells",
        evidence=evidence(),
    )
    assert mention.mention_type == "cell"

    with pytest.raises(ValidationError, match="asserted object, endpoint, or result"):
        AtomicClaimV12(
            claim_id="ACL-EMPTY",
            claim_kind="outcome",
            subject_text="Kupffer cells",
            predicate="expressed",
            polarity="neutral",
            evidence=evidence(),
        )


def test_qualitative_outcome_does_not_require_a_separate_endpoint():
    claim = AtomicClaimV12(
        claim_id="ACL-QUAL-1",
        claim_kind="outcome",
        subject_text="F4/80-positive Kupffer cells",
        predicate="expressed",
        object_text="eGFP",
        qualitative_result="few",
        polarity="positive",
        evidence=evidence(),
    )
    assert claim.endpoint_text is None
    assert claim.numeric_value is None


def test_one_evidence_item_can_support_multiple_atomic_relationships():
    quote = (
        "Macrophages recognized, phagocytosed, and eliminated activated HSCs."
    )
    claims = [
        AtomicClaimV12(
            claim_id=f"ACL-{predicate.upper()}",
            claim_kind="outcome",
            subject_text="Macrophages",
            predicate=predicate,
            object_text="activated HSCs",
            qualitative_result="reported",
            polarity="positive",
            evidence=evidence(quote),
        )
        for predicate in ("recognized", "phagocytosed", "eliminated")
    ]
    assert len(claims) == 3
    assert {row.evidence[0].evidence_id for row in claims} == {"E1"}


def test_inventory_rejects_double_assignment_of_an_atomic_claim():
    with pytest.raises(ValidationError, match="cannot belong to two"):
        ProvisionalExperimentInventoryV12(
            inventory_version="provisional-experiments-1.2.0",
            paper_id="GP-X",
            source_packet_checksum="a" * 64,
            experiments=[
                experiment("PEX-001", ["ACL-1"]),
                experiment("PEX-002", ["ACL-1"]),
            ],
        )


def test_inventory_cannot_reuse_gold_experiment_ids():
    with pytest.raises(ValidationError):
        experiment("GX-001")
