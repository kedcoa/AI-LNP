import json
from pathlib import Path

import pytest

from src.database.adapters.accepted_graph import adapt_accepted_graph, generate_gp_bundles
from src.database.import_contracts import ImportBundle


ROOT = Path(__file__).parents[1]
GRAPH_ROOT = ROOT / "data/staging/extraction/g1_fulltext_rag"


def _write_graph(path: Path, *, predicate: str = "has_species") -> Path:
    graph = {
        "contract_version": "4.0.0",
        "paper_id": "GP-TEST",
        "source_scope": "full_text",
        "original_lnp_experiments_present": True,
        "entities": [
            {"entity_id": "F", "entity_type": "lnp_formulation", "reported_name": "LNP-X", "normalized_name": "LNP-X", "normalization_status": "exact", "evidence": [{"clause_id": "C1", "quote": "LNP-X contained lipid A."}]},
            {"entity_id": "I", "entity_type": "intervention", "reported_name": "LNP-X dose", "normalized_name": None, "normalization_status": "unresolved", "evidence": [{"clause_id": "C2", "quote": "Mice received LNP-X."}]},
            {"entity_id": "S", "entity_type": "species", "reported_name": "mouse", "normalized_name": "Mus musculus", "normalization_status": "synonym", "evidence": [{"clause_id": "C2", "quote": "Mice received LNP-X."}]},
        ],
        "claims": [
            {"claim_id": "CF", "experiment_id": "E1", "subject_entity_id": "I", "predicate": "has_formulation", "object_entity_id": "F", "evidence": [{"clause_id": "C2", "quote": "Mice received LNP-X."}]},
            {"claim_id": "CS", "experiment_id": "E1", "subject_entity_id": "I", "predicate": predicate, "object_entity_id": "S", "evidence": [{"clause_id": "C2", "quote": "Mice received LNP-X."}]},
        ],
        "experiments": [{"experiment_id": "E1", "label": "mouse delivery", "claim_ids": ["CF", "CS"], "shared_claim_ids": [], "source_scope_clause_ids": ["C2"], "boundary_status": "explicit", "boundary_reason": "explicit"}],
    }
    path.write_text(json.dumps(graph), encoding="utf-8")
    return path


def test_adapter_preserves_paper_arm_species_and_evidence_provenance(tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path / "accepted_graph.json")

    bundle = adapt_accepted_graph(graph_path, title="Test paper")

    assert isinstance(bundle, ImportBundle)
    assert bundle.paper.source_paper_id == "GP-TEST"
    assert bundle.paper.title == "Test paper"
    assert len(bundle.formulations) == 1
    assert len(bundle.arms) == 1
    assert bundle.arms[0].species == "Mus musculus"
    assert bundle.arms[0].nearest_neighbor_eligible is False
    assert bundle.artifacts[0].path == str(graph_path)
    assert len(bundle.artifacts[0].sha256) == 64
    assert {row.record_id for row in bundle.evidence}
    assert any(link.field_name == "species" for link in bundle.field_evidence_links)


def test_adapter_quarantines_unknown_predicate_with_plain_review_tag(tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path / "accepted_graph.json", predicate="has_magic")

    bundle = adapt_accepted_graph(graph_path)

    assert any(review.reason_code == "needs_human_verification" for review in bundle.reviews)
    assert all(arm.completeness_status != "complete" for arm in bundle.arms)


@pytest.mark.parametrize("paper_id", ["GP-001", "GP-003", "GP-009"])
def test_adapter_rejects_screening_only_papers(paper_id: str) -> None:
    with pytest.raises(ValueError, match="screening-only"):
        adapt_accepted_graph(GRAPH_ROOT / paper_id / "accepted_graph.json")


