import hashlib
import json

from src.extraction.atomize_outcome_claims import atomize
from src.rag.compact_api_packet import (
    ApiEvidence,
    ApiSource,
    CompactApiPacket,
)


def packet(text: str) -> CompactApiPacket:
    source = ApiSource(
        source_id="S1",
        chunk_id="B1",
        source_path="paper.xml",
        source_kind="pmc_xml",
        block_type="paragraph",
        section="Results",
    )
    evidence = ApiEvidence(
        evidence_id="E1",
        text=text,
        retrieval_field_tags=["outcomes"],
        source_ids=["S1"],
    )
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": "GP-X",
        "blocked_fields": [],
        "sources": [source.model_dump(mode="json", exclude_none=True)],
        "evidence": [evidence.model_dump(mode="json", exclude_none=True)],
    }
    canonical = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return CompactApiPacket.model_validate(
        {
            **unsigned,
            "packet_checksum": hashlib.sha256(canonical.encode()).hexdigest(),
        }
    )


def test_mixed_cell_sentence_becomes_distinct_positive_and_negative_claims():
    claims = atomize(
        packet(
            "eGFP expression was absent in cholangiocytes, while few "
            "F4/80-positive Kupffer cells expressed eGFP."
        )
    )
    assert len(claims) == 2
    assert {claim.polarity for claim in claims} == {"negative", "positive"}
    kupffer = next(
        claim for claim in claims if "Kupffer" in claim.subject_text
    )
    assert kupffer.predicate == "expressed"
    assert kupffer.qualitative_result == "few"


def test_coordinated_verbs_become_three_atomic_claims():
    claims = atomize(
        packet(
            "FAPCAR macrophages recognized, phagocytosed, and eliminated "
            "activated HSCs."
        )
    )
    assert {claim.predicate for claim in claims} == {
        "recognized",
        "phagocytosed",
        "eliminated",
    }
    assert {claim.object_text for claim in claims} == {"activated HSCs"}


def test_colocalization_and_expression_are_not_blended():
    claims = atomize(
        packet(
            "Images showed colocalization of LYVE-1 and GFP signals, "
            "indicating that LSECs can express GFP protein."
        )
    )
    assert {claim.predicate for claim in claims} == {
        "colocalized_with",
        "expressed",
    }


def test_not_only_is_not_mistaken_for_negative_polarity():
    claims = atomize(
        packet(
            "LSECs not only uptake LNPs but can also express GFP protein."
        )
    )
    assert {row.predicate for row in claims} == {"uptake_by", "expressed"}
    assert {row.polarity for row in claims} == {"positive"}
    uptake = next(row for row in claims if row.predicate == "uptake_by")
    expression = next(row for row in claims if row.predicate == "expressed")
    assert uptake.object_text == "LNPs"
    assert expression.object_text == "GFP protein"


def test_dangling_figure_citation_is_not_part_of_the_atomic_fact():
    claims = atomize(
        packet("Virtually all hepatocytes expressed eGFP (Fig. 2A).")
    )
    assert len(claims) == 1
    assert claims[0].subject_text == "hepatocytes"
    assert claims[0].object_text == "eGFP"


def test_liver_parenchyma_is_used_instead_of_an_adjective_subject():
    claims = atomize(
        packet(
            "A pronounced eGFP expression was obvious in the parenchyma of "
            "the liver as early as 5 h after eGFP mRNA-LNP administration."
        )
    )
    expression = next(row for row in claims if row.predicate == "expressed")
    assert expression.subject_text == "parenchyma of the liver"


def test_lower_expression_is_one_decreased_claim_not_a_duplicate_expression():
    claims = atomize(
        packet("However, lower transgene expression was observed in LSECs.")
    )
    assert [row.predicate for row in claims] == ["decreased"]
    assert claims[0].subject_text == "LSECs"


def test_mixed_positive_and_absent_cell_expression_is_split_by_polarity():
    claims = atomize(
        packet(
            "In the Fibrosis group, PCNA expression was significantly "
            "increased in HSCs and was almost absent in Heps."
        )
    )
    assert {(row.predicate, row.polarity) for row in claims} == {
        ("increased", "positive"),
        ("expressed", "negative"),
    }
    assert {row.subject_text for row in claims} == {"HSCs", "Heps"}


def test_measured_clause_is_separated_from_trailing_speculation():
    claims = atomize(
        packet(
            "Treatment decreased serum ALT levels at T8, suggesting that "
            "repeated injections could alleviate chronic liver damage."
        )
    )
    assert [row.predicate for row in claims] == ["decreased"]
    assert "could" not in (claims[0].object_text or "").casefold()


def test_comparator_subclause_is_marked_for_review():
    claims = atomize(
        packet(
            "Steatosis decreased after treatment compared to control, in "
            "which steatosis was maintained."
        )
    )
    maintained = next(row for row in claims if row.predicate == "maintained")
    assert maintained.review_status == "needs_review"


def test_nominal_colocalization_study_is_context_not_a_relationship():
    claims = atomize(
        packet(
            "In colocalization studies, LNP exhibited specific expression "
            "of ZsGreen in macrophages, with no expression in other cells."
        )
    )
    assert {row.predicate for row in claims} == {"expressed"}


def test_quantitative_qualifier_and_unit_are_preserved():
    claims = atomize(
        packet("Over 80% of BMDMs expressed GFP after LNP treatment.")
    )
    claim = next(row for row in claims if row.predicate == "expressed")
    assert claim.numeric_value == 80
    assert claim.value_text.lower().startswith("over")
    assert claim.unit == "%"


def test_non_outcome_evidence_is_not_atomized():
    value = packet("Cells were incubated until they expressed the reporter.")
    value.evidence[0].retrieval_field_tags = ["methods"]
    assert atomize(value) == []


def test_cell_marker_digits_are_not_treated_as_an_outcome_value():
    claims = atomize(packet("Few F4/80-positive Kupffer cells expressed eGFP."))
    claim = next(row for row in claims if row.predicate == "expressed")
    assert claim.numeric_value is None


def test_relationship_uses_nearest_numeric_result():
    claims = atomize(
        packet(
            "Other variants represented 50% of events, while LSECs showed "
            "a total deletion frequency of approximately 16.5%."
        )
    )
    edited = next(row for row in claims if row.predicate == "edited")
    assert edited.numeric_value == 16.5


def test_plural_lsecs_and_hepatocytes_pass_the_context_gate():
    claims = atomize(
        packet(
            "The F8 gene was edited in 60.54% of hepatocytes, whereas "
            "LSECs showed gene editing rates of approximately 16.50%."
        )
    )
    assert {row.numeric_value for row in claims if row.predicate == "edited"} == {
        60.54,
        16.5,
    }


def test_generated_average_is_an_outcome_relationship():
    claims = atomize(
        packet(
            "Treated mice generated an average of 3.30% of FVIII activity "
            "over 26 weeks."
        )
    )
    claim = next(row for row in claims if row.predicate == "reached")
    assert claim.numeric_value == 3.3
    assert claim.endpoint_text == "FVIII activity"
