import json
from pathlib import Path

import pytest

from src.database.build_current_corpus import (
    build_current_corpus_manifest,
    write_day1_reports,
)


ROOT = Path(__file__).resolve().parents[1]
LANE_PATHS = [
    ROOT / "data/manifests/current_corpus_lanes/gp_v1.json",
    ROOT / "data/manifests/current_corpus_lanes/np_v1.json",
    ROOT / "data/manifests/current_corpus_lanes/pilot_v1.json",
]
EXPECTED_PAPER_IDS = [
    *(f"GP-{index:03d}" for index in range(1, 10)),
    "NP-001",
    "NP-002",
    "PILOT-001",
    "PILOT-002",
    "PILOT-003",
]


def test_builds_canonical_manifest_with_required_day1_counts(tmp_path: Path) -> None:
    output = tmp_path / "current_corpus_v1.json"

    manifest = build_current_corpus_manifest(ROOT, LANE_PATHS, output)

    assert [entry["paper_id"] for entry in manifest["entries"]] == EXPECTED_PAPER_IDS
    assert manifest["summary"] == {
        "total_papers": 14,
        "import_candidates": 11,
        "screening_only": 3,
        "selected_artifacts": 7,
        "explicit_unresolved_reasons": 4,
        "import_status_counts": {
            "blocked": 3,
            "needs_review": 8,
            "screening_only": 3,
        },
        "rerun_status_counts": {
            "blocked_pending_access": 3,
            "none": 4,
            "selective": 7,
        },
        "paid_api_calls": 0,
    }
    assert json.loads(output.read_text(encoding="utf-8")) == manifest


def test_manifest_records_local_hashes_without_selecting_raw_provider_data(
    tmp_path: Path,
) -> None:
    manifest = build_current_corpus_manifest(
        ROOT, reversed(LANE_PATHS), tmp_path / "manifest.json"
    )

    assert [lane["path"] for lane in manifest["source_lanes"]] == [
        "data/manifests/current_corpus_lanes/gp_v1.json",
        "data/manifests/current_corpus_lanes/np_v1.json",
        "data/manifests/current_corpus_lanes/pilot_v1.json",
    ]
    assert all(len(lane["sha256"]) == 64 for lane in manifest["source_lanes"])
    assert len(manifest["selected_artifacts"]) == 7
    assert all(
        len(artifact["sha256"]) == 64
        and artifact["rationale"].strip()
        and artifact["pipeline_name"].strip()
        and "pipeline_version" in artifact
        and "raw" not in artifact["path"].casefold()
        and "provider" not in artifact["path"].casefold()
        for artifact in manifest["selected_artifacts"]
    )


def test_canonical_entries_preserve_complete_lane_inventory(
    tmp_path: Path,
) -> None:
    manifest = build_current_corpus_manifest(
        ROOT, LANE_PATHS, tmp_path / "manifest.json"
    )

    entries = manifest["entries"]
    assert all(entry["pmcid"] is not None for entry in entries)
    assert all(entry["publication_metadata"] for entry in entries)
    assert all(entry["source_access_records"] for entry in entries)
    assert all(entry["metadata_provenance"] for entry in entries)
    assert all(entry["last_checked"] == "2026-08-06" for entry in entries)
    assert all(entry["strongest_artifact_rationale"].strip() for entry in entries)
    assert all("candidate_artifacts" in entry for entry in entries)
    assert all("pipeline_lineage" in entry for entry in entries)


