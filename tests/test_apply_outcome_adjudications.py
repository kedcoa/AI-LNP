from copy import deepcopy

from src.extraction.apply_outcome_adjudications import (
    adjudicate_gp004,
    adjudicate_gp006,
)


def test_gp004_merges_candidate_into_o2():
    result = {
        "outcomes": [
            {
                "outcome_id": "O2",
                "qualitative_outcome": {
                    "value": "Original",
                    "status": "reported",
                    "evidence_ids": ["E1"],
                    "missing_reason": None,
                },
            }
        ]
    }
    decisions = adjudicate_gp004(result)
    assert len(result["outcomes"]) == 1
    assert "GP-004-E-fc1b2e9e166859e2" in result["outcomes"][0][
        "qualitative_outcome"
    ]["evidence_ids"]
    assert decisions[0]["target_outcome_ids"] == ["O2"]


def test_gp006_adds_four_outcomes_and_combines_duplicate_evidence():
    result = {"outcomes": [{"outcome_id": "O1"}]}
    before = deepcopy(result)
    decisions = adjudicate_gp006(result)
    assert before["outcomes"][0] == result["outcomes"][0]
    assert [row["outcome_id"] for row in result["outcomes"][1:]] == [
        "O4",
        "O5",
        "O6",
        "O7",
    ]
    o6 = result["outcomes"][-2]
    assert o6["outcome_value"]["value"] == 2.6
    assert len(o6["outcome_value"]["evidence_ids"]) == 2
    o7 = result["outcomes"][-1]
    assert o7["outcome_value"]["value"] == 3.3
    assert "GP-006-E-8f4df2feafb0205d" in o7["endpoint"]["evidence_ids"]
    assert len(decisions) == 5
