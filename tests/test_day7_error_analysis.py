from src.rag.analyze_g1_errors import ERROR_AUDIT, RECOVERED, VALID_CATEGORIES


def test_every_missing_outcome_has_one_valid_primary_category():
    expected_missing = {
        "GO-001", "GO-002", "GO-003", "GO-004", "GO-006",
        "GO-011", "GO-013", "GO-017", "GO-018",
    }
    assert set(ERROR_AUDIT) == expected_missing
    assert set(ERROR_AUDIT).isdisjoint(RECOVERED)
    assert all(category in VALID_CATEGORIES for category, _ in ERROR_AUDIT.values())
