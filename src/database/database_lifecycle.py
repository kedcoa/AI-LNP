"""Safety checks for direct migration of the authoritative SQLite database."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.database.migrations import migrate_database


SCIENTIFIC_TABLES = (
    "paper",
    "formulation",
    "chemical_component",
    "experiment",
    "outcome",
    "evidence",
)


@dataclass(frozen=True)
class DatabasePreflight:
    """Immutable record of the database state immediately before migration."""

    database_path: Path
    original_sha256: str
    scientific_row_counts: dict[str, int]
    foreign_keys_enabled: bool


@dataclass(frozen=True)
class DatabaseMigration:
    """Verified result of applying the additive evidence-database migrations."""

    preflight: DatabasePreflight
    migration_versions: tuple[int, ...]
    foreign_keys_enabled: bool


def preflight_authoritative_database(path: str | Path) -> DatabasePreflight:
    """Reject unsafe direct-import targets without changing the database.

    The direct Day 2 import is permitted only for the empty, legacy scientific
    database.  The returned digest is computed before migration so callers can
    record the exact original artifact alongside a backup.
    """

    database_path = _database_path(path)
    original_sha256 = _sha256(database_path)
    connection = _read_only_connection(database_path)
    try:
        foreign_keys_enabled = _enable_and_verify_foreign_keys(connection)
        scientific_row_counts = _scientific_row_counts(connection)
        nonempty_tables = {
            table: count
            for table, count in scientific_row_counts.items()
            if count
        }
        if nonempty_tables:
            rendered_counts = ", ".join(
                f"{table}={count}" for table, count in nonempty_tables.items()
            )
            raise ValueError(
                "authoritative database already contains scientific records: "
                f"{rendered_counts}"
            )
        _verify_foreign_key_integrity(connection)
    finally:
        connection.close()

    return DatabasePreflight(
        database_path=database_path,
        original_sha256=original_sha256,
        scientific_row_counts=scientific_row_counts,
        foreign_keys_enabled=foreign_keys_enabled,
    )


def backup_database(path: str | Path, backup_dir: str | Path) -> Path:
    """Create one timestamped SQLite backup without replacing prior backups."""

    database_path = _database_path(path)
    destination_dir = Path(backup_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    backup_path = destination_dir / (
        f"{database_path.stem}-pre-day2-{_backup_timestamp()}.db"
    )
    try:
        with backup_path.open("xb"):
            pass
    except FileExistsError as error:
        raise FileExistsError(f"backup already exists: {backup_path}") from error

    try:
        shutil.copyfile(database_path, backup_path)
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise
    return backup_path


def migrate_authoritative_database(path: str | Path) -> DatabaseMigration:
    """Preflight and migrate the authoritative database, then verify integrity."""

    preflight = preflight_authoritative_database(path)
    connection = sqlite3.connect(preflight.database_path)
    try:
        foreign_keys_enabled = _enable_and_verify_foreign_keys(connection)
        migrate_database(connection)
        connection.commit()
        _verify_foreign_key_integrity(connection)
        migration_versions = tuple(
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migration ORDER BY version"
            )
        )
    finally:
        connection.close()

    return DatabaseMigration(
        preflight=preflight,
        migration_versions=migration_versions,
        foreign_keys_enabled=foreign_keys_enabled,
    )


def _database_path(path: str | Path) -> Path:
    database_path = Path(path).expanduser().resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"authoritative database does not exist: {database_path}")
    return database_path


def _read_only_connection(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)


def _enable_and_verify_foreign_keys(connection: sqlite3.Connection) -> bool:
    connection.execute("PRAGMA foreign_keys = ON")
    enabled = connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    if not enabled:
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
    return enabled


def _scientific_row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    available_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing_tables = [table for table in SCIENTIFIC_TABLES if table not in available_tables]
    if missing_tables:
        raise ValueError(
            "authoritative database is missing scientific tables: "
            + ", ".join(missing_tables)
        )
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in SCIENTIFIC_TABLES
    }


def _verify_foreign_key_integrity(connection: sqlite3.Connection) -> None:
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise ValueError(f"authoritative database has foreign-key violations: {violations}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
