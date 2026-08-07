from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from pathlib import Path

import pytest

from src.database import migrations as migrations_module
from src.database.import_bundle import import_bundle
from src.database.import_contracts import ImportBundle
from src.database.migrations import migrate_database
from src.init_db import initialize_database


PAPER_STATE_CASES = [
    ("include", "ready", True),
    ("include", "ready_with_missing_fields", True),
    ("include", "needs_review", True),
    ("include", "blocked", True),
    ("include", "screening_only", False),
    ("manual_review", "ready", True),
    ("manual_review", "ready_with_missing_fields", True),
    ("manual_review", "needs_review", True),
    ("manual_review", "blocked", True),
    ("manual_review", "screening_only", False),
    ("exclude", "ready", False),
    ("exclude", "ready_with_missing_fields", False),
    ("exclude", "needs_review", False),
    ("exclude", "blocked", False),
    ("exclude", "screening_only", True),
]

IMPORT_BUNDLE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "database"
    / "import_bundle"
    / "valid_bundle.json"
)


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
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,)]
    experiment_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(experiment)")
    }
    assert {
        "intended_target_cell",
        "target_or_recipient_organ",
        "observed_transfected_cell",
    } <= experiment_columns
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_lossless_fact_tables_and_wide_formulation_interface_exist() -> None:
    connection = _legacy_connection()
    migrate_database(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "source_artifact",
        "source_fact",
        "source_fact_evidence",
        "fact_projection",
    } <= tables
    columns = [
        row[1]
        for row in connection.execute("PRAGMA table_info(lnp_formulation_wide)")
    ]
    assert columns == [
        "lnp_name",
        "chemical_formulation_total",
        "lnp_molar_ratio",
        "ionizable_lipid",
        "helper_lipid",
        "cholesterol",
        "peg_lipid",
        "others",
    ]


def test_source_fact_requires_visible_disposition() -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    artifact_id = connection.execute(
        """
        INSERT INTO source_artifact (
            paper_id, logical_path, sha256, role, schema_family,
            validation_status, contributes_facts, contributes_evidence
        ) VALUES (7, 'result.json', ?, 'primary_extraction', 'fixture',
                  'accepted', 1, 1)
        """,
        ("a" * 64,),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO source_fact (
                source_artifact_id, paper_id, json_path, source_record_key,
                record_kind, subject_type, subject_key, field_name,
                raw_value_json, fact_identity_sha256, import_disposition
            ) VALUES (?, 7, '$.x', 'x', 'field', 'paper', 'GP-002', 'title',
                      '"value"', ?, '')
            """,
            (artifact_id, "b" * 64),
        )


def test_fact_projection_rejects_cross_paper_target() -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    connection.execute(
        """
        INSERT INTO paper (
            paper_id, title, source_type, retrieval_date, screening_status,
            source_paper_id, import_status
        ) VALUES (8, 'Other paper', 'fixture', '2026-08-07', 'include',
                  'OTHER', 'needs_review')
        """
    )
    other_formulation = connection.execute(
        "INSERT INTO formulation (paper_id, formulation_name) VALUES (8, 'Other LNP')"
    ).lastrowid
    artifact_id = connection.execute(
        """
        INSERT INTO source_artifact (
            paper_id, logical_path, sha256, role, schema_family,
            validation_status, contributes_facts, contributes_evidence
        ) VALUES (7, 'result.json', ?, 'primary_extraction', 'fixture',
                  'accepted', 1, 1)
        """,
        ("a" * 64,),
    ).lastrowid
    fact_id = connection.execute(
        """
        INSERT INTO source_fact (
            source_artifact_id, paper_id, json_path, source_record_key,
            record_kind, subject_type, subject_key, field_name,
            raw_value_json, fact_identity_sha256, import_disposition,
            disposition_reason
        ) VALUES (?, 7, '$.x', 'x', 'field', 'formulation', 'F1',
                  'formulation_name', '"value"', ?, 'unresolved', 'pending')
        """,
        (artifact_id, "b" * 64),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="same paper"):
        connection.execute(
            """
            INSERT INTO fact_projection (
                source_fact_id, paper_id, entity_type, entity_id, field_name,
                canonical_fact_sha256, projection_status
            ) VALUES (?, 7, 'formulation', ?, 'formulation_name', ?, 'active')
            """,
            (fact_id, other_formulation, "c" * 64),
        )


def test_wide_formulation_renders_gp008_as_one_row() -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    formulation_id = connection.execute(
        """
        INSERT INTO formulation (
            paper_id, formulation_name, chemical_formulation_total,
            lnp_molar_ratio
        ) VALUES (7, 'alpha-CD163/LNP-FAPCAR',
                  'ionizable lipid-DSPC-cholesterol-PEG-lipid',
                  '45:30:23.5:1.5')
        """
    ).lastrowid
    connection.executemany(
        """
        INSERT INTO chemical_component (
            formulation_id, component_name_reported, component_role,
            amount_value, amount_unit, amount_raw, composition_position
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (formulation_id, "heptadecan-9-yl... amino lipid", "ionizable_lipid", 45, "mol%", "45", 1),
            (formulation_id, "DSPC", "helper_lipid", 30, "mol%", "30", 2),
            (formulation_id, "cholesterol", "cholesterol", 23.5, "mol%", "23.5", 3),
            (formulation_id, "PEG-lipid", "peg_lipid", 1.5, "mol%", "1.5", 4),
            (formulation_id, "DSPE-PEG-maleimide", "targeting_anchor", None, None, None, 5),
            (formulation_id, "anti-CD163 antibody", "targeting_ligand", None, None, None, 6),
            (formulation_id, "antibody:LNP 1:20", "other", None, None, None, 7),
        ],
    )

    row = connection.execute(
        "SELECT * FROM lnp_formulation_wide WHERE lnp_name = 'alpha-CD163/LNP-FAPCAR'"
    ).fetchone()

    assert row == (
        "alpha-CD163/LNP-FAPCAR",
        "ionizable lipid-DSPC-cholesterol-PEG-lipid",
        "45:30:23.5:1.5",
        "heptadecan-9-yl... amino lipid",
        "DSPC",
        "cholesterol",
        "PEG-lipid",
        "DSPE-PEG-maleimide; anti-CD163 antibody; antibody:LNP 1:20",
    )


