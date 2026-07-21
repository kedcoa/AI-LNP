from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "src" / "schema.sql"
DATABASE_PATH = PROJECT_ROOT / "data" / "curated" / "lnp_evidence.db"


def initialize_database(database_path: Path = DATABASE_PATH) -> Path:
    database_path.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(schema_sql)

        result = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()

        if result != (1,):
            raise RuntimeError("SQLite foreign-key enforcement is disabled.")

    return database_path


if __name__ == "__main__":
    created_path = initialize_database()
    print(f"Database initialized: {created_path}")