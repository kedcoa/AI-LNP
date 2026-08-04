from __future__ import annotations

from pathlib import Path

import pytest

from src.extraction.replay_shadow_baseline import (
    assert_gold_blind,
    build_evidence_inventory,
    replay_pilot_paper,
)
from src.extraction.build_shadow_benchmark import build_audit_cases


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT.parent / "np002-selective-vision"
PAPER_IDS = ("PILOT-001", "PILOT-002", "PILOT-003")


def test_replays_all_saved_pilot_artifacts_without_provider_clients():
    replayed = [replay_pilot_paper(paper_id, ARTIFACT_ROOT) for paper_id in PAPER_IDS]

    assert [row["paper_id"] for row in replayed] == list(PAPER_IDS)
    assert sum(len(row["experiments"]) for row in replayed) == 14
    assert all("response" not in row for row in replayed)
    assert all("approval_request" not in row for row in replayed)


def test_evidence_inventory_deduplicates_marks_used_evidence_and_preserves_provenance():
    replayed = replay_pilot_paper("PILOT-001", ARTIFACT_ROOT)

    inventory = build_evidence_inventory(replayed)

    assert len(inventory) == len({row["evidence_id"] for row in inventory})
    used = next(row for row in inventory if row["used_by_merged_records"])
    assert {"source", "page_number", "heading", "table_or_figure", "text"} <= set(used)
    visual = next(row for row in inventory if row["evidence_id"].startswith("V-"))
    assert visual["table_or_figure"] == "Figure 6"
    assert visual["page_number"] == 1
    assert visual["source"] == "PMC9845313.html"


def test_evidence_inventory_rejects_conflicting_duplicate_provenance():
    with pytest.raises(ValueError, match="conflicting duplicate evidence provenance"):
        build_evidence_inventory(
            {
                "evidence_sources": [
                    {
                        "evidence_id": "FPE-1",
                        "text": "same source text",
                        "source": "paper.html",
                        "page_number": 1,
                        "heading": "Results",
                        "table_or_figure": None,
                    },
                    {
                        "evidence_id": "FPE-1",
                        "text": "same source text",
                        "source": "paper.html",
                        "page_number": 2,
                        "heading": "Results",
                        "table_or_figure": None,
                    },
                ]
            }
        )


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "reference_facts",
        "audit_findings",
        "gold_id",
        "benchmark_score",
        "known_miss_prose",
        "human_correction",
    ],
)
def test_gold_blind_payload_rejects_prohibited_keys(forbidden_key):
    with pytest.raises(ValueError, match="gold-blind"):
        assert_gold_blind({"nested": {forbidden_key: "forbidden"}})


@pytest.mark.parametrize(
    "forbidden_value",
    [
        "application_pilot_final.json",
        "scientific_reference_audit",
        "reference_bindings",
        "human_audit_corrections",
        "/data/benchmarks/application_pilot/PILOT-001.json",
    ],
)
def test_gold_blind_payload_rejects_exact_model_visible_marker_families(
    forbidden_value,
):
    with pytest.raises(ValueError, match="forbidden string marker"):
        assert_gold_blind({"instructions": f"Do not expose {forbidden_value}"})


def test_gold_blind_payload_allows_benign_audit_and_reference_language():
    assert_gold_blind(
        {
            "instructions": (
                "Act as a scientific auditor and cite the reference method "
                "described inside this sealed evidence packet."
            )
        }
    )


def test_audit_case_fingerprint_includes_saved_replay_dependencies():
    case = build_audit_cases(ROOT, artifact_root=ARTIFACT_ROOT)[0]

    source_paths = "\n".join(case.source_paths)
    assert "application_pilot_final.json" in source_paths
    assert "validated_maps/PILOT-001.json" in source_paths
    assert "PILOT-001/inventory.json" in source_paths
    assert "downstream_gate/requests/REQ-1.json" in source_paths
    assert "downstream_gate/run/REQ-1/response.json" in source_paths
