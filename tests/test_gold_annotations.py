from src.screening.validate_gold_annotations import validate


def test_day4_gold_annotations_pass_acceptance_checks():
    assert validate() == []
