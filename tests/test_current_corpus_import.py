from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from src.init_db import initialize_database


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/database/current_corpus_v1.json"
BUNDLES = ROOT / "data/staging/database/day2_bundles"


def _module():
    from src.database import run_current_corpus_import

    return run_current_corpus_import


def _new_database(tmp_path: Path, name: str = "evidence.db") -> Path:
    path = tmp_path / name
    initialize_database(path)
    return path


def _scientific_counts(connection: sqlite3.Connection, paper_id: int) -> tuple[int, ...]:
    return (
        connection.execute(
            "SELECT count(*) FROM formulation WHERE paper_id = ?", (paper_id,)
        ).fetchone()[0],
        connection.execute(
            "SELECT count(*) FROM experiment WHERE paper_id = ?", (paper_id,)
        ).fetchone()[0],
        connection.execute(
            "SELECT count(*) FROM outcome o JOIN experiment e USING (experiment_id) "
            "WHERE e.paper_id = ?", (paper_id,)
        ).fetchone()[0],
        connection.execute(
            "SELECT count(*) FROM evidence WHERE paper_id = ?", (paper_id,)
        ).fetchone()[0],
    )


def _canonical_database_dump(path: Path) -> tuple[str, ...]:
    with sqlite3.connect(path) as connection:
        return tuple(sorted(connection.iterdump()))


def test_current_corpus_import_covers_all_dispositions_and_isolates_screening(
    tmp_path: Path,
) -> None:
    module = _module()
    database = _new_database(tmp_path)

    summary = module.run_current_corpus_import(database, MANIFEST, BUNDLES)

    assert [row["paper_id"] for row in summary["dispositions"]] == [
        "GP-001", "GP-002", "GP-003", "GP-004", "GP-005", "GP-006",
        "GP-007", "GP-008", "GP-009", "NP-001", "NP-002",
        "PILOT-001", "PILOT-002", "PILOT-003",
    ]
    assert len(summary["dispositions"]) == 14
    assert summary["paid_calls"] == 0
    assert all(row["status"] == "committed" for row in summary["dispositions"])

    with sqlite3.connect(database) as connection:
        for source_id in ("GP-001", "GP-003", "GP-009"):
            paper_id = connection.execute(
                "SELECT paper_id FROM paper WHERE source_paper_id = ?", (source_id,)
            ).fetchone()[0]
            assert _scientific_counts(connection, paper_id) == (0, 0, 0, 0)


def test_import_preserves_review_visibility_evidence_and_deterministic_eligibility(
    tmp_path: Path,
) -> None:
    module = _module()
    first = _new_database(tmp_path, "first.db")
    second = _new_database(tmp_path, "second.db")

    first_summary = module.run_current_corpus_import(first, MANIFEST, BUNDLES)
    second_summary = module.run_current_corpus_import(second, MANIFEST, BUNDLES)

    assert first_summary["expected_counts"] == second_summary["expected_counts"]
    assert first_summary["eligibility"] == second_summary["eligibility"]
    with sqlite3.connect(first) as connection:
        assert connection.execute(
            "SELECT count(*) FROM evidence"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT count(*) FROM import_field_evidence"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT count(*) FROM import_review WHERE trim(review_tag) = ''"
        ).fetchone()[0] == 0
        pilot_rows = connection.execute(
            "SELECT source_paper_id, count(e.evidence_id), count(r.import_review_id) "
            "FROM paper p LEFT JOIN evidence e USING (paper_id) "
            "LEFT JOIN import_review r USING (paper_id) "
            "WHERE source_paper_id LIKE 'PILOT-%' GROUP BY source_paper_id"
        ).fetchall()
        assert len(pilot_rows) == 3
        assert all(evidence_count > 0 and review_count > 0 for _, evidence_count, review_count in pilot_rows)
        unknown_arms = connection.execute(
            """
            SELECT e.cell_type, a.completeness_status,
                   a.nearest_neighbor_eligible, a.comet_eligible,
                   a.quarantine_reason
            FROM experiment e JOIN arm_assessment a USING (experiment_id)
            WHERE e.cell_type IN ('not_reported', 'other')
            """
        ).fetchall()
        assert unknown_arms
        assert all(
            status == "quarantined" and nearest == 0 and comet == 0 and reason
            for _, status, nearest, comet, reason in unknown_arms
        )
        hep_g2 = connection.execute(
            """
            SELECT e.cell_type, e.cell_source, a.completeness_status,
                   a.nearest_neighbor_eligible, a.comet_eligible
            FROM experiment e JOIN paper p USING (paper_id)
            JOIN arm_assessment a USING (experiment_id)
            WHERE p.source_paper_id = 'NP-001'
            """
        ).fetchone()
        assert hep_g2 is not None
        assert hep_g2[0] == "other"
        assert "HepG2" in (hep_g2[1] or "")
        assert hep_g2[2:] == ("quarantined", 0, 0)


