from src.extraction.evaluate_candidate_eligibility_v12 import evaluate


def test_candidate_eligibility_controls_pass_without_trading_away_recall():
    report = evaluate()
    assert report["gate_passed"]
    assert report["positive_recall"] == 1.0
    assert report["negative_rejection_rate"] == 1.0
    assert report["gold_matched_positive_controls"] >= 12
    assert report["gold_matched_positive_recall"] == 1.0
    assert report["paid_api_requests"] == 0