def test_manifest_registers_all_fact_and_evidence_contributors(
    tmp_path: Path,
) -> None:
    manifest = build_current_corpus_manifest(
        ROOT, LANE_PATHS, tmp_path / "manifest.json"
    )
    entries = {entry["paper_id"]: entry for entry in manifest["entries"]}

    gp2_paths = {
        artifact["path"] for artifact in entries["GP-002"]["contributing_artifacts"]
    }
    assert entries["GP-002"]["import_artifact"] in gp2_paths
    assert "data/staging/extraction/g1_fulltext_rag/GP-002/source_clauses.json" in gp2_paths
    assert "data/staging/rag/compact_packets_v1/GP-002.json" in gp2_paths

    np2_fact_sources = [
        artifact
        for artifact in entries["NP-002"]["contributing_artifacts"]
        if artifact["contributes_facts"]
    ]
    assert len(np2_fact_sources) == 3
    assert all(
        artifact["role"] == "contributing_extraction"
        for artifact in np2_fact_sources
    )

    pilot_fact_sources = [
        artifact
        for artifact in entries["PILOT-001"]["contributing_artifacts"]
        if artifact["contributes_facts"]
    ]
    assert [artifact["path"] for artifact in pilot_fact_sources] == [
        "reports/extraction/application_pilot_final.json"
    ]
    assert pilot_fact_sources[0]["validation_status"] == "formal_acceptance_failed"

    coverage = manifest["artifact_coverage"]
    assert len(coverage) == 14
    assert coverage["GP-002"]["primary_artifact"] == entries["GP-002"][
        "import_artifact"
    ]


def test_every_import_candidate_has_an_artifact_or_explicit_reason(
    tmp_path: Path,
) -> None:
    manifest = build_current_corpus_manifest(
        ROOT, LANE_PATHS, tmp_path / "manifest.json"
    )

    import_candidates = [
        entry
        for entry in manifest["entries"]
        if entry["import_status"] != "screening_only"
    ]
    assert len(import_candidates) == 11
    assert all(
        entry["import_artifact"] or (entry["rerun_reason"] or "").strip()
        for entry in import_candidates
    )


def test_conflicting_cross_lane_claims_are_rejected(tmp_path: Path) -> None:
    conflicting_lane = tmp_path / "conflicting.json"
    conflicting_entry = json.loads(LANE_PATHS[0].read_text(encoding="utf-8"))[
        "entries"
    ][0]
    conflicting_entry.update(
        {
            "import_status": "blocked",
            "rerun_status": "blocked_pending_access",
            "rerun_reason": "Conflicting route from a second lane.",
        }
    )
    conflicting_lane.write_text(
        json.dumps({"entries": [conflicting_entry]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="conflicting lane claims.*GP-001"):
        build_current_corpus_manifest(
            ROOT,
            [*LANE_PATHS, conflicting_lane],
            tmp_path / "manifest.json",
        )


def test_import_candidate_without_artifact_or_reason_is_rejected(
    tmp_path: Path,
) -> None:
    modified_np = json.loads(LANE_PATHS[1].read_text(encoding="utf-8"))
    modified_np["entries"][1]["rerun_status"] = "none"
    modified_np["entries"][1]["rerun_reason"] = None
    modified_lane = tmp_path / "np_without_reason.json"
    modified_lane.write_text(json.dumps(modified_np), encoding="utf-8")

    with pytest.raises(ValueError, match="NP-002.*artifact or explicit reason"):
        build_current_corpus_manifest(
            ROOT,
            [LANE_PATHS[0], modified_lane, LANE_PATHS[2]],
            tmp_path / "manifest.json",
        )


def test_report_generation_is_idempotent_and_does_not_append_duplicates(
    tmp_path: Path,
) -> None:
    manifest = build_current_corpus_manifest(
        ROOT, LANE_PATHS, tmp_path / "manifest.json"
    )

    json_report, markdown_report = write_day1_reports(manifest, tmp_path / "reports")
    first_json = json_report.read_bytes()
    first_markdown = markdown_report.read_bytes()
    write_day1_reports(manifest, tmp_path / "reports")

    assert json_report.read_bytes() == first_json
    assert markdown_report.read_bytes() == first_markdown
    assert first_markdown.count(b"# Day 1 current-corpus inventory") == 1
    assert b"Paid/API/LLM calls recorded: **0**" in first_markdown
