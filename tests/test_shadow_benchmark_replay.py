from __future__ import annotations

from pathlib import Path

import pytest

from src.extraction.replay_shadow_baseline import (
    assert_gold_blind,
    build_evidence_inventory,
    replay_pilot_paper,
)


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


@pytest.mark.parametrize("forbidden_key", ["reference_facts", "audit_findings", "gold_id"])
def test_gold_blind_payload_rejects_reference_and_audit_keys(forbidden_key):
    with pytest.raises(ValueError, match="gold-blind"):
        assert_gold_blind({"nested": {forbidden_key: "forbidden"}})
