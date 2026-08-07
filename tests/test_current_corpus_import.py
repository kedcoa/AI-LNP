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
        assert all(nearest == 0 and comet == 0 for _, _, nearest, comet, _ in unknown_arms)
        assert all(
            status in {"complete", "incomplete"} and reason is None
            for cell, status, _, _, reason in unknown_arms
            if cell == "not_reported"
        )
        assert all(
            reason != "Target cell needs automatic resolution"
            for cell, _, _, _, reason in unknown_arms
            if cell == "other"
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


def test_lossless_rebuild_is_source_complete_and_reproducible(tmp_path: Path) -> None:
    module = _module()
    first = module.rebuild_database(
        tmp_path / "one.db", MANIFEST, BUNDLES, corpus_root=ROOT
    )
    second = module.rebuild_database(
        tmp_path / "two.db", MANIFEST, BUNDLES, corpus_root=ROOT
    )

    assert first.scientific_content_sha256 == second.scientific_content_sha256
    assert first.silent_fact_omissions == 0
    assert first.silent_evidence_omissions == 0
    assert first.source_fact_count > 0
    with sqlite3.connect(tmp_path / "one.db") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute(
            "SELECT lnp_molar_ratio FROM lnp_formulation_wide "
            "WHERE lnp_name='αCD163/LNP-FAPCAR'"
        ).fetchone() == ("45:30:23.5:1.5",)


def test_lossless_rebuild_projects_shared_gp002_and_gp004_context(
    tmp_path: Path,
) -> None:
    module = _module()
    database = tmp_path / "shared-context.db"
    module.rebuild_database(database, MANIFEST, BUNDLES, corpus_root=ROOT)

    with sqlite3.connect(database) as connection:
        gp002 = connection.execute(
            """
            SELECT experiment_id,target_or_recipient_organ,
                   observed_transfected_cell,route,timepoint,timepoint_unit
            FROM experiment JOIN paper USING(paper_id)
            WHERE source_paper_id='GP-002'
            ORDER BY experiment_id
            """
        ).fetchall()
        gp004 = connection.execute(
            """
            SELECT experiment_id,target_or_recipient_organ,payload_name,
                   timepoint,timepoint_unit,assay
            FROM experiment JOIN paper USING(paper_id)
            WHERE source_paper_id='GP-004'
            ORDER BY experiment_id
            """
        ).fetchall()

    assert len(gp002) == 6
    assert all(row[1] and "liver" in row[1].casefold() for row in gp002)
    assert all(row[2] and "hepatocyte" in row[2].casefold() for row in gp002)
    assert all(row[3] == "intravenous tail-vein injection" for row in gp002)
    assert gp002[1][4:6] == (24.0, "hours")
    assert gp002[3][4:6] == (14.0, "hours")

    assert len(gp004) == 4
    assert all(row[1] and "liver" in row[1].casefold() for row in gp004)
    assert gp004[0][3:5] == (5.0, "hours; also days 1, 2, 3, 6, and 8")
    assert gp004[2][2] == "HGF mRNA + EGF mRNA"
    assert "Oil Red O" in gp004[2][5]


def test_lossless_rebuild_projects_existing_pilot_outcomes(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "pilot-outcomes.db"
    module.rebuild_database(database, MANIFEST, BUNDLES, corpus_root=ROOT)

    with sqlite3.connect(database) as connection:
        counts = dict(connection.execute(
            """
            SELECT source_paper_id,count(outcome_id)
            FROM paper JOIN experiment USING(paper_id)
            LEFT JOIN outcome USING(experiment_id)
            WHERE source_paper_id LIKE 'PILOT-%'
            GROUP BY source_paper_id
            """
        ))

    assert counts == {"PILOT-001": 11, "PILOT-002": 18, "PILOT-003": 14}


def test_np002_validated_evidence_is_usable_only_when_mandatory_fields_exist(
    tmp_path: Path,
) -> None:
    module = _module()
    database = tmp_path / "np002.db"
    module.rebuild_database(database, MANIFEST, BUNDLES, corpus_root=ROOT)

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT a.completeness_status,a.verification_status,
                   a.nearest_neighbor_eligible,a.comet_eligible
            FROM arm_assessment a JOIN experiment e USING(experiment_id)
            JOIN paper p USING(paper_id)
            WHERE p.source_paper_id='NP-002'
            ORDER BY e.experiment_id
            """
        ).fetchall()

    assert len(rows) == 6
    assert all(status != "quarantined" for status, _, _, _ in rows)
    assert all(verification == "automatically_validated" for _, verification, _, _ in rows)
    assert sum(nearest for _, _, nearest, _ in rows) == 6
    assert sum(status == "complete" for status, _, _, _ in rows) == 6
    assert all(comet == 0 for _, _, _, comet in rows)


def test_descriptive_recipient_labels_do_not_force_human_review(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "recipient-labels.db"
    module.rebuild_database(database, MANIFEST, BUNDLES, corpus_root=ROOT)

    with sqlite3.connect(database) as connection:
        false_reviews = connection.execute(
            "SELECT count(*) FROM import_review "
            "WHERE reason_code='target_cell_automatic_resolution'"
        ).fetchone()[0]
        quarantined = connection.execute(
            """
            SELECT count(*)
            FROM arm_assessment a JOIN experiment e USING(experiment_id)
            JOIN paper p USING(paper_id)
            WHERE p.source_paper_id IN ('GP-005','PILOT-001','PILOT-002','PILOT-003')
              AND a.quarantine_reason='Target cell needs automatic resolution'
            """
        ).fetchone()[0]

    assert false_reviews == 0
    assert quarantined == 0


def test_repaired_corpus_rows_keep_shared_context_and_real_readiness(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "shared-invariants.db"
    module.rebuild_database(database, MANIFEST, BUNDLES, corpus_root=ROOT)

    with sqlite3.connect(database) as connection:
        gp005 = connection.execute(
            """
            SELECT f.formulation_name,a.completeness_status,
                   a.nearest_neighbor_eligible,count(o.outcome_id)
            FROM experiment e JOIN paper p USING(paper_id)
            JOIN formulation f USING(formulation_id)
            JOIN arm_assessment a USING(experiment_id)
            LEFT JOIN outcome o USING(experiment_id)
            WHERE p.source_paper_id='GP-005'
            GROUP BY e.experiment_id ORDER BY e.experiment_id
            """
        ).fetchall()
        gp008 = connection.execute(
            """
            SELECT f.formulation_name,e.in_vitro_in_vivo,
                   a.completeness_status,a.nearest_neighbor_eligible,
                   count(o.outcome_id)
            FROM experiment e JOIN paper p USING(paper_id)
            JOIN formulation f USING(formulation_id)
            JOIN arm_assessment a USING(experiment_id)
            LEFT JOIN outcome o USING(experiment_id)
            WHERE p.source_paper_id='GP-008'
            GROUP BY e.experiment_id ORDER BY e.experiment_id
            """
        ).fetchall()
        pilot_ready = dict(connection.execute(
            """
            SELECT p.source_paper_id,sum(a.nearest_neighbor_eligible)
            FROM paper p JOIN experiment e USING(paper_id)
            JOIN arm_assessment a USING(experiment_id)
            WHERE p.source_paper_id LIKE 'PILOT-%'
            GROUP BY p.source_paper_id
            """
        ))

    assert len(gp005) == 8
    assert {row[0] for row in gp005} >= {"LNP3", "LNP4", "LNP5", "LNP6", "LNP7", "LNP16", "LNP17"}
    assert all(row[1:] == ("complete", 1, row[3]) and row[3] > 0 for row in gp005)
    luc = next(row for row in gp008 if row[0] == "αCD163/LNP-Luc")
    zsgreen = next(row for row in gp008 if row[0] == "αCD163/LNP-ZsGreen")
    assert luc[1:] == ("in_vivo", "complete", 1, 1)
    assert zsgreen[1:] == ("in_vivo", "complete", 1, 1)
    assert pilot_ready == {"PILOT-001": 5, "PILOT-002": 2, "PILOT-003": 4}


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
    with pytest.raises(module.CurrentCorpusImportError) as captured:
        module.run_current_corpus_import(database, MANIFEST, BUNDLES)
    summary = captured.value.summary

    failed = [row for row in summary["dispositions"] if row["paper_id"] == "GP-004"]
    assert failed == [{"paper_id": "GP-004", "status": "rolled_back", "error": "forced paper failure"}]
    assert captured.value.failed_paper_ids == ("GP-004",)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM paper WHERE title = 'must rollback'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM paper WHERE source_paper_id = 'GP-005'"
        ).fetchone()[0] == 1


def test_failed_rerun_raises_even_when_prior_database_contains_that_paper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    database = _new_database(tmp_path)
    module.run_current_corpus_import(database, MANIFEST, BUNDLES)
    real_import = module.import_bundle

    def fail_existing(connection, bundle):
        if bundle.paper.source_paper_id == "GP-004":
            raise RuntimeError("forced stale-paper failure")
        return real_import(connection, bundle)

    monkeypatch.setattr(module, "import_bundle", fail_existing)
    with pytest.raises(module.CurrentCorpusImportError) as captured:
        module.run_current_corpus_import(database, MANIFEST, BUNDLES)

    assert captured.value.failed_paper_ids == ("GP-004",)
    failed = [
        row for row in captured.value.summary["dispositions"]
        if row["paper_id"] == "GP-004"
    ]
    assert failed[0]["status"] == "rolled_back"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM paper WHERE source_paper_id='GP-004'"
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
    assert report["expected_counts"]["field_evidence_references"] == 672
    assert "field_evidence_links" not in report["expected_counts"]
    assert report_path.exists()
