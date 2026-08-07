from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.extraction.prepare_current_corpus_reruns import prepare_current_corpus_reruns
from src.extraction.run_current_corpus_reruns import run_current_corpus_reruns
from src.database.run_current_corpus_import import rebuild_database


ROOT = Path(__file__).resolve().parents[1]


def test_preflight_contains_only_post_local_closure_gaps(tmp_path: Path) -> None:
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
    assert set(preflight.paper_ids) == {"PILOT-001", "PILOT-002", "PILOT-003"}
    assert preflight.provider_calls == 0
    assert len(preflight.requests) == 3


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
