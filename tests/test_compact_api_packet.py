import json
from pathlib import Path

from src.rag.compact_api_packet import (
    API_PACKET_VERSION,
    build_api_packet,
    estimate_tokens,
    evidence_priority,
    frozen_gold_preservation_report,
)
from src.rag.compact_packet import (
    CompactEvidence,
    CompactEvidencePacket,
    DeduplicationSummary,
    SourceLocation,
)


def evidence(
    evidence_id: str,
    text: str,
    *,
    field_tags: list[str],
    field_groups: list[str],
    chunk_id: str,
    section: str = "Results",
    context_before: str | None = None,
) -> CompactEvidence:
    return CompactEvidence(
        evidence_id=evidence_id,
        clause_ids=[f"{chunk_id}:C001"],
        chunk_ids=[chunk_id],
        text=text,
        normalized_text_sha256="a" * 64,
        field_tags=field_tags,
        field_groups=field_groups,
        query_ids=["Q1"],
        entity_types=[],
        experiment_candidate_ids=[],
        source_locations=[
            SourceLocation(
                chunk_id=chunk_id,
                source_path="paper.xml",
                source_kind="pmc_xml",
                block_type="paragraph",
                section=section,
                xml_element_id=chunk_id,
            )
        ],
        context_before=context_before,
    )


def packet(rows: list[CompactEvidence]) -> CompactEvidencePacket:
    return CompactEvidencePacket(
        paper_id="GP-X",
        source_retrieval_packet="retrieval/GP-X.json",
        blocked_fields={"payload": ["test diagnostic"]},
        evidence=rows,
        deduplication=DeduplicationSummary(
            input_hits=4,
            unique_chunks=3,
            removed_chunk_duplicates=1,
            removed_normalized_passages=0,
            input_clauses=len(rows),
            unique_evidence_items=len(rows),
        ),
        packet_checksum="b" * 64,
    )


def test_estimate_tokens_is_deterministic():
    value = {"text": "LNP-A delivered mRNA."}
    assert estimate_tokens(value) == estimate_tokens(value)
    assert estimate_tokens(value) > 0


def test_direct_evidence_is_prioritized_over_background():
    direct = evidence(
        "E1",
        "LNP-A delivered mRNA intravenously at 1 mg/kg.",
        field_tags=["dose"],
        field_groups=["experiment_boundary"],
        chunk_id="B1",
    )
    background = evidence(
        "E2",
        "Liver disease is a major global health problem.",
        field_tags=["dose"],
        field_groups=["experiment_boundary"],
        chunk_id="B2",
        section="Introduction",
    )
    assert evidence_priority(direct)[0] > evidence_priority(background)[0]


def test_api_packet_uses_shared_sources_and_retrieval_field_name():
    rows = [
        evidence(
            "E1",
            "LNP-A delivered mRNA.",
            field_tags=["formulation", "payload"],
            field_groups=["formulation"],
            chunk_id="B1",
        ),
        evidence(
            "E2",
            "Expression increased.",
            field_tags=["formulation", "outcome"],
            field_groups=["outcome"],
            chunk_id="B1",
        ),
    ]
    api_packet, manifest = build_api_packet(
        packet(rows),
        packet_budget_tokens=10_000,
    )
    assert api_packet.packet_version == API_PACKET_VERSION
    assert len(api_packet.sources) == 1
    assert api_packet.evidence[0].retrieval_field_tags == [
        "formulation",
        "payload",
    ]
    assert api_packet.blocked_fields == ["payload"]
    assert manifest["blocked_fields_with_diagnostics"] == {
        "payload": ["test diagnostic"]
    }


def test_budget_excludes_lower_priority_evidence_and_logs_it():
    direct = evidence(
        "E1",
        "LNP-A delivered mRNA intravenously at 1 mg/kg.",
        field_tags=["dose"],
        field_groups=["experiment_boundary"],
        chunk_id="B1",
    )
    background = evidence(
        "E2",
        "Background discussion " * 200,
        field_tags=["dose"],
        field_groups=["experiment_boundary"],
        chunk_id="B2",
        section="Introduction",
    )
    api_packet, manifest = build_api_packet(
        packet([background, direct]),
        packet_budget_tokens=250,
    )
    assert [row.evidence_id for row in api_packet.evidence] == ["E1"]
    assert manifest["excluded_passages"][0]["evidence_id"] == "E2"
    assert manifest["excluded_passages"][0]["exclusion_reason"] == (
        "evidence_budget_exceeded"
    )


