from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3

import pytest

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


def test_audit_recomputes_rules_when_flags_and_results_are_tampered_together(
    tmp_path: Path,
) -> None:
    from src.database.audit_current_database import audit_current_database

    database = _populated_database(tmp_path)
    with sqlite3.connect(database) as connection:
        experiment_id = connection.execute(
            "SELECT experiment_id FROM experiment ORDER BY experiment_id LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE arm_assessment SET nearest_neighbor_eligible=1, comet_eligible=1 "
            "WHERE experiment_id=?", (experiment_id,)
        )
        connection.execute(
            "UPDATE eligibility_result SET eligible=1, reasons_json='[]', "
            "rules_version='forged' WHERE experiment_id=?", (experiment_id,)
        )

    result = audit_current_database(database, MANIFEST, BUNDLES)

    problem = next(
        row for row in result["checks"]["eligibility_inconsistencies"]
        if row["arm_id"] == experiment_id
    )
    assert "rules_version" in " ".join(problem["reasons"])
    assert result["passed"] is False


def test_audit_rejects_manifest_disposition_drift(tmp_path: Path) -> None:
    from src.database.audit_current_database import audit_current_database

    database = _populated_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE paper SET import_status='blocked' WHERE source_paper_id='GP-002'"
        )

    result = audit_current_database(database, MANIFEST, BUNDLES)

    assert result["checks"]["manifest_disposition_mismatches"] == [
        {
            "paper_id": "GP-002",
            "expected_import_status": "needs_review",
            "actual_import_status": "blocked",
            "expected_screening_status": "manual_review",
            "actual_screening_status": "manual_review",
        }
    ]
    assert result["passed"] is False


def test_audit_rejects_polymorphic_entity_ids_with_wrong_ownership(
    tmp_path: Path,
) -> None:
    from src.database.audit_current_database import audit_current_database

    database = _populated_database(tmp_path)
    with sqlite3.connect(database) as connection:
        identity_id = connection.execute(
            "SELECT import_record_identity_id FROM import_record_identity "
            "WHERE entity_type='experiment' ORDER BY 1 LIMIT 1"
        ).fetchone()[0]
        field_link_id = connection.execute(
            "SELECT import_field_evidence_id FROM import_field_evidence "
            "WHERE entity_type='arm' ORDER BY 1 LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE import_record_identity SET entity_id=999999 "
            "WHERE import_record_identity_id=?", (identity_id,)
        )
        connection.execute(
            "UPDATE import_field_evidence SET entity_id=999999 "
            "WHERE import_field_evidence_id=?", (field_link_id,)
        )

    result = audit_current_database(database, MANIFEST, BUNDLES)

    assert result["checks"]["orphan_counts"]["identity_experiment_missing"] == 1
    assert result["checks"]["orphan_counts"]["field_evidence_arm_missing"] == 1
    assert result["passed"] is False


def test_authoritative_label_requires_exact_expected_path(tmp_path: Path) -> None:
    from src.database.audit_current_database import (
        CANONICAL_AUTHORITATIVE_DATABASE,
        audit_current_database,
        validate_database_kind,
    )

    database = _populated_database(tmp_path)
    with pytest.raises(ValueError, match="authoritative database path"):
        audit_current_database(
            database, MANIFEST, BUNDLES, database_kind="authoritative"
        )
    with pytest.raises(TypeError, match="expected_authoritative_path"):
        audit_current_database(
            database, MANIFEST, BUNDLES, database_kind="authoritative",
            expected_authoritative_path=database,
        )
    with pytest.raises(ValueError, match="database_kind"):
        audit_current_database(
            database, MANIFEST, BUNDLES, database_kind="authoratative"
        )
    validate_database_kind(CANONICAL_AUTHORITATIVE_DATABASE, "authoritative")


def test_common_checkout_root_resolves_normal_git_directory(tmp_path: Path) -> None:
    from src.database.audit_current_database import resolve_common_checkout_root

    checkout = tmp_path / "main"
    (checkout / ".git").mkdir(parents=True)

    assert resolve_common_checkout_root(checkout) == checkout.resolve()


def test_common_checkout_root_resolves_realistic_linked_worktree(tmp_path: Path) -> None:
    from src.database.audit_current_database import resolve_common_checkout_root

    main = tmp_path / "main"
    git_dir = main / ".git"
    worktree_git_dir = git_dir / "worktrees/audit"
    worktree_git_dir.mkdir(parents=True)
    (worktree_git_dir / "commondir").write_text("../..\n")
    checkout = main / ".worktrees/audit"
    checkout.mkdir(parents=True)
    (checkout / ".git").write_text(f"gitdir: {worktree_git_dir}\n")

    assert resolve_common_checkout_root(checkout) == main.resolve()


def test_common_checkout_root_fails_closed_on_malformed_metadata(
    tmp_path: Path,
) -> None:
    from src.database.audit_current_database import resolve_common_checkout_root

    checkout = tmp_path / "broken"
    checkout.mkdir()
    (checkout / ".git").write_text("not-a-gitdir\n")

    with pytest.raises(RuntimeError, match="Malformed worktree .git file"):
        resolve_common_checkout_root(checkout)



def test_missing_bundle_is_a_structured_failed_audit_not_an_exception(
    tmp_path: Path,
) -> None:
    from src.database.audit_current_database import audit_current_database

    database = _populated_database(tmp_path)
    incomplete_bundles = tmp_path / "bundles"
    shutil.copytree(BUNDLES, incomplete_bundles)
    (incomplete_bundles / "gp/GP-002.json").unlink()

    result = audit_current_database(
        database, MANIFEST, incomplete_bundles,
        expected_preflight_path=PREFLIGHT,
    )

    assert result["passed"] is False
    assert result["checks"]["bundle_hash_mismatches"] == [
        {
            "paper_id": "GP-002",
            "expected": json.loads(PREFLIGHT.read_text())["bundles"][0]["sha256"],
            "actual": "missing",
        }
    ]
    assert result["checks"]["manifest_disposition_mismatches"] == [
        {
            "paper_id": "GP-002",
            "expected_import_status": "missing_bundle",
            "actual_import_status": "needs_review",
            "expected_screening_status": "missing_bundle",
            "actual_screening_status": "manual_review",
        }
    ]


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
