from src.extraction.run_abstract_first import gold_inputs


def test_gold_inputs_cover_frozen_set_without_full_text():
    inputs = gold_inputs()
    assert len(inputs) == 9
    assert all(set(item) == {"paper_id", "screening_cell_type", "screening_decision", "eligible_records_expected", "title", "abstract"} for item in inputs)
    assert sum(not item["eligible_records_expected"] for item in inputs) == 3
