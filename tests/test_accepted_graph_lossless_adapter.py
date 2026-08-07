from __future__ import annotations

import json
from pathlib import Path

from src.database.adapters.accepted_graph import adapt_accepted_graph_losslessly


ROOT = Path(__file__).resolve().parents[1]
GRAPH_ROOT = ROOT / "data/staging/extraction/g1_fulltext_rag"


def test_gp_adapter_accounts_for_every_entity_claim_and_experiment() -> None:
    graph_path = GRAPH_ROOT / "GP-008/accepted_graph.json"
    source = json.loads(graph_path.read_text(encoding="utf-8"))

    result = adapt_accepted_graph_losslessly(graph_path)

    assert result.coverage.source_entities == len(source["entities"])
    assert result.coverage.source_claims == len(source["claims"])
    assert result.coverage.source_experiments == len(source["experiments"])
    assert result.coverage.silent_omissions == 0
    assert len(result.source_facts) == (
        len(source["entities"]) + len(source["claims"]) + len(source["experiments"])
    )


def test_unknown_predicate_is_preserved_not_dropped(tmp_path: Path) -> None:
    source = json.loads(
        (GRAPH_ROOT / "GP-008/accepted_graph.json").read_text(encoding="utf-8")
    )
    source["claims"] = [
        {
            "claim_id": "NOVEL-1",
            "subject_entity_id": "F1",
            "predicate": "novel_relation",
            "object_entity_id": "F2",
            "evidence": [{"clause_id": "C1", "quote": "A novel relation."}],
        }
    ]
    source["experiments"] = []
    graph_path = tmp_path / "accepted_graph.json"
    graph_path.write_text(json.dumps(source), encoding="utf-8")

    result = adapt_accepted_graph_losslessly(graph_path)
    fact = next(
        row for row in result.source_facts if row.source_record_key == "NOVEL-1"
    )

    assert fact.field_name == "novel_relation"
    assert fact.import_disposition == "quarantined"


def test_gold_composition_is_combined_with_graph_formulation() -> None:
    gp2 = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-002/accepted_graph.json"
    ).bundle
    gp8 = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-008/accepted_graph.json"
    ).bundle

    assert gp2.formulations[0].composition_raw == (
        "SM-102:DSPC:cholesterol:DMG-PEG2000 = 50:10:38.5:1.5"
    )
    gp8_formulation = next(
        row for row in gp8.formulations if row.formulation_name == "αCD163/LNP-FAPCAR"
    )
    assert gp8_formulation.chemical_formulation_total == (
        "ionizable lipid-DSPC-cholesterol-PEG-lipid"
    )
    assert gp8_formulation.lnp_molar_ratio == "45:30:23.5:1.5"
    gp8_components = [
        row for row in gp8.components if row.formulation_id == gp8_formulation.record_id
    ]
    assert [
        row.molar_percentage
        for row in gp8_components
        if row.component_role in {
            "ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid"
        }
    ] == [45.0, 30.0, 23.5, 1.5]
    assert any(row.component_name_reported == "antibody:LNP 1:20" for row in gp8_components)
    assert len(gp2.arms) == 6
    assert any(
        (row.dose, row.dose_unit, row.timepoint, row.timepoint_unit)
        == (10.0, "ug_mRNA_per_mouse", 24.0, "hour")
        for row in gp2.arms
    )
    assert {row.record_id for row in gp2.arms} >= {
        "GP-002:ARM:GP-002-E01:F1", "GP-002:ARM:GP-002-E06:F1"
    }
    healthy_arm = next(
        row for row in gp2.arms if row.record_id == "GP-002:ARM:GP-002-E01:F1"
    )
    assert healthy_arm.verification_status == "manually_verified"
    assert healthy_arm.cell_type == "hepatocyte"
    assert healthy_arm.payload_encoded_product == "enhanced green fluorescent protein"
    assert len(gp2.outcomes) == 7
    assert any(
        row.endpoint_name == "hepatocyte_eGFP_expression"
        for row in gp2.outcomes
    )


def test_gp004_projects_patent_ratio_as_explicit_inference() -> None:
    bundle = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-004/accepted_graph.json"
    ).bundle

    assert len(bundle.formulations) == 1
    formulation = bundle.formulations[0]
    assert formulation.lnp_molar_ratio == (
        "50:10:38.5:1.5 [inferred from US10,221,127]"
    )
    assert formulation.composition_basis == "molar_ratio"
    assert "not directly reported by GP-004" in (
        formulation.formulation_notes or ""
    )

    patent_artifact = next(
        row for row in bundle.artifacts
        if row.artifact_id == "GP-004:US10221127B2"
    )
    assert patent_artifact.path == (
        "https://patents.google.com/patent/US10221127B2/en"
    )
    ratio_evidence = next(
        row for row in bundle.evidence
        if row.record_id == "GP-004:EV:US10221127B2:RATIO"
    )
    assert "50% Cationic lipid" in (ratio_evidence.evidence_text or "")
    ratio_link = next(
        row for row in bundle.field_evidence_links
        if row.entity_type == "formulation"
        and row.entity_id == formulation.record_id
        and row.field_name == "lnp_molar_ratio"
    )
    assert ratio_link.evidence_ids == (
        "GP-004:EV:PATENT-REFERENCE",
        "GP-004:EV:US10221127B2:RATIO",
    )
    assert ratio_link.verification_status == "automatically_validated"