def test_import_is_ordered_and_idempotent(tmp_path: Path) -> None:
    module = _module()
    database = _new_database(tmp_path)

    first = module.run_current_corpus_import(database, MANIFEST, BUNDLES)
    first_dump = _canonical_database_dump(database)
    second = module.run_current_corpus_import(database, MANIFEST, BUNDLES)
    second_dump = _canonical_database_dump(database)

    assert [row["paper_id"] for row in first["dispositions"]] == [
        row["paper_id"] for row in second["dispositions"]
    ]
    assert sum(row["inserted"] for row in second["dispositions"]) == 0
    assert second["database_counts"] == first["database_counts"]
    assert second["eligibility"] == first["eligibility"]
    assert second_dump == first_dump


def test_failed_paper_rolls_back_without_erasing_other_papers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    database = _new_database(tmp_path)
    real_import = module.import_bundle

    def fail_one(connection, bundle):
        if bundle.paper.source_paper_id == "GP-004":
            connection.execute(
                "INSERT INTO paper (title, source_type, retrieval_date) "
                "VALUES ('must rollback', 'test', '2026-08-06')"
            )
            raise RuntimeError("forced paper failure")
        return real_import(connection, bundle)

    monkeypatch.setattr(module, "import_bundle", fail_one)
    summary = module.run_current_corpus_import(database, MANIFEST, BUNDLES)

    failed = [row for row in summary["dispositions"] if row["paper_id"] == "GP-004"]
    assert failed == [{"paper_id": "GP-004", "status": "rolled_back", "error": "forced paper failure"}]
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM paper WHERE title = 'must rollback'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM paper WHERE source_paper_id = 'GP-005'"
        ).fetchone()[0] == 1


def test_preflight_is_exact_and_read_only(tmp_path: Path) -> None:
    module = _module()
    authoritative = _new_database(tmp_path)
    original_hash = hashlib.sha256(authoritative.read_bytes()).hexdigest()
    report_path = tmp_path / "preflight.json"

    report = module.build_import_preflight(
        authoritative, MANIFEST, BUNDLES, report_path=report_path
    )

    assert report["authoritative_database_sha256"] == original_hash
    assert hashlib.sha256(authoritative.read_bytes()).hexdigest() == original_hash
    assert report["paid_calls"] == 0
    assert not Path(report["backup_target_proposal"]).resolve().is_relative_to(ROOT)
    assert not Path(report["backup_target_proposal"]).exists()
    assert report["paper_order"] == [
        row["paper_id"] for row in json.loads(MANIFEST.read_text())["entries"]
    ]
    assert len(report["bundles"]) == 11
    assert all(len(row["sha256"]) == 64 for row in report["bundles"])
    assert report["expected_counts"]["field_evidence_references"] == sum(
        row["expected_counts"]["field_evidence_references"]
        for row in report["bundles"]
    )
    assert "field_evidence_links" not in report["expected_counts"]
    assert report_path.exists()
