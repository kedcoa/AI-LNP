from __future__ import annotations

import sqlite3

from src.database.build_rerun_queue import build_rerun_queue
from src.init_db import initialize_database


def test_queue_is_bounded_and_does_not_request_locally_closed_gp008_ratio(tmp_path) -> None:
    database = initialize_database(tmp_path / "queue.db")
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys=ON")
    paper_id = connection.execute(
        "INSERT INTO paper (source_paper_id,title,source_type,retrieval_date,import_status) "
        "VALUES ('GP-008','GP-008','test','2026-08-07','needs_review')"
    ).lastrowid
    connection.execute(
        "INSERT INTO formulation "
        "(paper_id,formulation_name,chemical_formulation_total,lnp_molar_ratio) "
        "VALUES (?, 'αCD163/LNP-FAPCAR', 'ionizable lipid-DSPC-cholesterol-PEG-lipid', '45:30:23.5:1.5')",
        (paper_id,),
    )
    connection.commit()

    queue = build_rerun_queue(connection)

    assert all(item["paper_id"] in {
        "GP-002", "GP-004", "GP-005", "GP-006", "GP-008", "NP-001",
        "NP-002", "PILOT-001", "PILOT-002", "PILOT-003",
    } for item in queue)
    assert not any(
        item["paper_id"] == "GP-008" and "lnp_molar_ratio" in item["fields"]
        for item in queue
    )
