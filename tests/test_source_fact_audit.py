from __future__ import annotations

import sqlite3

import pytest

from src.database.source_fact_audit import audit_source_fact_coverage
from src.database.source_fact_import import (
    FactProjectionRecord,
    SourceArtifactRecord,
    SourceFactRecord,
    import_source_facts,
)
from src.init_db import initialize_database


def _seed(tmp_path) -> tuple[sqlite3.Connection, int]:
    path = tmp_path / "audit.db"
    initialize_database(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    paper_id = connection.execute(
        """
        INSERT INTO paper (
            source_paper_id, title, source_type, retrieval_date,
            screening_status, import_status
        ) VALUES ('P1', 'Fixture', 'fixture', '2026-08-07', 'include', 'ready')
        """
    ).lastrowid
    artifact = SourceArtifactRecord(
        "P1", "result.json", "a" * 64, "primary_extraction", "fixture",
        "accepted", True, True,
    )
    result = import_source_facts(
        connection,
        artifact,
        [
            SourceFactRecord(
                "$.title", "paper", "field", "paper", "P1", "title",
                "Fixture", "1" * 64, "projected", None,
                (FactProjectionRecord("paper", paper_id, "title", "1" * 64),),
            ),
            SourceFactRecord(
                "$.missing", "missing", "field", "paper", "P1", "journal",
                None, "2" * 64, "unresolved", "not reported",
            ),
        ],
    )
    return connection, result.artifact_id


def test_audit_proves_exact_source_fact_accounting(tmp_path) -> None:
    connection, artifact_id = _seed(tmp_path)

    coverage = audit_source_fact_coverage(connection, artifact_id)

    assert coverage.source_count == 2
    assert coverage.projected_count == 1
    assert coverage.unresolved_count == 1
    assert coverage.accounted_count == 2
    assert coverage.silent_omissions == ()


def test_audit_fails_silent_projection_omission(tmp_path) -> None:
    connection, artifact_id = _seed(tmp_path)
    fact_id = connection.execute(
        "SELECT source_fact_id FROM source_fact WHERE import_disposition = 'projected'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER trg_fact_projection_active_delete_guard")
    connection.execute(
        "DELETE FROM fact_projection WHERE source_fact_id = ?", (fact_id,)
    )

    with pytest.raises(ValueError, match="silent source-fact omission"):
        audit_source_fact_coverage(connection, artifact_id)
