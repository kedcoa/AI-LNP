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
