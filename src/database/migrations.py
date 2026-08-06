"""Additive SQLite migrations for the working evidence database."""

from __future__ import annotations

import re
import sqlite3


MIGRATION_VERSION = 3

PAPER_COLUMNS = {
    "source_paper_id": "TEXT",
    "import_status": "TEXT NOT NULL DEFAULT 'needs_review' CHECK (import_status IN ('ready', 'ready_with_missing_fields', 'needs_review', 'blocked', 'screening_only'))",
}

EXPERIMENT_COLUMNS = {
    "tissue_or_organ": "TEXT",
    "disease_model": "TEXT",
    "payload_encoded_product": "TEXT",
    "payload_molecular_target": "TEXT",
}

REVIEW_REVISION_COLUMNS = {
    "supersedes_review_revision_id": (
        "INTEGER REFERENCES review_revision(review_revision_id) "
        "ON UPDATE CASCADE ON DELETE RESTRICT"
    ),
}

ADDITIVE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS record_source (
    record_source_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('paper', 'formulation', 'chemical_component', 'experiment', 'outcome', 'evidence')),
    entity_id INTEGER,
    artifact_path TEXT NOT NULL CHECK (length(trim(artifact_path)) > 0),
    artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    pipeline_name TEXT NOT NULL CHECK (length(trim(pipeline_name)) > 0),
    pipeline_version TEXT,
    extraction_run_identifier TEXT,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS review_revision (
    review_revision_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'experiment',
    entity_id INTEGER,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    previous_value TEXT,
    corrected_value TEXT NOT NULL CHECK (length(trim(corrected_value)) > 0),
    evidence_excerpt TEXT NOT NULL CHECK (length(trim(evidence_excerpt)) > 0),
    evidence_location_type TEXT,
    evidence_location TEXT NOT NULL CHECK (length(trim(evidence_location)) > 0),
    reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
    decision TEXT NOT NULL DEFAULT 'accepted' CHECK (decision IN ('accepted', 'rejected', 'superseded')),
    supersedes_review_revision_id INTEGER,
    reviewer_notes TEXT,
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (supersedes_review_revision_id) REFERENCES review_revision(review_revision_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS missing_field (
    missing_field_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    recorded_at TEXT NOT NULL,
    resolved_by_review_revision_id INTEGER,
    resolved_at TEXT,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (resolved_by_review_revision_id) REFERENCES review_revision(review_revision_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK ((resolved_by_review_revision_id IS NULL AND resolved_at IS NULL) OR (resolved_by_review_revision_id IS NOT NULL AND resolved_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS field_verification (
    field_verification_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    evidence_id INTEGER,
    review_revision_id INTEGER,
    verification_status TEXT NOT NULL CHECK (verification_status IN ('unreviewed', 'automatically_validated', 'manually_verified', 'ambiguous', 'conflict', 'rejected')),
    notes TEXT,
    verified_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (review_revision_id) REFERENCES review_revision(review_revision_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS arm_assessment (
    experiment_id INTEGER PRIMARY KEY,
    completeness_status TEXT NOT NULL CHECK (completeness_status IN ('complete', 'incomplete', 'conflict', 'quarantined')),
    missing_fields_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(missing_fields_json)),
    verification_status TEXT NOT NULL CHECK (verification_status IN ('unreviewed', 'automatically_validated', 'manually_verified', 'ambiguous', 'conflict', 'rejected')),
    nearest_neighbor_eligible INTEGER NOT NULL DEFAULT 0 CHECK (nearest_neighbor_eligible IN (0, 1)),
    comet_eligible INTEGER NOT NULL DEFAULT 0 CHECK (comet_eligible IN (0, 1)),
    quarantine_reason TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE CASCADE,
    CHECK (completeness_status != 'quarantined' OR length(trim(quarantine_reason)) > 0)
);

CREATE TABLE IF NOT EXISTS screening_event (
    screening_event_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('include', 'exclude', 'manual_review', 'screening_only')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    search_query_id TEXT,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS eligibility_result (
    experiment_id INTEGER NOT NULL,
    profile TEXT NOT NULL CHECK (profile IN ('nearest_neighbor', 'comet')),
    eligible INTEGER NOT NULL CHECK (eligible IN (0, 1)),
    reasons_json TEXT NOT NULL CHECK (json_valid(reasons_json)),
    rules_version TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY (experiment_id, profile),
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_source_paper_id
    ON paper(source_paper_id) WHERE source_paper_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_record_source_paper ON record_source(paper_id);
CREATE INDEX IF NOT EXISTS idx_missing_field_experiment ON missing_field(experiment_id);
CREATE INDEX IF NOT EXISTS idx_field_verification_experiment ON field_verification(experiment_id);
CREATE INDEX IF NOT EXISTS idx_review_revision_experiment ON review_revision(experiment_id);
CREATE INDEX IF NOT EXISTS idx_screening_event_paper ON screening_event(paper_id);

CREATE TRIGGER IF NOT EXISTS trg_review_revision_no_update
BEFORE UPDATE ON review_revision
BEGIN
    SELECT RAISE(ABORT, 'review revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_revision_no_delete
BEFORE DELETE ON review_revision
BEGIN
    SELECT RAISE(ABORT, 'review revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_screening_only_not_ready
BEFORE UPDATE OF import_status ON paper
WHEN OLD.import_status = 'screening_only'
 AND NEW.import_status IN ('ready', 'ready_with_missing_fields')
BEGIN
    SELECT RAISE(ABORT, 'screening-only papers cannot become import candidates');
END;

CREATE TRIGGER IF NOT EXISTS trg_excluded_paper_not_ready_insert
BEFORE INSERT ON paper
WHEN NEW.screening_status = 'exclude'
 AND NEW.import_status IN ('ready', 'ready_with_missing_fields')
BEGIN
    SELECT RAISE(ABORT, 'excluded papers cannot become import candidates');
END;

CREATE TRIGGER IF NOT EXISTS trg_excluded_paper_not_ready_update
BEFORE UPDATE OF screening_status, import_status ON paper
WHEN NEW.screening_status = 'exclude'
 AND NEW.import_status IN ('ready', 'ready_with_missing_fields')
BEGIN
    SELECT RAISE(ABORT, 'excluded papers cannot become import candidates');
END;

INSERT OR IGNORE INTO schema_migration (version, name, applied_at)
VALUES (1, 'working_evidence_database_contract', '2026-08-06T00:00:00Z');
"""

INTEGRITY_SCHEMA_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_revision_superseded_once
    ON review_revision(supersedes_review_revision_id)
    WHERE supersedes_review_revision_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_missing_field_resolution_matches_insert
BEFORE INSERT ON missing_field
WHEN NEW.resolved_by_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM review_revision
    WHERE review_revision_id = NEW.resolved_by_review_revision_id
      AND experiment_id = NEW.experiment_id
      AND field_name = NEW.field_name
      AND decision = 'accepted'
 )
BEGIN
    SELECT RAISE(ABORT, 'missing field resolution requires matching experiment and field');
END;

CREATE TRIGGER IF NOT EXISTS trg_missing_field_resolution_matches_update
BEFORE UPDATE OF experiment_id, field_name, resolved_by_review_revision_id
ON missing_field
WHEN NEW.resolved_by_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM review_revision
    WHERE review_revision_id = NEW.resolved_by_review_revision_id
      AND experiment_id = NEW.experiment_id
      AND field_name = NEW.field_name
      AND decision = 'accepted'
 )
BEGIN
    SELECT RAISE(ABORT, 'missing field resolution requires matching experiment and field');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_revision_supersession_matches
BEFORE INSERT ON review_revision
WHEN NEW.supersedes_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM review_revision
    WHERE review_revision_id = NEW.supersedes_review_revision_id
      AND experiment_id = NEW.experiment_id
      AND field_name = NEW.field_name
      AND decision = 'accepted'
 )
BEGIN
    SELECT RAISE(ABORT, 'supersession requires an accepted revision for the same experiment and field');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_revision_retraction_requires_target
BEFORE INSERT ON review_revision
WHEN NEW.decision IN ('rejected', 'superseded')
 AND NEW.supersedes_review_revision_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'retraction requires a superseded review revision');
END;

CREATE TRIGGER IF NOT EXISTS trg_screening_event_excludes_import
AFTER INSERT ON screening_event
WHEN NEW.disposition IN ('exclude', 'screening_only')
BEGIN
    UPDATE paper
    SET screening_status = 'exclude',
        import_status = 'screening_only'
    WHERE paper_id = NEW.paper_id;
END;

INSERT OR IGNORE INTO schema_migration (version, name, applied_at)
VALUES (2, 'review_and_screening_integrity', '2026-08-06T01:00:00Z');
"""

SCREENING_STATE_SCHEMA_SQL = """
DROP TRIGGER IF EXISTS trg_screening_only_not_ready;
DROP TRIGGER IF EXISTS trg_excluded_paper_not_ready_insert;
DROP TRIGGER IF EXISTS trg_excluded_paper_not_ready_update;
DROP TRIGGER IF EXISTS trg_paper_screening_state_insert;
DROP TRIGGER IF EXISTS trg_paper_screening_state_update;

UPDATE paper
SET import_status = 'screening_only'
WHERE screening_status = 'exclude';

CREATE TRIGGER trg_paper_screening_state_insert
BEFORE INSERT ON paper
WHEN (
    NEW.screening_status = 'exclude'
    AND NEW.import_status != 'screening_only'
) OR (
    NEW.screening_status != 'exclude'
    AND NEW.import_status = 'screening_only'
)
BEGIN
    SELECT RAISE(
        ABORT,
        'screening exclusion requires screening_only import status'
    );
END;

CREATE TRIGGER trg_paper_screening_state_update
BEFORE UPDATE OF screening_status, import_status ON paper
WHEN (
    NEW.screening_status = 'exclude'
    AND NEW.import_status != 'screening_only'
) OR (
    NEW.screening_status != 'exclude'
    AND NEW.import_status = 'screening_only'
)
BEGIN
    SELECT RAISE(
        ABORT,
        'screening exclusion requires screening_only import status'
    );
END;

INSERT OR IGNORE INTO schema_migration (version, name, applied_at)
VALUES (3, 'screening_state_and_atomic_migration', '2026-08-06T02:00:00Z');
"""


def _add_missing_columns(
    connection: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
) -> None:
    existing = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if not existing:
        raise sqlite3.OperationalError(f"required legacy table is missing: {table}")
    for column_name, declaration in columns.items():
        if column_name not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column_name} {declaration}"
            )


def _execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute one complete SQL statement at a time without implicit commits."""

    pending: list[str] = []
    for line in script.splitlines(keepends=True):
        pending.append(line)
        statement = "".join(pending)
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            pending.clear()
    if "".join(pending).strip():
        raise sqlite3.OperationalError("incomplete migration SQL statement")


def migrate_database(connection: sqlite3.Connection) -> None:
    """Upgrade a legacy six-table database without replacing existing rows.

    The migration is purely local and additive. Repeated calls converge on the
    same schema and single migration-version record.
    """

    rebuild_cell_type = _experiment_needs_cell_type_rebuild(connection)
    if rebuild_cell_type and connection.in_transaction:
        raise RuntimeError("cell-type migration requires no active transaction")
    if not connection.in_transaction:
        connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise RuntimeError(
            "SQLite foreign-key enforcement must be enabled before migration"
        )
    if rebuild_cell_type:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA legacy_alter_table = ON")
    savepoint = "working_evidence_database_migration"
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        if rebuild_cell_type:
            _migrate_experiment_cell_type(connection)
        _add_missing_columns(connection, "paper", PAPER_COLUMNS)
        _add_missing_columns(connection, "experiment", EXPERIMENT_COLUMNS)
        _execute_sql_script(connection, ADDITIVE_SCHEMA_SQL)
        _add_missing_columns(
            connection,
            "review_revision",
            REVIEW_REVISION_COLUMNS,
        )
        _execute_sql_script(connection, INTEGRITY_SCHEMA_SQL)
        _execute_sql_script(connection, SCREENING_STATE_SCHEMA_SQL)
    except BaseException:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        if rebuild_cell_type:
            connection.execute("PRAGMA legacy_alter_table = OFF")
            connection.execute("PRAGMA foreign_keys = ON")
        raise
    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
    if rebuild_cell_type:
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("foreign-key violations after cell-type migration")


def _experiment_needs_cell_type_rebuild(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'experiment'"
    ).fetchone()
    if row is None:
        return False
    cell_segment = row[0].split("cell_type", 1)[1].split("cell_source", 1)[0]
    return "CHECK" in cell_segment.upper() and "'not_reported'" not in cell_segment


def _migrate_experiment_cell_type(connection: sqlite3.Connection) -> None:
    """Allow explicit unknown/other targets without fabricating a liver cell type."""

    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'experiment'"
    ).fetchone()
    if row is None or not _experiment_needs_cell_type_rebuild(connection):
        return
    old_sql = row[0]
    new_sql, replacements = re.subn(
        r"('hsc')(\s*\))",
        r"\1,\n                'not_reported',\n                'other'\2",
        old_sql,
        count=1,
    )
    if replacements != 1:
        raise RuntimeError("unrecognized experiment cell_type constraint")
    columns = [row[1] for row in connection.execute("PRAGMA table_info(experiment)")]
    quoted = ", ".join(f'"{column}"' for column in columns)
    connection.execute("ALTER TABLE experiment RENAME TO experiment_cell_type_v1")
    connection.execute(new_sql)
    connection.execute(
        f"INSERT INTO experiment ({quoted}) SELECT {quoted} FROM experiment_cell_type_v1"
    )
    connection.execute("DROP TABLE experiment_cell_type_v1")
