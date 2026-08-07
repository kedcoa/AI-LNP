from __future__ import annotations

import sqlite3

from src.database.deduplicate_science import deduplicate_science
from src.init_db import initialize_database


def test_component_deduplication_keeps_source_occurrence_count(tmp_path) -> None:
    database = initialize_database(tmp_path / "dedup.db")
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys=ON")
    paper_id = connection.execute(
        "INSERT INTO paper (source_paper_id,title,source_type,retrieval_date,import_status) "
        "VALUES ('P1','P1','test','2026-08-07','needs_review')"
    ).lastrowid
    formulation_id = connection.execute(
        "INSERT INTO formulation (paper_id,formulation_name) VALUES (?, 'LNP')",
        (paper_id,),
    ).lastrowid
    for _ in range(3):
        connection.execute(
            "INSERT INTO chemical_component "
            "(formulation_id,component_name_reported,component_role,amount_value,amount_unit) "
            "VALUES (?, 'DSPC', 'helper_lipid', 10, 'mol%')",
            (formulation_id,),
        )
    connection.commit()

    result = deduplicate_science(connection)

    assert result.canonical_component_count == 1
    assert result.source_occurrence_count == 3
    assert connection.execute(
        "SELECT count(*) FROM chemical_component"
    ).fetchone() == (1,)
