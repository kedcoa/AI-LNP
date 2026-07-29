from src.extraction.finalize_g1 import finalize


def test_completed_review_freezes_failed_g1_decision():
    result = finalize()
    assert result["review_completion"]["rows"] == 32
    assert result["gate"]["decision"] == "FAIL"
    assert result["metrics"]["best_case_overall_precision"] < 0.90
    assert result["metrics"]["traceable_abstract_evidence_coverage"] == 1.0
