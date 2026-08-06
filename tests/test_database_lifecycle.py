from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from src.database import database_lifecycle
from src.database.database_lifecycle import (
    backup_and_migrate_authoritative_database,
    backup_database,
    migrate_authoritative_database,
    preflight_authoritative_database,
)


SCIENTIFIC_TABLES = (
    "paper",
    "formulation",
    "chemical_component",
    "experiment",
    "outcome",
    "evidence",
)


def _create_empty_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
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
            """
        )
        connection.commit()
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preflight_rejects_a_missing_authoritative_database(tmp_path: Path) -> None:
    missing_database = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match="authoritative database"):
        preflight_authoritative_database(missing_database)


@pytest.mark.parametrize("table", SCIENTIFIC_TABLES)
def test_preflight_rejects_a_nonempty_scientific_table(
    tmp_path: Path, table: str
) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        statements = {
            "paper": """
                INSERT INTO paper (paper_id, title, source_type, retrieval_date)
                VALUES (1, 'test paper', 'fixture', '2026-08-06')
            """,
            "formulation": """
                INSERT INTO formulation (formulation_id, paper_id, formulation_name)
                VALUES (1, 999, 'test formulation')
            """,
            "chemical_component": """
                INSERT INTO chemical_component (
                    component_id, formulation_id, component_name_reported, component_role
                ) VALUES (1, 999, 'test component', 'lipid')
            """,
            "experiment": """
                INSERT INTO experiment (
                    experiment_id, paper_id, formulation_id, cell_type
                ) VALUES (1, 999, 999, 'test cell')
            """,
            "outcome": """
                INSERT INTO outcome (
                    outcome_id, experiment_id, endpoint_family, endpoint_name, value_status
                ) VALUES (1, 999, 'expression', 'test endpoint', 'reported')
            """,
            "evidence": """
                INSERT INTO evidence (
                    evidence_id, paper_id, field_name, evidence_text,
                    evidence_location_type, extraction_method, extraction_confidence
                ) VALUES (1, 999, 'test field', 'test evidence', 'text', 'fixture', 'high')
            """,
        }
        connection.execute(statements[table])
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match=f"{table}=1"):
        preflight_authoritative_database(database_path)


def test_preflight_records_original_sha_and_enables_foreign_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)

    result = preflight_authoritative_database(database_path)

    assert result.database_path == database_path.resolve()
    assert result.original_sha256 == _sha256(database_path)
    assert result.scientific_row_counts == {
        "paper": 0,
        "formulation": 0,
        "chemical_component": 0,
        "experiment": 0,
        "outcome": 0,
        "evidence": 0,
    }
    assert result.foreign_keys_enabled is True


def test_preflight_rejects_foreign_key_violations(tmp_path: Path) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE import_audit (
                import_audit_id INTEGER PRIMARY KEY,
                paper_id INTEGER NOT NULL REFERENCES paper(paper_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO import_audit (import_audit_id, paper_id) VALUES (1, 999)
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match="foreign-key violations"):
        preflight_authoritative_database(database_path)


def test_backup_is_timestamped_outside_database_location_and_is_valid(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "database" / "lnp_evidence.db"
    database_path.parent.mkdir()
    _create_empty_legacy_database(database_path)
    backup_directory = tmp_path / "excluded-backups"

    backup_path = backup_database(database_path, backup_directory)

    assert backup_path.parent == backup_directory.resolve()
    assert backup_path.name.startswith("lnp_evidence-pre-day2-")
    assert backup_path.suffix == ".db"
    assert backup_path != database_path
    backup = sqlite3.connect(backup_path)
    try:
        assert backup.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert backup.execute("SELECT COUNT(*) FROM paper").fetchone() == (0,)
    finally:
        backup.close()


def test_backup_includes_committed_wal_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    source = sqlite3.connect(database_path)
    try:
        assert source.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        source.execute(
            """
            INSERT INTO paper (paper_id, title, source_type, retrieval_date)
            VALUES (1, 'WAL paper', 'fixture', '2026-08-06')
            """
        )
        source.commit()
        assert database_path.with_name(f"{database_path.name}-wal").is_file()

        backup_path = backup_database(database_path, tmp_path / "excluded-backups")
    finally:
        source.close()

    backup = sqlite3.connect(backup_path)
    try:
        assert backup.execute("SELECT title FROM paper").fetchall() == [("WAL paper",)]
    finally:
        backup.close()


@pytest.mark.parametrize("directory_name", ("data/backups", ".git/backups"))
def test_backup_rejects_destinations_inside_a_repository(
    tmp_path: Path, directory_name: str
) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)

    with pytest.raises(ValueError, match="outside the repository"):
        backup_database(database_path, repository / directory_name)

    assert not (repository / directory_name).exists()


def test_backup_never_overwrites_an_existing_timestamped_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    backup_directory = tmp_path / "excluded-backups"
    monkeypatch.setattr(
        database_lifecycle, "_backup_timestamp", lambda: "20260806T000000Z"
    )
    first_backup = backup_database(database_path, backup_directory)
    original_contents = first_backup.read_bytes()

    with pytest.raises(FileExistsError, match="backup already exists"):
        backup_database(database_path, backup_directory)

    assert first_backup.read_bytes() == original_contents


def test_backup_removes_reserved_artifact_when_source_open_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    backup_directory = tmp_path / "excluded-backups"

    def fail_source_open(path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError(f"cannot open source: {path}")

    monkeypatch.setattr(
        database_lifecycle, "_read_only_connection", fail_source_open
    )

    with pytest.raises(sqlite3.OperationalError, match="cannot open source"):
        backup_database(database_path, backup_directory)

    assert list(backup_directory.glob("*.db")) == []


def test_backup_closes_source_and_removes_artifact_when_destination_open_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    backup_directory = tmp_path / "excluded-backups"
    source = sqlite3.connect(
        f"{database_path.resolve().as_uri()}?mode=ro", uri=True
    )

    def fail_destination_open(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("cannot open destination")

    monkeypatch.setattr(
        database_lifecycle, "_read_only_connection", lambda path: source
    )
    monkeypatch.setattr(database_lifecycle.sqlite3, "connect", fail_destination_open)

    try:
        with pytest.raises(sqlite3.OperationalError, match="cannot open destination"):
            backup_database(database_path, backup_directory)

        try:
            source.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            source_closed = True
        else:
            source_closed = False

        assert source_closed is True
        assert list(backup_directory.glob("*.db")) == []
    finally:
        source.close()


def test_migration_runs_against_the_preflighted_database_and_verifies_integrity(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    original_hash = _sha256(database_path)

    result = migrate_authoritative_database(database_path)

    assert result.preflight.original_sha256 == original_hash
    assert result.migration_versions == (1, 2, 3)
    assert result.foreign_keys_enabled is True
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT version FROM schema_migration ORDER BY version"
        ).fetchall() == [(1,), (2,), (3,)]
    finally:
        connection.close()


def test_composed_lifecycle_binds_preflight_backup_and_migration_digests(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    original_sha256 = _sha256(database_path)

    result = backup_and_migrate_authoritative_database(
        database_path, tmp_path / "excluded-backups"
    )

    assert result.preflight.original_sha256 == original_sha256
    assert result.backup_path.is_file()
    assert result.backup_sha256 == _sha256(result.backup_path)
    assert result.source_state_sha256_before_migration == (
        result.preflight.source_state_sha256
    )
    assert result.migration.migration_versions == (1, 2, 3)


def test_composed_lifecycle_refuses_to_migrate_a_source_changed_after_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "lnp_evidence.db"
    _create_empty_legacy_database(database_path)
    real_backup = backup_database
    changed_source_connections: list[sqlite3.Connection] = []

    def backup_then_change_source(path: str | Path, backup_dir: str | Path) -> Path:
        backup_path = real_backup(path, backup_dir)
        connection = sqlite3.connect(path)
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        changed_source_connections.append(connection)
        return backup_path

    monkeypatch.setattr(
        database_lifecycle, "backup_database", backup_then_change_source
    )

    try:
        with pytest.raises(RuntimeError, match="changed since preflight"):
            backup_and_migrate_authoritative_database(
                database_path, tmp_path / "excluded-backups"
            )
    finally:
        for connection in changed_source_connections:
            connection.close()

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migration'"
        ).fetchall() == []
    finally:
        connection.close()
