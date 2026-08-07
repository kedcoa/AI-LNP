from __future__ import annotations

from src.database.scientific_identity import (
    CompositionPart,
    composition_fingerprint,
    evidence_identity,
    fact_identity,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def test_fact_identity_deduplicates_formatting_not_context() -> None:
    first = fact_identity("P1", "arm", "A1", "dose", "0.30 mg/kg")
    same = fact_identity("P1", "arm", "A1", "dose", "0.3 mg/kg")
    other_arm = fact_identity("P1", "arm", "A2", "dose", "0.3 mg/kg")

    assert first == same
    assert first != other_arm


def test_evidence_identity_preserves_distinct_locations_and_artifacts() -> None:
    first = evidence_identity(
        "P1", HASH_A, {"page": 4}, "ratio 50:10:38.5:1.5", None
    )
    other_page = evidence_identity(
        "P1", HASH_A, {"page": 8}, "ratio 50:10:38.5:1.5", None
    )
    other_artifact = evidence_identity(
        "P1", HASH_B, {"page": 4}, "ratio 50:10:38.5:1.5", None
    )

    assert first != other_page
    assert first != other_artifact


def test_composition_fingerprint_ignores_component_order() -> None:
    parts = [
        CompositionPart("ionizable_lipid", "SM-102", 50, "mol%"),
        CompositionPart("helper_lipid", "DSPC", 10, "mol%"),
        CompositionPart("cholesterol", "cholesterol", 38.5, "mol%"),
        CompositionPart("peg_lipid", "PEG-DMG", 1.5, "mol%"),
    ]

    assert composition_fingerprint(parts) == composition_fingerprint(
        reversed(parts)
    )


def test_composition_fingerprint_preserves_scientific_differences() -> None:
    base = [
        CompositionPart("ionizable_lipid", "SM-102", 45, "mol%"),
        CompositionPart("helper_lipid", "DSPC", 30, "mol%"),
    ]
    changed = [
        CompositionPart("ionizable_lipid", "SM-102", 50, "mol%"),
        CompositionPart("helper_lipid", "DSPC", 30, "mol%"),
    ]

    assert composition_fingerprint(base) != composition_fingerprint(changed)


def test_composition_fingerprint_requires_component_identity() -> None:
    assert composition_fingerprint(
        [CompositionPart("ionizable_lipid", None, 45, "mol%")]
    ) is None


def test_surface_ligands_participate_in_composition_identity() -> None:
    core = [CompositionPart("ionizable_lipid", "Lipid-A", 45, "mol%")]
    targeted = [
        *core,
        CompositionPart("targeting_ligand", "anti-CD163 antibody", None, None),
    ]

    assert composition_fingerprint(core) != composition_fingerprint(targeted)


def test_composition_fingerprint_deduplicates_reported_mc3_aliases() -> None:
    compact = [
        CompositionPart("ionizable_lipid", "MC3", 50, "molar-ratio parts"),
        CompositionPart("helper_lipid", "DSPC", 10, "molar-ratio parts"),
        CompositionPart("cholesterol", "cholesterol", 38.5, "molar-ratio parts"),
        CompositionPart("peg_lipid", "C14 PEG 2000", 1.5, "molar-ratio parts"),
    ]
    expanded = [
        CompositionPart("ionizable_lipid", "DLin-MC3-DMA (MC3)", 50, "mol%"),
        CompositionPart("helper_lipid", "DSPC", 10, "mol%"),
        CompositionPart("cholesterol", "cholesterol", 38.5, "mol%"),
        CompositionPart("peg_lipid", "C14-PEG2000", 1.5, "mol%"),
    ]

    assert composition_fingerprint(compact) == composition_fingerprint(expanded)
