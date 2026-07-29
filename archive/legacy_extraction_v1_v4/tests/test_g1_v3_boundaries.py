from src.extraction.run_g1_v3_boundaries import split_sentences


def test_sentence_ids_are_stable_and_ordered():
    rows = split_sentences("First experiment. Second experiment! Final result?")
    assert [row.sentence_id for row in rows] == ["S01", "S02", "S03"]
    assert rows[1].text == "Second experiment!"
