from src.extraction.build_g1_review import literal_in_source


def test_literal_source_check_is_case_and_punctuation_insensitive():
    assert literal_in_source("eGFP mRNA", "Delivery of eGFP-mRNA was observed.")


def test_literal_source_check_rejects_unstated_value():
    assert not literal_in_source("50:10:38.5:1.5", "An optimized LNP was used.")
