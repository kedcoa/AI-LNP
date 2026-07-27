from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "src" / "schema.sql"
DATABASE_PATH = PROJECT_ROOT / "data" / "curated" / "lnp_evidence.db"

EXPERIMENT_TEXT_COLUMNS = {
    "tissue_or_organ": "TEXT",
    "disease_model": "TEXT",
    "payload_encoded_product": "TEXT",
    "payload_molecular_target": "TEXT",
}


def migrate_experiment_columns(connection: sqlite3.Connection) -> None:
    """Add nullable compact-contract fields to an existing database."""

    existing = {
        row[1]
        for row in connection.execute("PRAGMA table_info(experiment)")
    }
    for column_name, column_type in EXPERIMENT_TEXT_COLUMNS.items():
        if column_name not in existing:
            connection.execute(
                f"ALTER TABLE experiment ADD COLUMN {column_name} {column_type}"
            )


def initialize_database(database_path: Path = DATABASE_PATH) -> Path:
    database_path.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(schema_sql)
        migrate_experiment_columns(connection)

        result = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()

        if result != (1,):
            raise RuntimeError("SQLite foreign-key enforcement is disabled.")

    return database_path


if __name__ == "__main__":
    created_path = initialize_database()
    print(f"Database initialized: {created_path}")