def test_gold_arm_enrichment_merges_with_the_same_scientific_arm() -> None:
    gp5 = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-005/accepted_graph.json"
    ).bundle
    lnp1 = [
        row for row in gp5.arms
        if row.formulation_id.endswith(":FORM:ENT-LNP1")
    ]

    assert len(gp5.arms) == 8
    assert len(lnp1) == 1
    assert lnp1[0].record_id == "GP-005:ARM:GP-005-E01:ENT-LNP1"
    assert lnp1[0].cell_type == "kupffer_cell"
    assert lnp1[0].payload_name == "Egfp mRNA"
    assert lnp1[0].payload_encoded_product == "EGFP"
    assert sum(row.arm_id == lnp1[0].record_id for row in gp5.outcomes) == 2


def test_gp005_recovers_table_formulations_and_shared_protocol() -> None:
    bundle = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-005/accepted_graph.json"
    ).bundle
    formulations = {row.formulation_name: row for row in bundle.formulations}

    for name in ("LNP3", "LNP4", "LNP5", "LNP6", "LNP7", "LNP16", "LNP17"):
        assert formulations[name].lnp_molar_ratio == "50:10:38.5:1.5"
        assert formulations[name].chemical_formulation_total.endswith(
            "DSPC-cholesterol-DMG-PEG2000"
        )
    assert formulations["LNP3"].chemical_formulation_total.startswith("MC3-")
    assert formulations["LNP4"].chemical_formulation_total.startswith("SM-102-")
    assert formulations["LNP5"].chemical_formulation_total.startswith("SM-102-")
    assert formulations["LNP6"].chemical_formulation_total.startswith("MC3-")
    assert formulations["LNP7"].chemical_formulation_total.startswith("SM-102-")
    assert "LNP3‐LNP7" not in formulations

    arms = {
        next(form.formulation_name for form in bundle.formulations
             if form.record_id == arm.formulation_id): arm
        for arm in bundle.arms
    }
    assert arms["LNP3"].payload_name == "5moU-modified EGFP mRNA"
    assert arms["LNP5"].payload_name == "unmodified EGFP mRNA"
    assert arms["LNP6"].payload_name == "m1Ψ-modified EGFP mRNA"
    for name in ("LNP16", "LNP17"):
        assert arms[name].target_or_recipient_organ == "liver"
        assert arms[name].species == "Mus musculus"
        assert arms[name].dose == 3.0
        assert arms[name].route == "intravenous injection"
        assert arms[name].timepoint == 16.0


def test_payload_labels_populate_encoded_product_and_molecular_target() -> None:
    gp5 = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-005/accepted_graph.json"
    ).bundle
    by_formulation = {
        row.formulation_id.rsplit(":", 1)[-1]: row for row in gp5.arms
    }

    assert by_formulation["ENT-LNP16"].payload_encoded_product == "EGFP"
    assert by_formulation["ENT-LNP16"].payload_molecular_target is None
    assert by_formulation["ENT-LNP17"].payload_encoded_product == "EGFP"
    assert by_formulation["ENT-LNP17"].payload_molecular_target == "TLR4"


def test_gp007_keeps_payload_out_of_chemical_formulation() -> None:
    bundle = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-007/accepted_graph.json"
    ).bundle

    formulation = bundle.formulations[0]
    assert formulation.chemical_formulation_total == (
        "cholesterol-DSPE-PEG-FITC-labeled hyaluronic acid"
    )
    assert formulation.lnp_molar_ratio is None
    assert not any(
        component.component_name_reported.casefold() == "simicu1"
        for component in bundle.components
    )
    assert not any(
        component.component_role == "ionizable_lipid"
        for component in bundle.components
    )


def test_gp008_projects_shared_targeted_lnp_chemistry_to_payload_variants() -> None:
    bundle = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-008/accepted_graph.json"
    ).bundle
    targeted = {
        row.formulation_name: row
        for row in bundle.formulations
        if row.formulation_name in {
            "αCD163/LNP-FAPCAR", "αCD163/LNP-Luc", "αCD163/LNP-ZsGreen"
        }
    }

    assert set(targeted) == {
        "αCD163/LNP-FAPCAR", "αCD163/LNP-Luc", "αCD163/LNP-ZsGreen"
    }
    assert {row.chemical_formulation_total for row in targeted.values()} == {
        "ionizable lipid-DSPC-cholesterol-PEG-lipid"
    }
    assert {row.lnp_molar_ratio for row in targeted.values()} == {
        "45:30:23.5:1.5"
    }
    for formulation in targeted.values():
        roles = {
            component.component_role
            for component in bundle.components
            if component.formulation_id == formulation.record_id
        }
        assert {"ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid"} <= roles

    luc_arm = next(
        arm for arm in bundle.arms
        if arm.formulation_id == targeted["αCD163/LNP-Luc"].record_id
    )
    luc_outcomes = [row for row in bundle.outcomes if row.arm_id == luc_arm.record_id]
    assert len(luc_outcomes) == 1
    assert "peak fluorescence intensity at 8 h" in (
        luc_outcomes[0].qualitative_outcome or ""
    ).casefold()


def test_biological_model_subject_is_not_lost_when_species_is_linked() -> None:
    gp2 = adapt_accepted_graph_losslessly(
        GRAPH_ROOT / "GP-002/accepted_graph.json"
    ).bundle

    assert next(
        row for row in gp2.arms if "GP-002-E05" in row.record_id
    ).disease_model == "orthotopic HuH-7 hepatocellular carcinoma xenograft model"
    assert next(
        row for row in gp2.arms if "GP-002-E06" in row.record_id
    ).disease_model == (
        "A549-mCherry xenograft group; HCT116-mCherry xenograft group"
    )