def test_direct_quantitative_outcome_outranks_caption_only_evidence():
    direct_outcome = evidence(
        "E-OUTCOME",
        "Over 80% of BMDMs expressed GFP after alpha-CD163 LNP treatment.",
        field_tags=["outcomes"],
        field_groups=["outcome"],
        chunk_id="B-OUTCOME",
    )
    caption = evidence(
        "E-CAPTION",
        "Figure 2 shows representative GFP expression after LNP treatment.",
        field_tags=["outcomes"],
        field_groups=["outcome"],
        chunk_id="B-CAPTION",
    )
    assert evidence_priority(direct_outcome)[0] > evidence_priority(caption)[0]
    assert "direct_quantitative_outcome" in evidence_priority(direct_outcome)[1]


def test_quantitative_biological_outcome_survives_imperfect_field_tags():
    mislabeled = evidence(
        "E-MISLABELED",
        "Fewer than 20% of BMDMs expressed GFP after unmodified LNP delivery.",
        field_tags=["payload", "delivery_recipient_cell_reported"],
        field_groups=["payload", "recipient_cell"],
        chunk_id="B-MISLABELED",
    )
    score, reasons = evidence_priority(mislabeled)
    assert score >= 180
    assert "direct_quantitative_outcome" in reasons


def test_qualitative_biological_outcomes_are_not_ranked_as_background():
    cases = [
        "Few F4/80-positive Kupffer cells expressed eGFP.",
        "GFP signal colocalized with the LSEC marker LYVE-1.",
        (
            "FAPCAR macrophages recognized, phagocytosed, and eliminated "
            "activated HSCs."
        ),
    ]
    for index, text in enumerate(cases):
        qualitative = evidence(
            f"E-QUAL-{index}",
            text,
            field_tags=["delivery_recipient_cell_reported"],
            field_groups=["recipient_cell"],
            chunk_id=f"B-QUAL-{index}",
        )
        score, reasons = evidence_priority(qualitative)
        assert score >= 180
        assert "direct_qualitative_outcome" in reasons


def test_assay_setup_is_not_promoted_as_a_qualitative_result():
    setup = evidence(
        "E-SETUP",
        (
            "Liver sections were stained with anti-GFP and anti-LYVE-1 "
            "antibodies."
        ),
        field_tags=["outcomes"],
        field_groups=["outcome"],
        chunk_id="B-SETUP",
    )
    _, reasons = evidence_priority(setup)
    assert "direct_qualitative_outcome" not in reasons


def test_context_reference_is_an_evidence_id_not_repeated_text():
    first_text = "LNP-A delivered mRNA to hepatocytes."
    rows = [
        evidence(
            "E1",
            first_text,
            field_tags=["recipient"],
            field_groups=["experiment_boundary"],
            chunk_id="B1",
        ),
        evidence(
            "E2",
            "This formulation produced luciferase expression.",
            field_tags=["outcome"],
            field_groups=["outcome"],
            chunk_id="B1",
            context_before=first_text,
        ),
    ]
    api_packet, _ = build_api_packet(
        packet(rows),
        packet_budget_tokens=10_000,
    )
    by_id = {row.evidence_id: row for row in api_packet.evidence}
    assert by_id["E2"].context_before_evidence_id == "E1"
    saved = json.dumps(api_packet.model_dump(mode="json"))
    assert saved.count(first_text) == 1


def test_frozen_gold_locations_are_not_lost_during_deduplication(
    tmp_path: Path,
):
    review_root = tmp_path / "review"
    retrieval_root = tmp_path / "retrieval"
    review_root.mkdir()
    retrieval_root.mkdir()
    review_packet = packet(
        [
            evidence(
                "E1",
                "LNP-A delivered mRNA.",
                field_tags=["payload"],
                field_groups=["payload"],
                chunk_id="p1",
            )
        ]
    )
    (review_root / "GP-X.json").write_text(
        review_packet.model_dump_json(),
        encoding="utf-8",
    )
    (retrieval_root / "GP-X.json").write_text(
        json.dumps(
            {
                "paper_id": "GP-X",
                "packets": {
                    "payload": {
                        "hits": [
                            {
                                "source_path": "paper.xml",
                                "xml_element_id": "p1",
                                "page_number": None,
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    gold_path = tmp_path / "evidence.csv"
    gold_path.write_text(
        "evidence_id,gold_paper_id,xml_file,xml_element_id,page_number\n"
        "GOLD-1,GP-X,paper.xml,p1,\n",
        encoding="utf-8",
    )
    report = frozen_gold_preservation_report(
        review_packet_root=review_root,
        retrieval_root=retrieval_root,
        gold_evidence_path=gold_path,
    )
    assert report["frozen_gold_locations"] == 1
    assert report["available_before_deduplication"] == 1
    assert report["available_after_deduplication"] == 1
    assert report["lost_during_deduplication"] == 0


def test_project_frozen_gold_locations_are_preserved_after_deduplication():
    report = frozen_gold_preservation_report()
    assert report["available_before_deduplication"] > 0
    assert report["lost_during_deduplication"] == 0
