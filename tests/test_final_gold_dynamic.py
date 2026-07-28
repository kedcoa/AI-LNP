from src.extraction.evaluate_final_gold_dynamic import _best_one_to_one_matches


def test_paper_level_assignment_beats_greedy_record_stealing():
    gold = [{"gold_outcome_id": "G1"}, {"gold_outcome_id": "G2"}]
    outcomes = [{"outcome_id": "O1"}, {"outcome_id": "O2"}]
    scored = {
        (0, 0): (0.90, {"label": "broad"}),
        (0, 1): (0.80, {"label": "specific-g1"}),
        (1, 0): (0.85, {"label": "specific-g2"}),
        (1, 1): (0.00, {"label": "wrong"}),
    }
    matches = _best_one_to_one_matches(gold, outcomes, scored)
    assert matches["G1"]["outcome_id"] == "O2"
    assert matches["G2"]["outcome_id"] == "O1"
