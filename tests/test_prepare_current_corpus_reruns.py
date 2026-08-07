from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.extraction.prepare_current_corpus_reruns import prepare_current_corpus_reruns
from src.extraction.run_current_corpus_reruns import run_current_corpus_reruns
from src.database.build_rerun_queue import GapRecord, build_requests
from src.database.run_current_corpus_import import rebuild_database


ROOT = Path(__file__).resolve().parents[1]


def _gap(kind: str, *, recoverable: bool = False) -> GapRecord:
    return GapRecord(
        paper_id="TEST-001",
        experiment_id=1,
        record_id="TEST-001:ARM:1",
        field_name="outcome",
        gap_kind=kind,
        reason="test gap",
        recoverable=recoverable,
    )


def test_projection_gap_never_creates_paid_rerun() -> None:
    assert build_requests((_gap("projection_missed"),)) == ()


def test_source_not_reported_is_reported_but_not_rerun() -> None:
    assert build_requests((_gap("source_not_reported"),)) == ()


def test_only_extraction_or_recoverable_asset_gaps_create_reruns() -> None:
    requests = build_requests((
        _gap("source_asset_missing", recoverable=False),
        _gap("source_asset_missing", recoverable=True),
        _gap("extraction_missed"),
        _gap("scientific_conflict"),
    ))
    assert len(requests) == 1
    assert requests[0]["paper_id"] == "TEST-001"
    assert requests[0]["fields"] == ["outcome"]


def test_preflight_does_not_rerun_completed_exact_hashes(tmp_path: Path) -> None:
    database = tmp_path / "rerun.db"
    rebuild_database(
        database,
        ROOT / "config/database/current_corpus_v1.json",
        ROOT / "data/staging/database/day2_bundles",
        corpus_root=ROOT,
    )
    preflight = prepare_current_corpus_reruns(
        database,
        ROOT / "config/database/current_corpus_v1.json",
        ROOT / "data/staging/extraction/application_pilot/map_gate/manifest.json",
    )

    assert "GP-008:lnp_molar_ratio" not in preflight.requested_fields
    assert preflight.paper_ids == ()
    assert set(preflight.completed_existing_paper_ids) == {
        "PILOT-001", "PILOT-002", "PILOT-003"
    }
    assert preflight.provider_calls == 0
    assert len(preflight.requests) == 0
    assert preflight.human_approval_required is False
    assert Path(preflight.manifest_path) == (
        ROOT / "data/staging/extraction/application_pilot/map_gate/manifest.json"
    ).resolve()


def test_runner_refuses_unapproved_request_hashes() -> None:
    manifest = json.loads(
        (ROOT / "data/staging/extraction/application_pilot/map_gate/manifest.json").read_text()
    )
    with pytest.raises(PermissionError, match="approved request hash"):
        run_current_corpus_reruns(
            Path(manifest["manifest_path"]),
            manifest["approval_hash"],
            approved_request_hashes=set(),
        )
