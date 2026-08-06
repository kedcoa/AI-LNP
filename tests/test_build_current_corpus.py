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
        and "raw" not in artifact["path"].casefold()
        and "provider" not in artifact["path"].casefold()
        for artifact in manifest["selected_artifacts"]
    )


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
    conflicting_lane.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "paper_id": "GP-001",
                        "title": None,
                        "doi": "10.1080/10717544.2026.2682976",
                        "pmid": "42249613",
                        "import_status": "blocked",
                        "rerun_status": "blocked_pending_access",
                        "rerun_reason": "Conflicting route from a second lane.",
                        "import_artifact": None,
                    }
                ]
            }
        ),
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
