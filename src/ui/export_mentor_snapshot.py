"""Export a portable, frozen, read-only mentor evidence snapshot."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Iterator

from src.ui.evidence_browser_service import (
    combined_arm_rows_for_export,
    list_combined_arm_rows,
    summarize_browser_database,
)


ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_readonly_database(path: Path) -> sqlite3.Connection:
    """Open one SQLite database with both URI and pragma write protection."""

    resolved = Path(path).resolve()
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _verify_database(path: Path) -> tuple[str, int]:
    with open_readonly_database(path) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    if foreign_keys:
        raise RuntimeError(
            f"SQLite foreign-key check found {foreign_keys} violation(s)"
        )
    return integrity, foreign_keys


def _runtime_sources() -> Iterator[tuple[Path, Path]]:
    for relative in (
        Path("src/__init__.py"),
        Path("src/ui/__init__.py"),
        Path("src/ui/evidence_browser_app.py"),
        Path("src/ui/evidence_browser_service.py"),
        Path("src/database/__init__.py"),
        Path("src/database/scientific_identity.py"),
    ):
        yield ROOT / relative, relative


def _write_runtime(output_dir: Path) -> None:
    for source, relative in _runtime_sources():
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    paths_module = output_dir / "src/database/paths.py"
    paths_module.write_text(
        '''"""Portable snapshot path constants."""
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMON_CHECKOUT_ROOT = REPOSITORY_ROOT
CANONICAL_AUTHORITATIVE_DATABASE = REPOSITORY_ROOT / "lnp_evidence.db"
''',
        encoding="utf-8",
    )
    shutil.copy2(ROOT / "src/ui/mentor_snapshot_app.py", output_dir / "app.py")


def export_mentor_snapshot(
    database_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Create a verified mentor package and write its summary last."""

    source = Path(database_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Authoritative database is missing: {source}")
    destination = Path(output_dir).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Snapshot output directory is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    integrity, foreign_key_violations = _verify_database(source)
    source_hash = _sha256(source)
    copied_database = destination / "lnp_evidence.db"
    shutil.copy2(source, copied_database)
    copied_hash = _sha256(copied_database)
    if copied_hash != source_hash:
        raise RuntimeError("Snapshot database hash differs from authoritative source")
    copied_integrity, copied_foreign_keys = _verify_database(copied_database)
    if (copied_integrity, copied_foreign_keys) != (
        integrity,
        foreign_key_violations,
    ):
        raise RuntimeError("Snapshot database verification differs from source")

    summary = summarize_browser_database(copied_database)
    arm_rows = list_combined_arm_rows(database_path=copied_database)
    exported_rows = combined_arm_rows_for_export(
        arm_rows,
        include_local_links=False,
    )
    if len(exported_rows) != summary.experimental_arms:
        raise RuntimeError("CSV arm count does not match browser summary")
    csv_path = destination / "combined_experimental_arms.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(exported_rows[0]) if exported_rows else [],
        )
        writer.writeheader()
        writer.writerows(exported_rows)

    _write_runtime(destination)
    (destination / "README.md").write_text(
        """# AI-LNP mentor evidence snapshot

This is a frozen, read-only SQLite and Streamlit export. It contains no editing
controls and does not modify the working research database.

## Run

Install Streamlit in a Python environment, open a terminal in this directory,
and run:

```bash
streamlit run app.py
```

The combined table is also available as `combined_experimental_arms.csv`.
Publisher, DOI, PubMed, and PMC links remain available; local source-file links
are intentionally omitted.
""",
        encoding="utf-8",
    )
    payload: dict[str, object] = {
        "schema_version": "mentor-snapshot/v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "database_sha256": copied_hash,
        "integrity_check": copied_integrity,
        "foreign_key_violations": copied_foreign_keys,
        "csv_rows": len(exported_rows),
        "counts": asdict(summary),
    }
    (destination / "snapshot_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(
        export_mentor_snapshot(args.database, args.output),
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()


__all__ = ["export_mentor_snapshot", "open_readonly_database"]
