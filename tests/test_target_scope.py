from __future__ import annotations

from src.database.target_scope import classify_target_statement


def test_observed_hepatocyte_transfection_is_not_intentional_targeting() -> None:
    """Catches promotion of an observed cell into an intended-target field."""

    candidate = classify_target_statement(
        "Transfection of hepatocytes was widespread in most livers."
    )

    assert candidate.intended_target_cell is None
    assert candidate.target_or_recipient_organ == "liver"
    assert candidate.observed_transfected_cell == "hepatocyte"
    assert candidate.ambiguous is False


def test_explicit_hepatocyte_targeting_is_kept_separate_from_organ() -> None:
    """Catches loss of explicit targeting language during classification."""

    candidate = classify_target_statement(
        "The ligand-targeted LNP was designed for delivery to hepatocytes."
    )

    assert candidate.intended_target_cell == "hepatocyte"
    assert candidate.observed_transfected_cell is None


def test_biodistribution_without_a_named_destination_abstains() -> None:
    """Catches fabrication of a destination from generic biodistribution text."""

    candidate = classify_target_statement(
        "Biodistribution was measured twenty-four hours after injection."
    )

    assert candidate.intended_target_cell is None
    assert candidate.target_or_recipient_organ is None
    assert candidate.observed_transfected_cell is None
    assert candidate.ambiguous is True


def test_prior_hydrodynamic_comparison_is_not_assigned_to_current_lnp_arm() -> None:
    candidate = classify_target_statement(
        "It was previously demonstrated that following hydrody- FVIII was "
        "measured and namic injection of plasmid DNA, transfection occurred "
        "predominantly in hepatocytes."
    )

    assert candidate.observed_transfected_cell is None
    assert candidate.intended_target_cell is None
    assert candidate.ambiguous is True


def test_colocalization_records_observed_cell_and_liver_destination() -> None:
    candidate = classify_target_statement(
        "Liver immunostaining showed colocalization of GFP and the LSEC marker LYVE-1."
    )

    assert candidate.target_or_recipient_organ == "liver"
    assert candidate.observed_transfected_cell == "lsec"
