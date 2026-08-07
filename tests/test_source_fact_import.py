from __future__ import annotations

import sqlite3

from src.database.source_fact_import import (
    FactProjectionRecord,
    SourceArtifactRecord,
    SourceFactRecord,
    import_source_facts,
)
from src.init_db import initialize_database


def _connection(tmp_path) -> sqlite3.Connection:
    path = tmp_path / "facts.db"
    initialize_database(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        INSERT INTO paper (
            source_paper_id, title, source_type, retrieval_date,
            screening_status, import_status
        ) VALUES ('P1', 'Fixture', 'fixture', '2026-08-07', 'include', 'ready')
        """
    )
    connection.commit()
    return connection


def _artifact() -> SourceArtifactRecord:
    return SourceArtifactRecord(
        paper_id="P1",
        logical_path="result.json",
        sha256="a" * 64,
        role="primary_extraction",
        schema_family="fixture",
        validation_status="accepted",
        contributes_facts=True,
        contributes_evidence=True,
    )


def test_every_source_fact_gets_one_visible_disposition(tmp_path) -> None:
    connection = _connection(tmp_path)
    paper_id = connection.execute(
        "SELECT paper_id FROM paper WHERE source_paper_id = 'P1'"
    ).fetchone()[0]
    facts = [
        SourceFactRecord(
            json_path="$.title",
            source_record_key="paper",
            record_kind="field",
            subject_type="paper",
            subject_key="P1",
            field_name="title",
            raw_value="Fixture",
            fact_identity_sha256="1" * 64,
            import_disposition="projected",
            projections=(
                FactProjectionRecord(
                    "paper", paper_id, "title", "1" * 64
                ),
            ),
        ),
        SourceFactRecord(
            "$.missing", "missing", "field", "paper", "P1", "journal",
            None, "2" * 64, "unresolved", "not reported",
        ),
        SourceFactRecord(
            "$.unsafe", "unsafe", "field", "paper", "P1", "authors",
            "unknown", "3" * 64, "quarantined", "source linkage unclear",
        ),
        SourceFactRecord(
            "$.invalid", "invalid", "field", "paper", "P1", "pmid",
            "not-a-pmid", "4" * 64, "rejected", "invalid value",
        ),
    ]

    result = import_source_facts(connection, _artifact(), facts)
    second = import_source_facts(connection, _artifact(), facts)

    assert result.source_count == 4
    assert result.accounted_count == 4
    assert result.inserted == 4
    assert second.unchanged == 4
    assert connection.execute("SELECT count(*) FROM source_fact").fetchone() == (4,)


def test_import_rolls_back_one_artifact_on_invalid_projection(tmp_path) -> None:
    connection = _connection(tmp_path)
    fact = SourceFactRecord(
        "$.title", "paper", "field", "paper", "P1", "title", "Fixture",
        "1" * 64, "projected", None,
        (FactProjectionRecord("paper", 999, "title", "1" * 64),),
    )

    try:
        import_source_facts(connection, _artifact(), [fact])
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("invalid cross-paper projection should fail")

    assert connection.execute("SELECT count(*) FROM source_artifact").fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM source_fact").fetchone() == (0,)
