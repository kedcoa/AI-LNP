from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.database.report_current_database import report_current_database
from src.database.run_current_corpus_import import rebuild_database


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_COUNTS = {
    "papers", "named_formulations", "unique_chemical_formulations",
    "complete_formulations", "incomplete_formulations", "components",
    "source_fact_occurrences", "canonical_facts", "experimental_arms",
    "outcomes", "source_evidence_occurrences", "evidence_records",
    "nearest_neighbor_ready_arms", "comet_ready_arms",
    "unresolved_review_items",
}


def test_final_report_keeps_scientific_counts_separate(tmp_path: Path) -> None:
    database = tmp_path / "report.db"
    rebuild_database(
        database,
        ROOT / "config/database/current_corpus_v1.json",
        ROOT / "data/staging/database/day2_bundles",
        corpus_root=ROOT,
    )
    manifest = json.loads((ROOT / "config/database/current_corpus_v1.json").read_text())
    with sqlite3.connect(database) as connection:
        report = report_current_database(
            connection,
            manifest,
            manifest_path=ROOT / "config/database/current_corpus_v1.json",
            rerun_history={"provider_calls": 0, "paper_ids": []},
            promotion_record={"old_sha256": "old", "new_sha256": "new"},
        )

    assert REQUIRED_COUNTS <= report["counts"].keys()
    assert report["definitions"]["named_formulations"] != report["definitions"]["unique_chemical_formulations"]
    assert report["checks"]["silent_fact_omissions"] == 0
    assert report["checks"]["silent_evidence_omissions"] == 0
    assert report["checks"]["source_artifact_accounting_matches"] is True
    assert report["checks"]["forbidden_general_app_human_tags"] == 0
    assert report["checks"]["new_paid_rerun_calls"] == 0
    assert report["database"]["path"] == str(database.resolve())
    assert len(report["database"]["sha256"]) == 64
    assert report["database"]["schema_versions"][-1] == 6
    assert len(report["manifest"]["sha256"]) == 64
    assert report["eligibility"]["rules_version"]
    assert report["rerun_history"] == {"provider_calls": 0, "paper_ids": []}
    assert report["promotion"] == {"old_sha256": "old", "new_sha256": "new"}
    assert sum(report["verification_status_counts"].values()) == report["counts"]["experimental_arms"]
    assert all(
        {"verification_status_counts", "nearest_neighbor_ready_arms", "comet_ready_arms", "eligibility_blocking_reasons"}
        <= row.keys()
        for row in report["per_paper"]
    )
    assert "missing_or_unhashed_manifest_artifacts" in report["unresolved_blockers"]