@pytest.mark.parametrize("paper_id", ["GP-002", "GP-004", "GP-005", "GP-006", "GP-007", "GP-008"])
def test_real_supported_graph_produces_valid_noneligible_bundle(paper_id: str) -> None:
    bundle = adapt_accepted_graph(GRAPH_ROOT / paper_id / "accepted_graph.json")

    assert bundle.paper.source_paper_id == paper_id
    assert bundle.formulations
    assert bundle.arms
    assert bundle.evidence
    assert all(not arm.nearest_neighbor_eligible and not arm.comet_eligible for arm in bundle.arms)
    assert all(arm.dose is None or arm.dose_unit for arm in bundle.arms)
    graph = json.loads((GRAPH_ROOT / paper_id / "accepted_graph.json").read_text())
    imported_quotes = {evidence.evidence_text for evidence in bundle.evidence}
    source_quotes = {
        evidence["quote"]
        for claim in graph["claims"]
        for evidence in claim.get("evidence", [])
        if evidence.get("quote")
    }
    assert source_quotes <= imported_quotes
    assert ImportBundle.from_dict(bundle.to_dict()).to_dict() == bundle.to_dict()


def test_generator_writes_only_six_supported_gp_bundles(tmp_path: Path) -> None:
    paths = generate_gp_bundles(ROOT, tmp_path)

    assert {path.stem for path in paths} == {"GP-002", "GP-004", "GP-005", "GP-006", "GP-007", "GP-008"}
    assert not any((tmp_path / f"{paper_id}.json").exists() for paper_id in ("GP-001", "GP-003", "GP-009"))
    bundles = [ImportBundle.from_dict(json.loads(path.read_text())) for path in paths]
    assert all(bundle.artifacts[0].path.startswith("data/staging/extraction/") for bundle in bundles)


def test_gp005_preserves_explicit_formulation_arms_without_fallback() -> None:
    bundle = adapt_accepted_graph(GRAPH_ROOT / "GP-005" / "accepted_graph.json")
    formulation_by_id = {row.record_id: row.formulation_name for row in bundle.formulations}

    assert {formulation_by_id[arm.formulation_id] for arm in bundle.arms} == {
        "Egfp mRNA‐LNP (LNP1)", "LNP16", "LNP17", "LNP3‐LNP7"
    }
    assert not any("GP-005-E03" in arm.record_id for arm in bundle.arms)
    assert any(review.reason_code == "experiment_link_unclear" for review in bundle.reviews)


def test_gp008_creates_only_explicitly_related_formulation_arms() -> None:
    bundle = adapt_accepted_graph(GRAPH_ROOT / "GP-008" / "accepted_graph.json")
    formulation_by_id = {row.record_id: row.formulation_name for row in bundle.formulations}

    assert {formulation_by_id[arm.formulation_id] for arm in bundle.arms} == {
        "αCD163/LNP-FAPCAR", "αCD163/LNP-Luc", "αCD163/LNP-ZsGreen"
    }


def test_shared_claims_are_assigned_only_when_experiment_lists_them() -> None:
    gp002 = adapt_accepted_graph(GRAPH_ROOT / "GP-002" / "accepted_graph.json")
    assert all(arm.payload_name for arm in gp002.arms)
    gp007 = adapt_accepted_graph(GRAPH_ROOT / "GP-007" / "accepted_graph.json")
    e04 = next(arm for arm in gp007.arms if "GP-007-E04" in arm.record_id)
    graph = json.loads((GRAPH_ROOT / "GP-007" / "accepted_graph.json").read_text())
    experiment = next(row for row in graph["experiments"] if row["experiment_id"] == "GP-007-E04")
    expected = sum(
        graph_claim["predicate"] == "has_outcome_value"
        for graph_claim in graph["claims"]
        if graph_claim["claim_id"] in experiment["claim_ids"] + experiment["shared_claim_ids"]
    )
    assert len([outcome for outcome in gp007.outcomes if outcome.arm_id == e04.record_id]) == expected


def test_dimensioned_dose_keeps_microgram_unit() -> None:
    bundle = adapt_accepted_graph(GRAPH_ROOT / "GP-002" / "accepted_graph.json")
    arm = next(arm for arm in bundle.arms if arm.dose == 10)
    assert arm.dose_unit == "micrograms"


def test_unsupported_predicate_preserves_exact_evidence(tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path / "accepted_graph.json", predicate="has_magic")
    bundle = adapt_accepted_graph(graph_path)
    review = next(review for review in bundle.reviews if review.reason_code == "needs_human_verification")

    assert review.evidence_ids
    assert all(next(e for e in bundle.evidence if e.record_id == evidence_id).evidence_text for evidence_id in review.evidence_ids)
