from src.extraction.build_g1_v3_boundary_review import build


def test_boundary_review_accounts_for_all_gold_papers():
    summary = build()
    assert len(summary["expected_zero_papers"]) + len(summary["automatic_consensus_papers"]) + len(summary["human_review_papers"]) == 9
