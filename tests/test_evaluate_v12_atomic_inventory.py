from src.extraction.evaluate_v12_atomic_inventory import _allowed_predicates


def test_elimination_gold_cannot_match_colocalization():
    allowed = _allowed_predicates(
        {
            "endpoint_name": "activated_HSC_elimination",
            "qualitative_outcome": (
                "FAPCAR macrophages recognized, phagocytosed, and "
                "eliminated activated HSC models."
            ),
        }
    )
    assert "eliminated" in allowed
    assert "colocalized_with" not in allowed


def test_colocalized_expression_can_match_relationship_or_expression():
    allowed = _allowed_predicates(
        {
            "endpoint_name": "GFP_expression_in_LYVE1_positive_LSECs",
            "qualitative_outcome": (
                "GFP signal colocalized with the LSEC marker LYVE-1."
            ),
        }
    )
    assert {"colocalized_with", "expressed"} <= allowed
