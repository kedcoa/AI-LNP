from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from tests.test_evidence_browser_service import evidence_browser_database


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_export_mentor_snapshot_is_complete_consistent_and_read_only(
    evidence_browser_database: Path,
    tmp_path: Path,
) -> None:
    from src.ui.evidence_browser_service import summarize_browser_database
    from src.ui.export_mentor_snapshot import (
        export_mentor_snapshot,
        open_readonly_database,
    )

    output_dir = tmp_path / "mentor_snapshot"
    result = export_mentor_snapshot(
        evidence_browser_database,
        output_dir,
    )

    expected = {
        "lnp_evidence.db",
        "combined_experimental_arms.csv",
        "snapshot_summary.json",
        "README.md",
        "app.py",
        "src",
    }
    assert expected <= {path.name for path in output_dir.iterdir()}
    copied_database = output_dir / "lnp_evidence.db"
    assert _sha256(copied_database) == _sha256(evidence_browser_database)

    summary = json.loads(
        (output_dir / "snapshot_summary.json").read_text(encoding="utf-8")
    )
    expected_summary = summarize_browser_database(evidence_browser_database)
    assert summary["counts"] == {
        "unique_chemical_formulations": (
            expected_summary.unique_chemical_formulations
        ),
        "general_use_ready_arms": expected_summary.general_use_ready_arms,
        "nearest_neighbor_ready_arms": (
            expected_summary.nearest_neighbor_ready_arms
        ),
        "comet_ready_arms": expected_summary.comet_ready_arms,
        "experimental_arms": expected_summary.experimental_arms,
    }
    assert summary["database_sha256"] == _sha256(copied_database)
    assert summary["integrity_check"] == "ok"
    assert summary["foreign_key_violations"] == 0

    with (output_dir / "combined_experimental_arms.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        exported_rows = list(csv.DictReader(handle))
    assert len(exported_rows) == expected_summary.experimental_arms

    with open_readonly_database(copied_database) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE forbidden_write (value TEXT)")

    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix in {".md", ".json", ".csv"}
    )
    assert "file://" not in text
    assert "OPENAI_API_KEY" not in text
    assert ".env" not in text
    assert result == summary


def test_export_refuses_to_mix_with_existing_files(
    evidence_browser_database: Path,
    tmp_path: Path,
) -> None:
    from src.ui.export_mentor_snapshot import export_mentor_snapshot

    output_dir = tmp_path / "mentor_snapshot"
    output_dir.mkdir()
    (output_dir / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        export_mentor_snapshot(evidence_browser_database, output_dir)
