import pytest

from src.extraction.application_normalization import canonicalize_fact


def test_ratio_format_is_canonical_but_raw_is_preserved() -> None:
    """A ratio-space mutation must not alter its source value or evidence."""
    fact = canonicalize_fact("component_ratio", "50 : 38.5 : 1.5 : 10", ["E-1"])

    assert fact.raw_value == "50 : 38.5 : 1.5 : 10"
    assert fact.canonical_value == "50:38.5:1.5:10"
    assert fact.evidence_ids == ("E-1",)


def test_unknown_scientific_text_is_not_fuzzy_rewritten() -> None:
    """Unregistered scientific names must only receive safe text normalization."""
    fact = canonicalize_fact("formulation", "Novel LNP-X", ["E-2"])

    assert fact.canonical_value == "novel lnp-x"
    assert fact.normalization_rule == "casefold_whitespace"


@pytest.mark.parametrize(
    ("field_name", "raw_value", "expected"),
    [
        ("assay", "ddPCR", "droplet digital pcr"),
        ("assay", "digital   droplet PCR", "droplet digital pcr"),
        ("assay", "qPCR", "quantitative pcr"),
        ("outcome_unit", "percent", "%"),
        ("amount_unit", "mol percent", "mol%"),
        ("dose_unit", "mg per kg", "mg/kg"),
    ],
)
def test_reviewed_aliases_are_normalized_only_for_their_field(
    field_name: str,
    raw_value: str,
    expected: str,
) -> None:
    """Removing an exact reviewed alias must prevent its canonical match."""
    fact = canonicalize_fact(field_name, raw_value, ["E-3", "E-3", "E-4"])

    assert fact.canonical_value == expected
    assert fact.normalization_rule == "closed_alias"
    assert fact.evidence_ids == ("E-3", "E-4")


def test_alias_text_inside_a_longer_value_is_not_replaced() -> None:
    """Substring replacement would conflate a specific assay description."""
    fact = canonicalize_fact("assay", "ddPCR calibration control", ["E-5"])

    assert fact.canonical_value == "ddpcr calibration control"
    assert fact.normalization_rule == "casefold_whitespace"
