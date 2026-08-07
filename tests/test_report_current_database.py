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
        report = report_current_database(connection, manifest)

    assert REQUIRED_COUNTS <= report["counts"].keys()
    assert report["definitions"]["named_formulations"] != report["definitions"]["unique_chemical_formulations"]
    assert report["checks"]["silent_fact_omissions"] == 0
    assert report["checks"]["silent_evidence_omissions"] == 0