def test_migration_and_first_bundle_import_converge_in_one_pass(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "clean-legacy.db"
    initialize_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    bundle = ImportBundle.from_dict(
        json.loads(IMPORT_BUNDLE_FIXTURE.read_text(encoding="utf-8"))
    )
    try:
        migrate_database(connection)
        connection.commit()
        first = import_bundle(connection, bundle)
        connection.commit()
        first_dump = tuple(connection.iterdump())

        migrate_database(connection)
        connection.commit()
        second = import_bundle(connection, bundle)
        connection.commit()
        second_dump = tuple(connection.iterdump())

        assert first.inserted == 6
        assert second.unchanged == 6
        assert second_dump == first_dump
    finally:
        connection.close()


def test_migration_replaces_legacy_screening_trigger_once() -> None:
    connection = _legacy_connection()
    connection.executescript(
        """
        CREATE TRIGGER trg_paper_screening_state_insert
        BEFORE INSERT ON paper
        BEGIN
            SELECT RAISE(ABORT, 'legacy screening trigger');
        END;
        """
    )
    try:
        migrate_database(connection)
        connection.commit()
        first = connection.execute(
            """
            SELECT rowid, sql FROM sqlite_master
            WHERE type = 'trigger'
              AND name = 'trg_paper_screening_state_insert'
            """
        ).fetchone()
        connection.execute(
            "CREATE INDEX migration_order_marker ON paper(title)"
        )
        connection.commit()

        migrate_database(connection)
        connection.commit()
        second = connection.execute(
            """
            SELECT rowid, sql FROM sqlite_master
            WHERE type = 'trigger'
              AND name = 'trg_paper_screening_state_insert'
            """
        ).fetchone()

        assert "legacy screening trigger" not in first[1]
        assert "screening exclusion requires screening_only" in first[1]
        assert second == first
    finally:
        connection.close()


def test_migration_backfills_legacy_excluded_papers_to_screening_only() -> None:
    connection = _legacy_connection()
    connection.execute(
        """
        INSERT INTO paper (
            paper_id, title, source_type, retrieval_date, screening_status
        ) VALUES (8, 'Legacy excluded paper', 'fixture', '2026-08-01', 'exclude')
        """
    )
    connection.commit()

    migrate_database(connection)

    assert connection.execute(
        "SELECT screening_status, import_status FROM paper WHERE paper_id = 8"
    ).fetchone() == ("exclude", "screening_only")


@pytest.mark.parametrize(
    ("screening_status", "import_status", "allowed"), PAPER_STATE_CASES
)
def test_paper_insert_enforces_screening_and_import_state_pair(
    screening_status: str,
    import_status: str,
    allowed: bool,
) -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    statement = """
        INSERT INTO paper (
            title, source_type, retrieval_date, screening_status, import_status
        ) VALUES ('New paper', 'fixture', '2026-08-06', ?, ?)
    """

    if allowed:
        connection.execute(statement, (screening_status, import_status))
        assert connection.execute(
            """
            SELECT screening_status, import_status
            FROM paper
            WHERE title = 'New paper'
            """
        ).fetchone() == (screening_status, import_status)
    else:
        with pytest.raises(sqlite3.IntegrityError, match="screening exclusion"):
            connection.execute(statement, (screening_status, import_status))


@pytest.mark.parametrize(
    ("screening_status", "import_status", "allowed"), PAPER_STATE_CASES
)
@pytest.mark.parametrize("starting_excluded", [False, True])
def test_paper_update_enforces_screening_and_import_state_pair(
    screening_status: str,
    import_status: str,
    allowed: bool,
    starting_excluded: bool,
) -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    if starting_excluded:
        connection.execute(
            """
            UPDATE paper
            SET screening_status = 'exclude', import_status = 'screening_only'
            WHERE paper_id = 7
            """
        )
    statement = """
        UPDATE paper
        SET screening_status = ?, import_status = ?
        WHERE paper_id = 7
    """

    if allowed:
        connection.execute(statement, (screening_status, import_status))
        assert connection.execute(
            "SELECT screening_status, import_status FROM paper WHERE paper_id = 7"
        ).fetchone() == (screening_status, import_status)
    else:
        with pytest.raises(sqlite3.IntegrityError, match="screening exclusion"):
            connection.execute(statement, (screening_status, import_status))


def test_screening_only_exit_requires_same_statement_screening_reversal() -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    connection.execute(
        """
        UPDATE paper
        SET screening_status = 'exclude', import_status = 'screening_only'
        WHERE paper_id = 7
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="screening exclusion"):
        connection.execute(
            "UPDATE paper SET import_status = 'needs_review' WHERE paper_id = 7"
        )

    connection.execute(
        """
        UPDATE paper
        SET screening_status = 'include', import_status = 'needs_review'
        WHERE paper_id = 7
        """
    )
    assert connection.execute(
        "SELECT screening_status, import_status FROM paper WHERE paper_id = 7"
    ).fetchone() == ("include", "needs_review")


def test_migration_rolls_back_every_change_after_late_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _legacy_connection()
    before = tuple(connection.iterdump())
    monkeypatch.setattr(
        migrations_module,
        "INTEGRITY_SCHEMA_SQL",
        migrations_module.INTEGRITY_SCHEMA_SQL
        + "\nSELECT definitely_missing_migration_function();\n",
    )

    with pytest.raises(sqlite3.OperationalError):
        migrate_database(connection)

    assert tuple(connection.iterdump()) == before
    assert connection.in_transaction is False


def test_screening_trigger_repair_rolls_back_after_late_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _legacy_connection()
    connection.executescript(
        """
        CREATE TRIGGER trg_paper_screening_state_insert
        BEFORE INSERT ON paper
        BEGIN
            SELECT RAISE(ABORT, 'legacy screening trigger');
        END;
        """
    )
    before = tuple(connection.iterdump())
    monkeypatch.setattr(
        migrations_module,
        "SCREENING_STATE_SCHEMA_SQL",
        migrations_module.SCREENING_STATE_SCHEMA_SQL
        + "\nSELECT definitely_missing_screening_migration_function();\n",
    )

    with pytest.raises(sqlite3.OperationalError):
        migrate_database(connection)

    assert tuple(connection.iterdump()) == before
    assert connection.in_transaction is False


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


def test_migration_adds_entity_action_and_evidence_context_to_review_history() -> None:
    connection = _legacy_connection()
    migrate_database(connection)

    columns = {row[1] for row in connection.execute('PRAGMA table_info(review_revision)')}
    assert {'entity_type', 'entity_id', 'review_action', 'evidence_id'} <= columns
    assert connection.execute(
        "SELECT version FROM schema_migration ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,)]

    revision_id = connection.execute(
        """INSERT INTO review_revision (
               experiment_id, entity_type, entity_id, field_name, corrected_value,
               evidence_excerpt, evidence_location, reviewer, decision, review_action,
               reviewer_notes, reviewed_at
           ) VALUES (13, 'arm', 13, 'dose', 'not reported', 'Human review action',
                     'human review record', 'reviewer-a', 'rejected', 'not_reported',
                     'No supported value.', '2026-08-06T11:00:00Z')"""
    ).lastrowid

    assert connection.execute(
        "SELECT entity_type, entity_id, review_action FROM review_revision WHERE review_revision_id = ?",
        (revision_id,),
    ).fetchone() == ('arm', 13, 'not_reported')
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        connection.execute(
            "UPDATE review_revision SET reviewer_notes = 'changed' WHERE review_revision_id = ?",
            (revision_id,),
        )


def test_v5_repairs_v4_missing_field_triggers_for_shared_formulations() -> None:
    connection = _legacy_connection()
    migrate_database(connection)
    connection.execute('DELETE FROM schema_migration WHERE version = 5')
    connection.execute('DROP TRIGGER trg_missing_field_resolution_matches_insert')
    connection.execute('DROP TRIGGER trg_missing_field_resolution_matches_update')
    migrations_module._execute_sql_script(connection, migrations_module.INTEGRITY_SCHEMA_SQL)
    connection.execute(
        """INSERT INTO experiment (
               experiment_id, paper_id, formulation_id, cell_type, payload_type
           ) VALUES (14, 7, 11, 'hepatocyte', 'mRNA')"""
    )
    missing_id = connection.execute(
        """INSERT INTO missing_field (experiment_id, field_name, reason, recorded_at)
           VALUES (14, 'formulation_name', 'not extracted', '2026-08-06T10:00:00Z')"""
    ).lastrowid
    revision_id = connection.execute(
        """INSERT INTO review_revision (
               experiment_id, entity_type, entity_id, field_name, corrected_value,
               evidence_excerpt, evidence_location, reviewer, decision, review_action,
               reviewed_at
           ) VALUES (13, 'formulation', 11, 'formulation_name', 'Reviewed LNP',
                     'Shared formulation name.', 'table 1', 'reviewer-a', 'accepted',
                     'correct', '2026-08-06T11:00:00Z')"""
    ).lastrowid
    connection.execute(
        """INSERT INTO outcome (
               outcome_id, experiment_id, endpoint_family, endpoint_name, value_status
           ) VALUES (21, 13, 'expression', 'luciferase', 'reported')"""
    )
    outcome_revision_id = connection.execute(
        """INSERT INTO review_revision (
               experiment_id, entity_type, entity_id, field_name, corrected_value,
               evidence_excerpt, evidence_location, reviewer, decision, review_action,
               reviewed_at
               ) VALUES (13, 'outcome', 21, 'outcome_value', '14',
                     'Outcome review.', 'figure 1', 'reviewer-a', 'accepted',
                     'correct', '2026-08-06T11:05:00Z')"""
    ).lastrowid
    connection.execute(
        """INSERT INTO field_verification (
               experiment_id, field_name, review_revision_id, verification_status, verified_at
           ) VALUES (13, 'outcome_value', ?, 'rejected', '2026-08-06T11:05:00Z')""",
        (outcome_revision_id,),
    )
    connection.execute(
        """INSERT INTO missing_field (experiment_id, field_name, reason, recorded_at)
           VALUES (13, 'outcome_value', 'not reported', '2026-08-06T11:05:00Z')"""
    )
    for outcome_id in (22, 23):
        connection.execute(
            """INSERT INTO outcome (
                   outcome_id, experiment_id, endpoint_family, endpoint_name, value_status
               ) VALUES (?, 14, 'expression', ?, 'reported')""",
            (outcome_id, f'endpoint-{outcome_id}'),
        )
        connection.execute(
            """INSERT INTO review_revision (
                   experiment_id, entity_type, entity_id, field_name, corrected_value,
                   evidence_excerpt, evidence_location, reviewer, decision, review_action,
                   reviewed_at
               ) VALUES (14, 'outcome', ?, 'outcome_value', '10', 'Outcome review.',
                         'figure 2', 'reviewer-a', 'accepted', 'correct',
                         '2026-08-06T11:06:00Z')""",
            (outcome_id,),
        )
    connection.execute(
        """INSERT INTO missing_field (experiment_id, field_name, reason, recorded_at)
           VALUES (14, 'outcome_value', 'not reported', '2026-08-06T11:06:00Z')"""
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match='matching experiment and field'):
        connection.execute(
            """UPDATE missing_field SET resolved_by_review_revision_id = ?,
                      resolved_at = '2026-08-06T11:00:00Z'
               WHERE missing_field_id = ?""",
            (revision_id, missing_id),
        )
    migrate_database(connection)
    connection.execute(
        """UPDATE missing_field SET resolved_by_review_revision_id = ?,
                  resolved_at = '2026-08-06T11:00:00Z'
           WHERE missing_field_id = ?""",
        (revision_id, missing_id),
    )

    assert connection.execute(
        'SELECT version FROM schema_migration WHERE version = 5'
    ).fetchone() == (5,)
    assert connection.execute(
        'SELECT field_name FROM field_verification WHERE review_revision_id = ?',
        (outcome_revision_id,),
    ).fetchone() == ('outcome:21:outcome_value',)
    assert connection.execute(
        "SELECT field_name FROM missing_field WHERE experiment_id = 13 AND reason = 'not reported'"
    ).fetchone() == ('outcome:21:outcome_value',)
    assert connection.execute(
        "SELECT field_name, reason FROM missing_field WHERE experiment_id = 14 AND field_name LIKE 'outcome:ambiguous:%'"
    ).fetchone() == (
        'outcome:ambiguous:outcome_value',
        'ambiguous outcome ownership; not reported',
    )


def test_legacy_experiment_entity_alias_remains_insertable_after_upgrade() -> None:
    connection = _legacy_connection()
    migrate_database(connection)

    revision_id = connection.execute(
        """INSERT INTO review_revision (
               experiment_id, entity_type, field_name, corrected_value,
               evidence_excerpt, evidence_location, reviewer, decision, review_action,
               reviewed_at
           ) VALUES (13, 'experiment', 'dose', '0.75', 'Reported dose.',
                     'methods', 'reviewer-a', 'accepted', 'correct',
                     '2026-08-06T11:00:00Z')"""
    ).lastrowid

    assert revision_id == 1


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

    with pytest.raises(sqlite3.IntegrityError, match="matching entity and field"):
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

    with pytest.raises(sqlite3.IntegrityError, match="matching entity and field"):
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
        """
        UPDATE paper
        SET screening_status = 'exclude', import_status = 'screening_only'
        WHERE paper_id = 7
        """
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
def test_migration_expands_cell_type_without_losing_existing_arm(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        schema_path = Path(__file__).resolve().parents[1] / "src/schema.sql"
        schema = schema_path.read_text(encoding="utf-8").replace(
            "'hsc',\n                'not_reported',\n                'other'",
            "'hsc'",
            1,
        )
        connection.executescript(schema)
        connection.execute(
            "INSERT INTO paper (paper_id, title, source_type, retrieval_date) "
            "VALUES (1, 'paper', 'fixture', '2026-08-06')"
        )
        connection.execute(
            "INSERT INTO formulation (formulation_id, paper_id) VALUES (1, 1)"
        )
        connection.execute(
            "INSERT INTO experiment (experiment_id, paper_id, formulation_id, cell_type) "
            "VALUES (1, 1, 1, 'hepatocyte')"
        )
        connection.commit()
        migrate_database(connection)
        connection.execute(
            "INSERT INTO experiment (experiment_id, paper_id, formulation_id, cell_type) "
            "VALUES (2, 1, 1, 'not_reported')"
        )
        connection.execute(
            "INSERT INTO experiment (experiment_id, paper_id, formulation_id, cell_type) "
            "VALUES (3, 1, 1, 'other')"
        )
        assert connection.execute(
            "SELECT cell_type FROM experiment ORDER BY experiment_id"
        ).fetchall() == [('hepatocyte',), ('not_reported',), ('other',)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_cell_type_rebuild_rolls_back_with_later_migration_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "legacy-failure.db"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    schema_path = Path(__file__).resolve().parents[1] / "src/schema.sql"
    legacy_schema = schema_path.read_text(encoding="utf-8").replace(
        "'hsc',\n                'not_reported',\n                'other'",
        "'hsc'",
        1,
    )
    connection.executescript(legacy_schema)
    connection.execute(
        "INSERT INTO paper (paper_id, title, source_type, retrieval_date) "
        "VALUES (1, 'paper', 'fixture', '2026-08-06')"
    )
    connection.execute("INSERT INTO formulation (formulation_id, paper_id) VALUES (1, 1)")
    connection.execute(
        "INSERT INTO experiment (experiment_id, paper_id, formulation_id, cell_type) "
        "VALUES (1, 1, 1, 'hepatocyte')"
    )
    connection.commit()
    before_dump = "\n".join(connection.iterdump())
    before_schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]

    def fail_later(*_args, **_kwargs):
        raise RuntimeError("injected late failure")

    monkeypatch.setattr(migrations_module, "_execute_sql_script", fail_later)
    with pytest.raises(RuntimeError, match="injected late failure"):
        migrate_database(connection)

    assert "\n".join(connection.iterdump()) == before_dump
    assert connection.execute("PRAGMA schema_version").fetchone()[0] == before_schema_version
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    connection.close()


def test_cell_type_migration_rejects_preexisting_orphan_without_mutation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-orphan.db"
    connection = sqlite3.connect(database_path)
    schema_path = Path(__file__).resolve().parents[1] / "src/schema.sql"
    legacy_schema = schema_path.read_text(encoding="utf-8").replace(
        "'hsc',\n                'not_reported',\n                'other'",
        "'hsc'",
        1,
    )
    connection.executescript(legacy_schema)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        "INSERT INTO paper (paper_id, title, source_type, retrieval_date) "
        "VALUES (1, 'paper', 'fixture', '2026-08-06')"
    )
    connection.execute("INSERT INTO formulation (formulation_id, paper_id) VALUES (1, 1)")
    connection.execute(
        "INSERT INTO experiment (experiment_id, paper_id, formulation_id, cell_type) "
        "VALUES (1, 999, 1, 'hepatocyte')"
    )
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")
    before_dump = "\n".join(connection.iterdump())
    before_schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
    before_ledger = connection.execute(
        "SELECT version, name, applied_at FROM schema_migration ORDER BY version"
    ).fetchall()
    before_experiment_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='experiment'"
    ).fetchone()[0]

    with pytest.raises(RuntimeError, match="foreign-key violations before migration"):
        migrate_database(connection)

    assert "\n".join(connection.iterdump()) == before_dump
    assert connection.execute("PRAGMA schema_version").fetchone()[0] == before_schema_version
    assert connection.execute(
        "SELECT version, name, applied_at FROM schema_migration ORDER BY version"
    ).fetchall() == before_ledger
    assert connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='experiment'"
    ).fetchone()[0] == before_experiment_sql
    assert "'not_reported'" not in before_experiment_sql.split("cell_type", 1)[1].split(
        "cell_source", 1
    )[0]
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    connection.close()
