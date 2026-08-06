from __future__ import annotations

import sqlite3

import pytest

from src.database.migrations import migrate_database


def _legacy_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE paper (
            paper_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL,
            retrieval_date TEXT NOT NULL,
            screening_status TEXT NOT NULL DEFAULT 'manual_review'
        );
        CREATE TABLE formulation (
            formulation_id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES paper(paper_id),
            formulation_name TEXT,
            composition_raw TEXT
        );
        CREATE TABLE chemical_component (
            component_id INTEGER PRIMARY KEY,
            formulation_id INTEGER NOT NULL REFERENCES formulation(formulation_id),
            component_name_reported TEXT NOT NULL,
            component_role TEXT NOT NULL
        );
        CREATE TABLE experiment (
            experiment_id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES paper(paper_id),
            formulation_id INTEGER NOT NULL REFERENCES formulation(formulation_id),
            cell_type TEXT NOT NULL,
            payload_type TEXT,
            species TEXT,
            in_vitro_in_vivo TEXT,
            dose REAL,
            dose_unit TEXT,
            assay TEXT
        );
        CREATE TABLE outcome (
            outcome_id INTEGER PRIMARY KEY,
            experiment_id INTEGER NOT NULL REFERENCES experiment(experiment_id),
            endpoint_family TEXT NOT NULL,
            endpoint_name TEXT NOT NULL,
            outcome_value REAL,
            outcome_unit TEXT,
            normalization_basis TEXT,
            qualitative_outcome TEXT,
            value_status TEXT NOT NULL
        );
        CREATE TABLE evidence (
            evidence_id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES paper(paper_id),
            experiment_id INTEGER REFERENCES experiment(experiment_id),
            outcome_id INTEGER REFERENCES outcome(outcome_id),
            field_name TEXT NOT NULL,
            evidence_text TEXT NOT NULL,
            evidence_location_type TEXT NOT NULL,
            extraction_method TEXT NOT NULL,
            extraction_confidence TEXT NOT NULL,
            evidence_review_status TEXT NOT NULL DEFAULT 'unreviewed'
        );
        INSERT INTO paper VALUES (7, 'Legacy paper', 'fixture', '2026-08-01', 'include');
        INSERT INTO formulation VALUES (11, 7, 'Legacy LNP', '50:10:38.5:1.5');
        INSERT INTO experiment (
            experiment_id, paper_id, formulation_id, cell_type, payload_type
        ) VALUES (13, 7, 11, 'hepatocyte', 'mRNA');
        """
    )
    return connection


def test_migration_preserves_legacy_rows_and_is_idempotent() -> None:
    connection = _legacy_connection()
    with connection:
        migrate_database(connection)
        migrate_database(connection)

    assert connection.execute(
        "SELECT paper_id, title FROM paper"
    ).fetchall() == [(7, "Legacy paper")]
    assert connection.execute(
        "SELECT experiment_id, payload_type FROM experiment"
    ).fetchall() == [(13, "mRNA")]
    assert connection.execute(
        "SELECT version FROM schema_migration ORDER BY version"
    ).fetchall() == [(1,), (2,)]
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_provenance_missing_fields_and_verification_have_foreign_keys() -> None:
    connection = _legacy_connection()
    migrate_database(connection)

    connection.execute(
        """
        INSERT INTO record_source (
            paper_id, entity_type, entity_id, artifact_path, artifact_sha256,
            pipeline_name, pipeline_version, imported_at
        ) VALUES (7, 'experiment', 13, 'merged/GP-002.json', ?, 'compact', 'v1.2', ?)
        """,
        ("a" * 64, "2026-08-06T10:00:00Z"),
    )
    connection.execute(
        """
        INSERT INTO missing_field (
            experiment_id, field_name, reason, recorded_at
        ) VALUES (13, 'dose', 'not reported', '2026-08-06T10:01:00Z')
        """
    )
    connection.execute(
        """
        INSERT INTO field_verification (
            experiment_id, field_name, verification_status, verified_at
        ) VALUES (13, 'payload_type', 'automatically_validated', '2026-08-06T10:02:00Z')
        """
    )

    assert connection.execute(
        "SELECT artifact_path, pipeline_version FROM record_source"
    ).fetchone() == ("merged/GP-002.json", "v1.2")
    assert connection.execute(
        "SELECT field_name, reason FROM missing_field"
    ).fetchone() == ("dose", "not reported")
    assert connection.execute(
        "SELECT field_name, verification_status FROM field_verification"
    ).fetchone() == ("payload_type", "automatically_validated")

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO missing_field (
                experiment_id, field_name, reason, recorded_at
            ) VALUES (999, 'dose', 'not reported', '2026-08-06T10:03:00Z')
            """
        )


