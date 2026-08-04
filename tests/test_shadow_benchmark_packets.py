from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.extraction.build_shadow_benchmark import (
    build_audit_packets,
    write_audit_packet_manifest,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parent
    / "fixtures/codex_ollama_shadow/audit_packets"
)


@pytest.fixture
def packet_inputs() -> tuple[dict, list[dict]]:
    return (
        json.loads((FIXTURE_ROOT / "replayed.json").read_text(encoding="utf-8")),
        json.loads((FIXTURE_ROOT / "evidence.json").read_text(encoding="utf-8")),
    )


def test_build_audit_packets_includes_shared_paper_facts_with_issued_evidence(packet_inputs):
    replayed, evidence = packet_inputs

    packets = build_audit_packets(replayed, evidence)

    packet = packets[0]

    assert packet["packet_id"] == "PILOT-900:shared-paper"
    assert packet["packet_type"] == "shared_paper"
    assert packet["current_merged_facts"] == replayed["shared_facts"]
    assert packet["issued_ids"]["evidence_ids"] == ["EV-shared"]


def test_build_audit_packets_scopes_each_experiment_to_its_issued_ids(packet_inputs):
    replayed, evidence = packet_inputs

    packets = build_audit_packets(replayed, evidence)

    packet = packets[1]

    assert packet["packet_id"] == "PILOT-900:experiment:EXP-900-1"
    assert packet["packet_type"] == "experiment"
    assert packet["current_merged_facts"] == replayed["experiments"][0]
    assert packet["issued_ids"]["experiment_ids"] == ["EXP-900-1"]
    assert packet["issued_ids"]["candidate_ids"] == ["PEC-900-1"]
    assert packet["issued_ids"]["evidence_ids"] == ["EV-experiment"]


def test_build_audit_packets_chunks_unused_evidence_at_fifteen_items(packet_inputs):
    replayed, evidence = packet_inputs

    packets = build_audit_packets(replayed, evidence)

    unused_packets = [packet for packet in packets if packet["packet_type"] == "unused_evidence"]

    assert [packet["packet_id"] for packet in unused_packets] == [
        "PILOT-900:unused-evidence:001",
        "PILOT-900:unused-evidence:002",
    ]
    assert unused_packets[0]["issued_ids"]["evidence_ids"] == [
        f"EV-unused-{number:02d}" for number in range(1, 16)
    ]
    assert unused_packets[1]["issued_ids"]["evidence_ids"] == ["EV-unused-16"]


def test_build_audit_packets_adds_final_consistency_scope(packet_inputs):
    replayed, evidence = packet_inputs

    packets = build_audit_packets(replayed, evidence)

    packet = packets[-1]

    assert packet["packet_id"] == "PILOT-900:final-consistency"
    assert packet["packet_type"] == "final_consistency"
    assert packet["current_merged_facts"] == {
        "quarantined_conflicts": replayed["quarantined_conflicts"],
        "validation_findings": replayed["validation_findings"],
        "experiment_ids": ["EXP-900-1"],
    }


def test_build_audit_packets_bound_every_packet_and_require_abstention(packet_inputs):
    replayed, evidence = packet_inputs

    packets = build_audit_packets(replayed, evidence)

    assert all("abstain" in packet["abstention"].casefold() for packet in packets)
    assert all("PILOT-900" not in packet["instructions"] for packet in packets)
    assert all(len(json.dumps(packet, ensure_ascii=False)) < 45_000 for packet in packets)
    assert all(len(packet["evidence"]) <= 15 for packet in packets)


def test_build_audit_packets_hashes_deterministically_and_seals_gold_blind_manifest(
    packet_inputs, tmp_path
):
    replayed, evidence = packet_inputs

    packets = build_audit_packets(replayed, evidence)
    destination = tmp_path / "audit_packet_manifest.json"

    assert packets == build_audit_packets(replayed, evidence)
    assert all(
        packet["packet_sha256"]
        == hashlib.sha256(
            json.dumps(
                {key: value for key, value in packet.items() if key != "packet_sha256"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for packet in packets
    )
    assert write_audit_packet_manifest(packets, destination) == destination

    manifest = json.loads(destination.read_text(encoding="utf-8"))
    assert manifest["packet_count"] == 5
    assert manifest["packets"] == [
        {"packet_id": packet["packet_id"], "packet_sha256": packet["packet_sha256"]}
        for packet in packets
    ]
    assert manifest["manifest_sha256"] == hashlib.sha256(
        json.dumps(manifest["packets"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert "gold" not in json.dumps(manifest).casefold()
    with pytest.raises(FileExistsError):
        write_audit_packet_manifest(packets, destination)
