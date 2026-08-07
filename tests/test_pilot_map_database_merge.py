from __future__ import annotations

import json
from pathlib import Path

from src.database.adapters.pilot_map_results import (
    build_pilot_map_lossless_result,
    completed_pilot_map_response,
)
from src.database.import_contracts import ImportBundle
from src.extraction.prepare_application_pilot import _map_artifact_inputs


ROOT = Path(__file__).resolve().parents[1]
CONSOLIDATED = ROOT / "reports/extraction/application_pilot_final.json"


def _completed_response(paper_id: str) -> Path:
    response = completed_pilot_map_response(
        ROOT / "data/staging/extraction/application_pilot/map_gate/manifest.json",
        paper_id,
    )
    assert response is not None
    assert response.is_relative_to(ROOT)
    return response


def _base_bundle(paper_id: str) -> ImportBundle:
    path = ROOT / f"data/staging/database/day2_bundles/pilot/{paper_id}.json"
    return ImportBundle.from_dict(json.loads(path.read_text(encoding="utf-8")))


def test_completed_pilot_map_promotes_only_grounded_formulations_and_arms() -> None:
    result = build_pilot_map_lossless_result(
        response_path=(response := _completed_response("PILOT-001")),
        base_bundle=_base_bundle("PILOT-001"),
        consolidated_path=CONSOLIDATED,
    )
    assert _map_artifact_inputs(response)[7] == (
        ROOT / "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
    ).resolve()

    bundle = result.bundle
    assert len(bundle.formulations) == 2
    assert len(bundle.components) == 10
    assert len(bundle.arms) == 5
    assert len(bundle.outcomes) == 11
    assert any(
        outcome.endpoint_name.casefold() == "gfp silencing/knockdown efficiency"
        and ">80% GFP silencing" in (outcome.qualitative_outcome or "")
        for outcome in bundle.outcomes
    )
    assert not any(
        review.reason_code == "outcome_link_unclear"
        for review in bundle.reviews
    )
    in_vivo = [arm for arm in bundle.arms if arm.tissue_or_organ == "liver"]
    assert in_vivo
    assert all(arm.target_or_recipient_organ == "liver" for arm in in_vivo)
    assert all(arm.observed_transfected_cell for arm in bundle.arms)
    completed_artifact = next(
        artifact
        for artifact in bundle.artifacts
        if artifact.pipeline_name == "application_pilot_completed_map"
    )
    assert completed_artifact.path == (
        "data/staging/extraction/application_pilot/map_gate/run/REQ-1/response.json"
    )
    assert bundle.formulations[0].lnp_molar_ratio == "50:10:38.5:1.5"
    assert bundle.formulations[0].chemical_formulation_total == (
        "AA-T3A-C12 anisamide-tethered ionizable lipidoid-DSPC-"
        "cholesterol-C14-PEG2000"
    )
    assert all(not arm.nearest_neighbor_eligible for arm in bundle.arms)
    assert all(not arm.comet_eligible for arm in bundle.arms)
    assert all(
        arm.verification_status == "automatically_validated"
        for arm in bundle.arms
    )
    assert all(
        review.reason_code != "needs_human_verification"
        for review in bundle.reviews
    )
    assert result.coverage.source_experiments == 5
    assert result.coverage.silent_omissions == 0


def test_all_three_completed_maps_are_schema_and_inventory_bound() -> None:
    expected = {
        "PILOT-001": (2, 5, 11),
        "PILOT-002": (5, 5, 18),
        "PILOT-003": (1, 5, 14),
    }
    for paper_id, (formulation_count, arm_count, outcome_count) in expected.items():
        result = build_pilot_map_lossless_result(
            response_path=_completed_response(paper_id),
            base_bundle=_base_bundle(paper_id),
            consolidated_path=CONSOLIDATED,
        )
        assert len(result.bundle.formulations) == formulation_count
        assert len(result.bundle.arms) == arm_count
        assert len(result.bundle.outcomes) == outcome_count
        assert result.coverage.silent_omissions == 0
        assert result.coverage.source_fields == result.source_fact_count
