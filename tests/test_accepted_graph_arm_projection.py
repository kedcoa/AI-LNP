from __future__ import annotations

from pathlib import Path

from src.database.adapters.accepted_graph import adapt_accepted_graph_losslessly


ROOT = Path(__file__).resolve().parents[1]
GRAPH_ROOT = ROOT / "data/staging/extraction/g1_fulltext_rag"


def _bundle(paper_id: str):
    return adapt_accepted_graph_losslessly(
        GRAPH_ROOT / paper_id / "accepted_graph.json"
    ).bundle


def _source_experiment_ids(paper_id: str) -> set[str]:
    prefix = f"{paper_id}:ARM:"
    return {
        arm.record_id[len(prefix) :].split(":", 1)[0]
        for arm in _bundle(paper_id).arms
        if arm.record_id.startswith(prefix)
    }


def test_gold_enrichment_retains_all_projected_graph_experiments() -> None:
    assert _source_experiment_ids("GP-002") == {
        "GP-002-E01",
        "GP-002-E02",
        "GP-002-E03",
        "GP-002-E04",
        "GP-002-E05",
        "GP-002-E06",
    }
    assert _source_experiment_ids("GP-004") == {
        "GP-004-E01",
        "GP-004-E02",
        "GP-004-E03",
    }
    assert _source_experiment_ids("GP-005") == {
        "GP-005-E01",
        "GP-005-E02",
    }
    assert _source_experiment_ids("GP-006") == {"GP-006-E01"}
    assert _source_experiment_ids("GP-007") == {"GP-007-E04"}
    assert _source_experiment_ids("GP-008") == {"GP-008-E01"}


def test_unprojected_graph_experiments_keep_named_review_reason() -> None:
    expected = {
        "GP-004": {"GP-004-E04"},
        "GP-005": {"GP-005-E03"},
        "GP-007": {"GP-007-E01", "GP-007-E02", "GP-007-E03"},
    }
    for paper_id, experiment_ids in expected.items():
        bundle = _bundle(paper_id)
        review_keys = {review.record_id for review in bundle.reviews}
        for experiment_id in experiment_ids:
            assert any(experiment_id in key for key in review_keys)


def test_gold_arms_enrich_instead_of_replacing_graph_arms() -> None:
    gp006 = _bundle("GP-006")
    gp008 = _bundle("GP-008")

    assert len(gp006.arms) == 3
    assert len({arm.record_id for arm in gp006.arms}) == 3
    assert len(gp008.arms) == 5
    assert len({arm.record_id for arm in gp008.arms}) == 5


def test_retained_source_arms_keep_their_outcomes_and_evidence() -> None:
    bundle = _bundle("GP-002")
    source_arm_ids = {
        arm.record_id for arm in bundle.arms if ":ARM:GP-002-" in arm.record_id
    }

    assert len(source_arm_ids) == 6
    assert all(outcome.arm_id in source_arm_ids for outcome in bundle.outcomes if ":OUT:" in outcome.record_id)
    assert any(evidence.arm_id in source_arm_ids for evidence in bundle.evidence)
    assert any(
        link.entity_type == "arm" and link.entity_id in source_arm_ids
        for link in bundle.field_evidence_links
    )
