from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from src.init_db import initialize_database
from src.database.run_current_corpus_import import run_current_corpus_import


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/database/current_corpus_v1.json"
BUNDLES = ROOT / "data/staging/database/day2_bundles"
PREFLIGHT = ROOT / "reports/database/day2_import_preflight.json"


def _populated_database(tmp_path: Path) -> Path:
    database = tmp_path / "current-corpus.db"
    initialize_database(database)
    summary = run_current_corpus_import(database, MANIFEST, BUNDLES)
    assert all(row["status"] == "committed" for row in summary["dispositions"])
    return database


def test_audit_accepts_complete_current_corpus_fixture(tmp_path: Path) -> None:
    from src.database.audit_current_database import audit_current_database

    database = _populated_database(tmp_path)
    result = audit_current_database(
        database, MANIFEST, BUNDLES, expected_preflight_path=PREFLIGHT
    )

    assert result["schema_version"] == "day2-database-audit/v1"
    assert result["database_kind"] == "explicit_fixture"
    assert result["paid_calls"] == 0
    assert result["passed"] is True
    assert result["checks"]["sqlite_integrity"] == "ok"
    assert result["checks"]["foreign_key_violations"] == []
    assert result["checks"]["orphan_counts"] == {}
    assert result["checks"]["exact_duplicate_natural_keys"] == []
    assert result["checks"]["manifest_dispositions"] == {
        "expected": 14,
        "present": 14,
        "missing": [],
        "unexpected": [],
    }
    assert result["checks"]["manifest_hash_matches"] is True
    assert result["checks"]["bundle_hash_mismatches"] == []
    assert [row["paper_id"] for row in result["papers"]] == [
        row["paper_id"] for row in json.loads(MANIFEST.read_text())["entries"]
    ]
    assert len(result["papers"]) == 14
    gp2 = next(row for row in result["papers"] if row["paper_id"] == "GP-002")
    assert set(gp2) >= {
        "formulations", "arms", "outcomes", "evidence", "missing",
        "conflicts", "quarantined", "eligible_arms",
    }
    assert sum(row["evidence"] for row in result["papers"]) == 777
    assert sum(row["missing"] for row in result["papers"]) == 6
    pilot1 = next(row for row in result["papers"] if row["paper_id"] == "PILOT-001")
    assert pilot1["likely_evidence_inaccessible"] is True


def test_audit_detects_semantic_orphan_and_eligibility_inconsistency(
    tmp_path: Path,
) -> None:
    from src.database.audit_current_database import audit_current_database

    database = _populated_database(tmp_path)
    with sqlite3.connect(database) as connection:
        experiment_id = connection.execute(
            "SELECT experiment_id FROM experiment ORDER BY experiment_id LIMIT 1"
        ).fetchone()[0]
        other_paper_id = connection.execute(
            "SELECT paper_id FROM paper WHERE paper_id != "
            "(SELECT paper_id FROM experiment WHERE experiment_id = ?) LIMIT 1",
            (experiment_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE evidence SET paper_id = ? WHERE experiment_id = ?",
            (other_paper_id, experiment_id),
        )
        connection.execute(
            "UPDATE arm_assessment SET nearest_neighbor_eligible = 1, "
            "completeness_status = 'quarantined' WHERE experiment_id = ?",
            (experiment_id,),
        )

    result = audit_current_database(database, MANIFEST, BUNDLES)

    assert result["passed"] is False
    assert result["checks"]["orphan_counts"]["evidence_paper_mismatch"] > 0
    assert result["checks"]["eligibility_inconsistencies"]


def test_audit_detects_foreign_key_coverage_tag_and_bundle_hash_failures(
    tmp_path: Path,
) -> None:
    from src.database.audit_current_database import audit_current_database

    database = _populated_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        experiment_id, paper_id = connection.execute(
            "SELECT experiment_id, paper_id FROM experiment ORDER BY experiment_id LIMIT 1"
        ).fetchone()
        connection.execute(
            "UPDATE experiment SET formulation_id=999999 WHERE experiment_id=?",
            (experiment_id,),
        )
        connection.execute(
            "UPDATE evidence SET experiment_id=NULL WHERE experiment_id=?",
            (experiment_id,),
        )
        connection.execute(
            "DELETE FROM import_review WHERE paper_id=?", (paper_id,)
        )
    fake_preflight = tmp_path / "preflight.json"
    payload = json.loads(PREFLIGHT.read_text())
    payload["bundles"][0]["sha256"] = "0" * 64
    fake_preflight.write_text(json.dumps(payload))

    result = audit_current_database(
        database, MANIFEST, BUNDLES, expected_preflight_path=fake_preflight
    )

    assert result["passed"] is False
    assert result["checks"]["foreign_key_violations"]
    assert experiment_id in result["checks"]["evidence_coverage"]["arms_without_evidence"]
    assert experiment_id in result["checks"]["review_tag_gaps"]
    assert result["checks"]["bundle_hash_mismatches"][0]["paper_id"] == "GP-002"


def test_render_report_requires_explicit_paths_and_labels_fixture(
    tmp_path: Path,
) -> None:
    from src.database.audit_current_database import (
        audit_current_database,
        render_audit_report,
    )

    database = _populated_database(tmp_path)
    result = audit_current_database(database, MANIFEST, BUNDLES)
    report = tmp_path / "audit.md"
    render_audit_report(result, report)

    text = report.read_text()
    assert "Temporary fixture audit" in text
    assert "No paid calls were authorized or made" in text
    assert "| GP-001 |" in text
    assert str(database.resolve()) in text


def test_selective_call_preflight_is_zero_call_and_only_for_inaccessible_evidence(
    tmp_path: Path,
) -> None:
    from src.database.audit_current_database import build_selective_call_preflight

    audit = {
        "papers": [
            {
                "paper_id": "PILOT-001",
                "likely_evidence_inaccessible": True,
                "inaccessible_reason": "Source pages were not retained locally.",
            },
            {"paper_id": "GP-002", "likely_evidence_inaccessible": False},
        ]
    }
    target = tmp_path / "selective.json"
    preflight = build_selective_call_preflight(audit, target)

    assert preflight["paid_calls_authorized"] == 0
    assert preflight["provider_requests"] == []
    assert preflight["papers"] == [
        {
            "paper_id": "PILOT-001",
            "reason": "Source pages were not retained locally.",
        }
    ]
    assert json.loads(target.read_text()) == preflight
