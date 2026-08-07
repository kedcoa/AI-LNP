from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.database.arm_projection_audit import audit_arm_projection


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    graph = root / "data/staging/extraction/g1_fulltext_rag/GP-T01/accepted_graph.json"
    graph.parent.mkdir(parents=True)
    graph.write_text(
        json.dumps(
            {
                "paper_id": "GP-T01",
                "experiments": [
                    {
                        "experiment_id": "GP-T01-E01",
                        "label": "mapped experiment",
                        "boundary_status": "explicit",
                        "boundary_reason": "directly reported",
                    },
                    {
                        "experiment_id": "GP-T01-E02",
                        "label": "unlinked experiment",
                        "boundary_status": "ambiguous",
                        "boundary_reason": "formulation link is unclear",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def _fixture_database(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE paper (
            paper_id INTEGER PRIMARY KEY,
            source_paper_id TEXT NOT NULL UNIQUE
        );
        CREATE TABLE experiment (
            experiment_id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL
        );
        CREATE TABLE import_record_identity (
            import_record_identity_id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            content_json TEXT NOT NULL,
            entity_id INTEGER NOT NULL
        );
        CREATE TABLE import_review (
            import_review_id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL,
            natural_key TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            review_status TEXT NOT NULL,
            notes TEXT
        );
        INSERT INTO paper VALUES (1, 'GP-T01');
        INSERT INTO experiment VALUES (10, 1);
        """
    )
    connection.execute(
        """
        INSERT INTO import_record_identity (
            paper_id, entity_type, content_json, entity_id
        ) VALUES (1, 'experiment', ?, 10)
        """,
        (
            json.dumps(
                {"record": {"record_id": "GP-T01:ARM:GP-T01-E01:FORM-1"}}
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO import_review (
            paper_id, natural_key, reason_code, review_status, notes
        ) VALUES (
            1, 'GP-T01:REV:GP-T01-E02:UNLINKED',
            'experiment_link_unclear', 'incomplete',
            'No evidence-supported formulation edge.'
        )
        """
    )
    connection.commit()
    connection.close()
    return path


def test_every_graph_experiment_has_one_explained_disposition(
    tmp_path: Path,
) -> None:
    report = audit_arm_projection(
        _fixture_root(tmp_path),
        _fixture_database(tmp_path / "projection.db"),
    )

    paper = report["papers"]["GP-T01"]
    assert paper["graph_experiment_count"] == 2
    assert paper["accounted_count"] == 2
    assert paper["unexplained_experiment_ids"] == []
    assert paper["sqlite_arm_count"] == 1
    assert paper["experiments"]["GP-T01-E01"]["disposition"] == "projected"
    assert paper["experiments"]["GP-T01-E02"]["disposition"] == "incomplete"


def test_unexplained_graph_experiment_is_reported(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    database = _fixture_database(tmp_path / "projection.db")
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM import_review")
    connection.commit()
    connection.close()

    report = audit_arm_projection(root, database)

    assert report["papers"]["GP-T01"]["unexplained_experiment_ids"] == [
        "GP-T01-E02"
    ]
    assert report["summary"]["unexplained_experiments"] == 1
