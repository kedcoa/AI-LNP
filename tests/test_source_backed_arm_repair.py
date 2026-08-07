from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.database.source_backed_arm_repair import apply_repair_manifest
from src.database.import_bundle import _IMPORT_SCHEMA
from src.init_db import initialize_database


def _database(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    database = tmp_path / "repair.db"
    initialize_database(database)
    source = tmp_path / "paper.nxml"
    source.write_text(
        "<article><p>Mice received 10 micrograms by intravenous tail-vein "
        "injection. Expression was observed in hepatocytes throughout the "
        "liver after 24 hours.</p></article>",
        encoding="utf-8",
    )
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(_IMPORT_SCHEMA)
    paper_id = int(connection.execute(
        """
        INSERT INTO paper (
            source_paper_id,title,source_type,retrieval_date,
            screening_status,import_status
        ) VALUES ('GP-TEST','Fixture','nxml','2026-08-07','include','needs_review')
        """
    ).lastrowid)
    formulation_id = int(connection.execute(
        "INSERT INTO formulation (paper_id,formulation_name) VALUES (?,'LNP')",
        (paper_id,),
    ).lastrowid)
    connection.execute(
        """
        INSERT INTO experiment (
            experiment_id,paper_id,formulation_id,cell_type,payload_name,
            disease_model
        ) VALUES (101,?,?,'not_reported','eGFP mRNA','fibrosis')
        """,
        (paper_id, formulation_id),
    )
    content = json.dumps(
        {"record": {"record_id": "GP-TEST::arm::stable-X1"}},
        sort_keys=True,
    )
    connection.execute(
        """
        INSERT INTO import_record_identity (
            paper_id,entity_type,natural_key,content_sha256,content_json,entity_id
        ) VALUES (?,'experiment','stable-X1',?,?,101)
        """,
        (paper_id, hashlib.sha256(content.encode()).hexdigest(), content),
    )
    connection.commit()
    return connection, source


def _manifest(source: Path) -> dict[str, object]:
    return {
        "schema_version": "source-backed-arm-repair/v1",
        "repairs": [
            {
                "repair_id": "gp-test-arm-101",
                "paper_id": "GP-TEST",
                "experiment_id": 101,
                "expected": {
                    "payload_name": "eGFP mRNA",
                    "disease_model": "fibrosis",
                },
                "updates": {
                    "target_or_recipient_organ": "liver",
                    "observed_transfected_cell": "hepatocyte",
                    "dose": 10.0,
                    "dose_unit": "micrograms per mouse",
                    "route": "intravenous tail-vein injection",
                    "timepoint": 24.0,
                    "timepoint_unit": "hours",
                },
                "evidence": [
                    {
                        "source_path": str(source),
                        "location": "Methods and Results",
                        "excerpt": (
                            "Mice received 10 micrograms by intravenous tail-vein "
                            "injection. Expression was observed in hepatocytes "
                            "throughout the liver after 24 hours."
                        ),
                        "fields": [
                            "target_or_recipient_organ",
                            "observed_transfected_cell",
                            "dose",
                            "dose_unit",
                            "route",
                            "timepoint",
                            "timepoint_unit",
                        ],
                    }
                ],
            }
        ],
    }


def test_source_backed_repair_updates_fields_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    connection, source = _database(tmp_path)
    try:
        first = apply_repair_manifest(connection, _manifest(source))
        second = apply_repair_manifest(connection, _manifest(source))
        arm = connection.execute(
            """
            SELECT target_or_recipient_organ,observed_transfected_cell,dose,
                   dose_unit,route,timepoint,timepoint_unit
            FROM experiment WHERE experiment_id=101
            """
        ).fetchone()
        counts = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM evidence WHERE experiment_id=101),
              (SELECT count(*) FROM import_field_evidence
                 WHERE entity_type='arm' AND entity_id=101),
              (SELECT count(*) FROM source_fact WHERE paper_id=(
                 SELECT paper_id FROM experiment WHERE experiment_id=101)),
              (SELECT count(*) FROM fact_projection
                 WHERE entity_type='arm' AND entity_id=101)
            """
        ).fetchone()
    finally:
        connection.close()

    assert tuple(arm) == (
        "liver", "hepatocyte", 10.0, "micrograms per mouse",
        "intravenous tail-vein injection", 24.0, "hours",
    )
    assert first.updated_fields == 7
    assert second.updated_fields == 0
    assert tuple(counts) == (1, 7, 7, 7)


def test_source_backed_repair_rejects_unverified_excerpt(tmp_path: Path) -> None:
    connection, source = _database(tmp_path)
    manifest = _manifest(source)
    manifest["repairs"][0]["evidence"][0]["excerpt"] = "This is not in the paper."
    try:
        with pytest.raises(ValueError, match="excerpt was not found"):
            apply_repair_manifest(connection, manifest)
        row = connection.execute(
            "SELECT target_or_recipient_organ FROM experiment WHERE experiment_id=101"
        ).fetchone()
    finally:
        connection.close()

    assert row[0] is None


def test_source_backed_repair_fails_closed_on_wrong_arm_identity(
    tmp_path: Path,
) -> None:
    connection, source = _database(tmp_path)
    manifest = _manifest(source)
    manifest["repairs"][0]["expected"]["payload_name"] = "wrong payload"
    try:
        with pytest.raises(ValueError, match="arm identity mismatch"):
            apply_repair_manifest(connection, manifest)
        row = connection.execute(
            "SELECT target_or_recipient_organ FROM experiment WHERE experiment_id=101"
        ).fetchone()
    finally:
        connection.close()

    assert row[0] is None


def test_source_backed_repair_restores_connection_row_factory(tmp_path: Path) -> None:
    connection, source = _database(tmp_path)
    connection.row_factory = None
    try:
        apply_repair_manifest(connection, _manifest(source))
        observed = connection.row_factory
    finally:
        connection.close()

    assert observed is None


def test_source_backed_repair_resolves_stable_arm_record_id(tmp_path: Path) -> None:
    connection, source = _database(tmp_path)
    manifest = _manifest(source)
    repair = manifest["repairs"][0]
    repair.pop("experiment_id")
    repair["arm_record_id"] = "GP-TEST::arm::stable-X1"
    try:
        result = apply_repair_manifest(connection, manifest)
        row = connection.execute(
            "SELECT target_or_recipient_organ FROM experiment WHERE experiment_id=101"
        ).fetchone()
    finally:
        connection.close()

    assert result.updated_fields == 7
    assert row[0] == "liver"
