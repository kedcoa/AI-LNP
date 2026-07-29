from src.extraction.assign_atomic_claims import assign_claims
from src.extraction.build_atomic_candidates_v12 import build_atomic_candidates
from src.extraction.v12_structure_contracts import (
    AtomicClaimV12,
    EvidenceReferenceV12,
    ProvisionalExperimentInventoryV12,
    ProvisionalExperimentV12,
)
from src.rag.compact_api_packet import (
    ApiEvidence,
    ApiSource,
    CompactApiPacket,
)


def claim(
    identifier: str,
    predicate: str,
    quote: str,
    *,
    subject: str = "LSECs",
    object_text: str = "GFP",
):
    return AtomicClaimV12(
        claim_id=identifier,
        claim_kind="outcome",
        subject_text=subject,
        predicate=predicate,
        object_text=object_text,
        qualitative_result="reported",
        polarity="positive",
        evidence=[
            EvidenceReferenceV12(
                evidence_id="E1",
                source_id="S1",
                quote=quote,
            )
        ],
    )


def experiment(identifier: str, payload: str, context: str, evidence_id: str):
    return ProvisionalExperimentV12(
        provisional_experiment_id=identifier,
        label=f"{payload}/{context}",
        anchors=[
            {
                "anchor_type": "payload",
                "value": payload,
                "evidence_ids": [evidence_id],
            },
            {
                "anchor_type": "model",
                "value": context,
                "evidence_ids": [evidence_id],
            },
        ],
        boundary_status="inferred",
        boundary_reason="test",
        confidence="medium",
    )


def inventory(experiments):
    return ProvisionalExperimentInventoryV12(
        inventory_version="provisional-experiments-1.2.0",
        paper_id="GP-X",
        source_packet_checksum="a" * 64,
        experiments=experiments,
    )


def test_direct_anchor_evidence_assigns_reporter_claim():
    reporter = experiment("PEX-REPORTER", "egfp_gfp", "in_vivo", "E1")
    editing = experiment("PEX-EDIT", "cas9_sgrna", "in_vivo", "E2")
    assigned, _ = assign_claims(
        [claim("ACL-1", "expressed", "LSECs expressed GFP after LNP injection.")],
        inventory([reporter, editing]),
    )
    assert assigned[0].provisional_experiment_id == "PEX-REPORTER"


def test_same_payload_without_context_forces_abstention():
    in_vitro = experiment("PEX-IVT", "fapcar", "in_vitro", "E2")
    in_vivo = experiment("PEX-IVV", "fapcar", "in_vivo", "E3")
    ambiguous = claim(
        "ACL-1",
        "eliminated",
        "FAPCAR macrophages eliminated activated HSCs.",
        subject="FAPCAR macrophages",
        object_text="activated HSCs",
    )
    assigned, diagnostics = assign_claims(
        [ambiguous], inventory([in_vitro, in_vivo])
    )
    assert assigned[0].provisional_experiment_id is None
    assert diagnostics["ACL-1"] == [
        "abstained_multiple_contexts_for_same_payload"
    ]


def test_shared_evidence_does_not_merge_different_predicates():
    claims = [
        claim("ACL-1", "recognized", "Macrophages recognized and eliminated HSCs."),
        claim("ACL-2", "eliminated", "Macrophages recognized and eliminated HSCs."),
    ]
    candidates = build_atomic_candidates("GP-X", claims)
    assert len(candidates) == 2
    assert {row.predicate for row in candidates} == {
        "recognized",
        "eliminated",
    }


def test_duplicate_claims_merge_by_structure_not_evidence_identity():
    first = claim("ACL-1", "expressed", "LSECs expressed GFP.")
    second = claim("ACL-2", "expressed", "GFP was expressed by LSECs.")
    second.evidence[0].evidence_id = "E2"
    candidates = build_atomic_candidates("GP-X", [first, second])
    assert len(candidates) == 1
    assert set(candidates[0].claim_ids) == {"ACL-1", "ACL-2"}
    assert set(candidates[0].evidence_ids) == {"E1", "E2"}


def test_same_source_block_can_supply_omitted_payload_context():
    reporter = experiment("PEX-REPORTER", "egfp_gfp", "in_vivo", "E2")
    value = CompactApiPacket(
        paper_id="GP-X",
        blocked_fields=[],
        sources=[
            ApiSource(
                source_id="S1",
                chunk_id="B1",
                source_path="paper.xml",
                source_kind="pmc_xml",
                block_type="paragraph",
                section="Results",
            )
        ],
        evidence=[
            ApiEvidence(
                evidence_id="E1",
                text="LSECs showed reporter expression.",
                retrieval_field_tags=["outcomes"],
                source_ids=["S1"],
            ),
            ApiEvidence(
                evidence_id="E2",
                text="GFP mRNA-LNP was injected into mice.",
                retrieval_field_tags=["outcomes"],
                source_ids=["S1"],
            ),
        ],
        packet_checksum="a" * 64,
    )
    result_claim = claim(
        "ACL-1",
        "expressed",
        "LSECs showed reporter expression.",
        object_text="reporter",
    )
    assigned, diagnostics = assign_claims(
        [result_claim],
        inventory([reporter]),
        packet=value,
    )
    assert assigned[0].provisional_experiment_id == "PEX-REPORTER"
    assert "same_source_block" in diagnostics["ACL-1"]
