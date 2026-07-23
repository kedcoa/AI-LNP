from src.extraction.build_g1_v2_review import build


def test_v2_review_packet_covers_all_eligible_papers():
    summary = build()
    assert len(summary["paper_status"]) == 9
    assert summary["reported_fields_with_exact_abstract_quote"] <= summary["reported_source_fields"]
    assert summary["g1_status"] == "pending_human_verification"
