"""Safety checks for direct migration of the authoritative SQLite database."""

from __future__ import annotations

import hashlib
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
    wal_sha256: str | None
    source_state_sha256: str
    scientific_row_counts: dict[str, int]
    foreign_keys_enabled: bool


@dataclass(frozen=True)
class DatabaseMigration:
    """Verified result of applying the additive evidence-database migrations."""

    preflight: DatabasePreflight
    migration_versions: tuple[int, ...]
    foreign_keys_enabled: bool


@dataclass(frozen=True)
class DatabaseLifecycleResult:
    """Manifest for one verified backup-and-migration operation."""

    preflight: DatabasePreflight
    backup_path: Path
    backup_sha256: str
    source_state_sha256_before_migration: str
    migration: DatabaseMigration


def snapshot_database(path: str | Path) -> dict[str, object]:
    """Return a JSON-serializable, read-only audit of one SQLite database."""

    database_path = _database_path(path)
    database_sha256 = _sha256(database_path)
    wal_sha256, source_state_sha256 = _wal_and_state_sha256(
        database_path, database_sha256
    )
    connection = _read_only_connection(database_path)
    try:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        integrity = (
            "ok"
            if integrity_rows == [("ok",)]
            else "; ".join(row[0] for row in integrity_rows)
        )
        _verify_foreign_key_integrity(connection)
        counts = _scientific_row_counts(connection)
        available_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        migration_versions = (
            [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migration ORDER BY version"
                )
            ]
            if "schema_migration" in available_tables
            else []
        )
    finally:
        connection.close()

    return {
        "database_path": str(database_path),
        "sha256": database_sha256,
        "wal_sha256": wal_sha256,
        "source_state_sha256": source_state_sha256,
        "integrity": integrity,
        "migration_versions": migration_versions,
        "counts": counts,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
    }


def preflight_authoritative_database(path: str | Path) -> DatabasePreflight:
    """Reject unsafe direct-import targets without changing the database.

    The direct Day 2 import is permitted only for the empty, legacy scientific
    database.  The returned digest is computed before migration so callers can
    record the exact original artifact alongside a backup.
    """

    database_path = _database_path(path)
    original_sha256 = _sha256(database_path)
    wal_sha256, source_state_sha256 = _wal_and_state_sha256(
        database_path, original_sha256
    )
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
        wal_sha256=wal_sha256,
        source_state_sha256=source_state_sha256,
        scientific_row_counts=scientific_row_counts,
        foreign_keys_enabled=foreign_keys_enabled,
    )


def backup_database(path: str | Path, backup_dir: str | Path) -> Path:
    """Create one timestamped SQLite backup without replacing prior backups."""

    database_path = _database_path(path)
    destination_dir = Path(backup_dir).expanduser().resolve()
    _require_non_repository_destination(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    backup_path = destination_dir / (
        f"{database_path.stem}-pre-day2-{_backup_timestamp()}.db"
    )
    try:
        with backup_path.open("xb"):
            pass
    except FileExistsError as error:
        raise FileExistsError(f"backup already exists: {backup_path}") from error

    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    backup_complete = False
    try:
        source = _read_only_connection(database_path)
        destination = sqlite3.connect(backup_path)
        source.backup(destination)
        destination.commit()
        backup_complete = True
    finally:
        try:
            if destination is not None:
                destination.close()
        finally:
            try:
                if source is not None:
                    source.close()
            finally:
                if not backup_complete:
                    backup_path.unlink(missing_ok=True)
    return backup_path


def migrate_authoritative_database(path: str | Path) -> DatabaseMigration:
    """Preflight and migrate the authoritative database, then verify integrity."""

    preflight = preflight_authoritative_database(path)
    connection = sqlite3.connect(preflight.database_path)
    try:
        return _migrate_preflighted_connection(connection, preflight)
    finally:
        connection.close()


def backup_and_migrate_authoritative_database(
    path: str | Path, backup_dir: str | Path
) -> DatabaseLifecycleResult:
    """Back up and migrate only the exact database state that passed preflight.

    ``migrate_database`` exclusively owns its SQLite transaction because a
    legacy CHECK-table rebuild must toggle foreign-key enforcement before that
    transaction begins.  The source digest is therefore revalidated on the
    open local connection immediately before handoff.  This command assumes a
    single local migration writer; concurrent external writers are unsupported.
    """

    preflight = preflight_authoritative_database(path)
    backup_path = backup_database(preflight.database_path, backup_dir)
    backup_sha256 = _sha256(backup_path)
    _verify_backup_database(backup_path)

    connection = sqlite3.connect(preflight.database_path)
    try:
        _enable_and_verify_foreign_keys(connection)
        source_state_sha256 = _database_state_sha256(preflight.database_path)
        if source_state_sha256 != preflight.source_state_sha256:
            raise RuntimeError(
                "authoritative database changed since preflight; migration is refused"
            )
        migration = _migrate_preflighted_connection(connection, preflight)
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

    return DatabaseLifecycleResult(
        preflight=preflight,
        backup_path=backup_path,
        backup_sha256=backup_sha256,
        source_state_sha256_before_migration=source_state_sha256,
        migration=migration,
    )


def _database_path(path: str | Path) -> Path:
    database_path = Path(path).expanduser().resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"authoritative database does not exist: {database_path}")
    return database_path


def _read_only_connection(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)


def _require_non_repository_destination(destination_dir: Path) -> None:
    repository_root = _repository_root(destination_dir)
    if repository_root is not None and destination_dir.is_relative_to(repository_root):
        raise ValueError(
            "backup destination must be outside the repository: "
            f"{destination_dir} is within {repository_root}"
        )


def _repository_root(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _migrate_preflighted_connection(
    connection: sqlite3.Connection, preflight: DatabasePreflight
) -> DatabaseMigration:
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
    return DatabaseMigration(
        preflight=preflight,
        migration_versions=migration_versions,
        foreign_keys_enabled=foreign_keys_enabled,
    )


def _verify_backup_database(backup_path: Path) -> None:
    connection = _read_only_connection(backup_path)
    try:
        _enable_and_verify_foreign_keys(connection)
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError(f"backup integrity check failed: {backup_path}")
        _verify_foreign_key_integrity(connection)
    finally:
        connection.close()


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


def _database_state_sha256(database_path: Path) -> str:
    database_sha256 = _sha256(database_path)
    _, state_sha256 = _wal_and_state_sha256(database_path, database_sha256)
    return state_sha256


def _wal_and_state_sha256(
    database_path: Path, database_sha256: str
) -> tuple[str | None, str]:
    wal_path = database_path.with_name(f"{database_path.name}-wal")
    wal_sha256 = _sha256(wal_path) if wal_path.is_file() else None
    digest = hashlib.sha256()
    digest.update(b"database-sha256:")
    digest.update(database_sha256.encode("ascii"))
    digest.update(b"\nwal-sha256:")
    digest.update((wal_sha256 or "absent").encode("ascii"))
    return wal_sha256, digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
