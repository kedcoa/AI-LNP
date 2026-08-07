from __future__ import annotations

import sqlite3

from src.database.rescreen_target_scope import rescreen_paper
from src.init_db import initialize_database


def _fixture_connection(tmp_path) -> sqlite3.Connection:
    path = tmp_path / "rescreen.db"
    initialize_database(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    paper_id = connection.execute(
        """INSERT INTO paper (
               source_paper_id,title,source_type,retrieval_date,
               screening_status,import_status
           ) VALUES ('GP-002','fixture','pdf','2026-08-07','include','needs_review')"""
    ).lastrowid
    formulation_id = connection.execute(
        "INSERT INTO formulation (paper_id,formulation_name) VALUES (?,'LNP')",
        (paper_id,),
    ).lastrowid
    experiment_id = connection.execute(
        """INSERT INTO experiment (
               paper_id,formulation_id,cell_type,tissue_or_organ,payload_name
           ) VALUES (?,?,'hepatocyte','liver','eGFP mRNA')""",
        (paper_id, formulation_id),
    ).lastrowid
    for field_name, quote in (
        ("tissue_or_organ", "delivery of mRNA to the liver"),
        ("endpoint_name", "Transfection of hepatocytes was widespread in most livers."),
    ):
        connection.execute(
            """INSERT INTO evidence (
                   paper_id,experiment_id,field_name,evidence_text,
                   evidence_location_type,extraction_method,
                   extraction_confidence,evidence_review_status
               ) VALUES (?,?,?,?,'results','text_extraction','high',
                         'automatically_validated')""",
            (paper_id, experiment_id, field_name, quote),
        )
    connection.commit()
    return connection


def test_gp002_observation_is_separate_from_liver_destination(tmp_path) -> None:
    connection = _fixture_connection(tmp_path)
    try:
        result = rescreen_paper(connection, "GP-002")
    finally:
        connection.close()

    assert any(
        row.target_or_recipient_organ == "liver" for row in result.candidates
    )
    assert any(
        row.observed_transfected_cell == "hepatocyte"
        for row in result.candidates
    )
    assert not any(
        row.intended_target_cell == "hepatocyte" for row in result.candidates
    )


def test_multi_cell_observation_is_not_forced_onto_one_arm(tmp_path) -> None:
    connection = _fixture_connection(tmp_path)
    try:
        experiment_id = connection.execute(
            "SELECT experiment_id FROM experiment"
        ).fetchone()[0]
        paper_id = connection.execute("SELECT paper_id FROM paper").fetchone()[0]
        connection.execute(
            """INSERT INTO evidence (
                   paper_id,experiment_id,field_name,evidence_text,
                   evidence_location_type,extraction_method,
                   extraction_confidence,evidence_review_status
               ) VALUES (?,?,?,'Uptake occurred in hepatocytes and Kupffer cells.',
                         'results','text_extraction','high','automatically_validated')""",
            (paper_id, experiment_id, "cell_type"),
        )
        result = rescreen_paper(connection, "GP-002")
    finally:
        connection.close()

    multi = [row for row in result.unresolved if row.evidence_text.startswith("Uptake")]
    assert len(multi) == 1
    assert multi[0].disposition == "unresolved"
