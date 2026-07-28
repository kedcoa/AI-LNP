from src.extraction.evaluate_compact_gold import (
    _exact_gold_outcomes,
    _field_value,
    _number,
)


def test_exact_gold_outcomes_excludes_approximate_and_threshold_values():
    rows = [
        {
            "gold_outcome_id": "GO-1",
            "endpoint_name": "exact",
            "outcome_value": "1.01",
            "outcome_unit": "percent",
            "value_status": "reported",
            "evidence_id": "E-1",
        },
        {
            "gold_outcome_id": "GO-2",
            "endpoint_name": "approximate",
            "outcome_value": "17",
            "outcome_unit": "fold",
            "value_status": "reported_approximate",
            "evidence_id": "E-2",
        },
        {
            "gold_outcome_id": "GO-3",
            "endpoint_name": "threshold",
            "outcome_value": "80",
            "outcome_unit": "percent_greater_than",
            "value_status": "reported_threshold",
            "evidence_id": "E-3",
        },
    ]
    assert [row["gold_outcome_id"] for row in _exact_gold_outcomes(rows)] == ["GO-1"]


def test_number_and_field_value_are_conservative():
    assert _number("16.50") == 16.5
    assert _number("") is None
    assert _number("over 80") is None
    assert _field_value({"value": "LSEC", "status": "reported"}) == "LSEC"