def test_review_history_is_additive_and_screening_events_are_retained() -> None:
    connection = _legacy_connection()
    migrate_database(connection)

    revisions = [
        ("1.0", "1.5", "first correction", "results, p. 4", "reviewer-a", "2026-08-06T11:00:00Z"),
        ("1.5", "2.0", "second correction", "table 2", "reviewer-b", "2026-08-06T12:00:00Z"),
    ]
    connection.executemany(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, previous_value, corrected_value,
            evidence_excerpt, evidence_location, reviewer, reviewed_at
        ) VALUES (13, 'dose', ?, ?, ?, ?, ?, ?)
        """,
        revisions,
    )
    connection.execute(
        """
        INSERT INTO screening_event (
            paper_id, disposition, reason, source, occurred_at
        ) VALUES (7, 'include', 'meets scope', 'manual review', '2026-08-06T09:00:00Z')
        """
    )

    assert connection.execute(
        "SELECT previous_value, corrected_value FROM review_revision ORDER BY review_revision_id"
    ).fetchall() == [("1.0", "1.5"), ("1.5", "2.0")]
    assert connection.execute(
        "SELECT disposition, reason FROM screening_event"
    ).fetchone() == ("include", "meets scope")

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE review_revision SET corrected_value = '9.0' WHERE review_revision_id = 1"
        )


def test_missing_field_rejects_resolution_from_another_field() -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    revision_id = connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, corrected_value, evidence_excerpt,
            evidence_location, reviewer, reviewed_at
        ) VALUES (13, 'dose', '0.75', 'Reported dose was 0.75 mg/kg.',
                  'methods, p. 3', 'reviewer-a', '2026-08-06T11:00:00Z')
        """
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="matching experiment and field"):
        connection.execute(
            """
            INSERT INTO missing_field (
                experiment_id, field_name, reason, recorded_at,
                resolved_by_review_revision_id, resolved_at
            ) VALUES (13, 'species', 'not extracted', '2026-08-06T10:00:00Z',
                      ?, '2026-08-06T11:00:00Z')
            """,
            (revision_id,),
        )


def test_missing_field_rejects_resolution_from_another_arm() -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    connection.execute(
        """
        INSERT INTO experiment (
            experiment_id, paper_id, formulation_id, cell_type, payload_type
        ) VALUES (14, 7, 11, 'hepatocyte', 'mRNA')
        """
    )
    revision_id = connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, corrected_value, evidence_excerpt,
            evidence_location, reviewer, reviewed_at
        ) VALUES (13, 'dose', '0.75', 'Reported dose was 0.75 mg/kg.',
                  'methods, p. 3', 'reviewer-a', '2026-08-06T11:00:00Z')
        """
    ).lastrowid
    missing_field_id = connection.execute(
        """
        INSERT INTO missing_field (
            experiment_id, field_name, reason, recorded_at
        ) VALUES (14, 'dose', 'not extracted', '2026-08-06T10:00:00Z')
        """
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="matching experiment and field"):
        connection.execute(
            """
            UPDATE missing_field
            SET resolved_by_review_revision_id = ?,
                resolved_at = '2026-08-06T11:00:00Z'
            WHERE missing_field_id = ?
            """,
            (revision_id, missing_field_id),
        )


def test_screening_only_paper_cannot_be_marked_import_ready() -> None:
    connection = _legacy_connection()
    migrate_database(connection)

    connection.execute(
        "UPDATE paper SET import_status = 'screening_only' WHERE paper_id = 7"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE paper SET import_status = 'ready' WHERE paper_id = 7"
        )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO paper (
                title, source_type, retrieval_date, screening_status, import_status
            ) VALUES ('Excluded paper', 'fixture', '2026-08-06', 'exclude', 'ready')
            """
        )


@pytest.mark.parametrize("disposition", ["exclude", "screening_only"])
def test_exclusion_event_removes_ready_import_eligibility(disposition: str) -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    connection.execute(
        "UPDATE paper SET import_status = 'ready' WHERE paper_id = 7"
    )

    connection.execute(
        """
        INSERT INTO screening_event (
            paper_id, disposition, reason, source, occurred_at
        ) VALUES (7, ?, 'outside scope', 'human screening', '2026-08-06T12:00:00Z')
        """,
        (disposition,),
    )

    assert connection.execute(
        "SELECT screening_status, import_status FROM paper WHERE paper_id = 7"
    ).fetchone() == ("exclude", "screening_only")


def test_eligibility_result_profiles_are_stored_independently() -> None:
    connection = _legacy_connection()
    migrate_database(connection)

    connection.executemany(
        """
        INSERT INTO eligibility_result (
            experiment_id, profile, eligible, reasons_json, rules_version, evaluated_at
        ) VALUES (13, ?, ?, ?, 'v1', '2026-08-06T10:00:00Z')
        """,
        [
            ("nearest_neighbor", 1, "[]"),
            ("comet", 0, '["dose"]'),
        ],
    )

    assert connection.execute(
        "SELECT profile, eligible FROM eligibility_result ORDER BY profile"
    ).fetchall() == [("comet", 0), ("nearest_neighbor", 1)]
