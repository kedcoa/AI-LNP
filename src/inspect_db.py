from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "curated" / "lnp_evidence.db"


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

        print("Tables:")
        for (table_name,) in tables:
            print(f"- {table_name}")

        print("\nRow counts:")
        for table_name in (
            "paper",
            "formulation",
            "chemical_component",
            "experiment",
            "outcome",
            "evidence",
        ):
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
            print(f"- {table_name}: {count}")


if __name__ == "__main__":
    main()