from __future__ import annotations

from copy import deepcopy
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


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "reference_answers",
        "benchmark_score",
        "known_miss_prose",
        "human_audit_corrections",
    ],
)
def test_build_audit_packets_rejects_prohibited_replay_families(
    packet_inputs, forbidden_key
):
    replayed, evidence = packet_inputs
    replayed["shared_facts"][0][forbidden_key] = "must not reach a packet"

    with pytest.raises(ValueError, match="gold-blind"):
        build_audit_packets(replayed, evidence)


def test_build_audit_packets_projects_only_scientific_current_facts(packet_inputs):
    replayed, evidence = packet_inputs
    replayed["shared_facts"][0]["operational_history"] = {"run_id": "prior-run"}
    replayed["experiments"][0]["provider_response"] = {"attempt": 7}
    replayed["experiments"][0]["facts"][0]["normalization_rules"] = [
        "casefold_whitespace"
    ]
    replayed["quarantined_conflicts"][0]["source"] = "internal/path.json"
    replayed["validation_findings"][0]["history"] = ["previous validation"]

    packets = build_audit_packets(replayed, evidence)

    assert packets[0]["current_merged_facts"] == [
        {
            "field_name": "formulation.lipid",
            "canonical_value": "Lipid A",
            "raw_values": ["Lipid A"],
            "evidence_ids": ["EV-shared"],
        }
    ]
    assert packets[1]["current_merged_facts"] == {
        "experiment_id": "EXP-900-1",
        "candidate_id": "PEC-900-1",
        "facts": [
            {
                "field_name": "dose",
                "canonical_value": "1 mg/kg",
                "raw_values": ["1 mg/kg"],
                "evidence_ids": ["EV-experiment"],
            }
        ],
    }
    assert packets[-1]["current_merged_facts"] == {
        "quarantined_conflicts": [
            {
                "conflict_id": "QC-900-1",
                "reason": "Competing dose values",
                "evidence_ids": ["EV-unused-01"],
            }
        ],
        "validation_findings": [
            {
                "finding_id": "VF-900-1",
                "severity": "medium",
                "evidence_ids": ["EV-experiment"],
            }
        ],
        "experiment_ids": ["EXP-900-1"],
    }
    serialized = json.dumps(packets, ensure_ascii=False)
    assert "operational_history" not in serialized
    assert "provider_response" not in serialized
    assert "internal/path.json" not in serialized
    assert "previous validation" not in serialized


def test_build_audit_packets_partitions_every_over_limit_scope(packet_inputs):
    replayed, evidence = packet_inputs
    replayed = deepcopy(replayed)
    evidence = deepcopy(evidence)
    shared_ids = [f"EV-shared-{number:02d}" for number in range(1, 17)]
    experiment_ids = [f"EV-experiment-{number:02d}" for number in range(1, 17)]
    final_ids = [f"EV-final-{number:02d}" for number in range(1, 17)]
    replayed["shared_facts"] = [
        {
            "field_name": f"shared.{number}",
            "canonical_value": f"shared value {number}",
            "raw_values": [f"shared value {number}"],
            "evidence_ids": [evidence_id],
        }
        for number, evidence_id in enumerate(shared_ids, start=1)
    ]
    replayed["experiments"][0]["facts"] = [
        {
            "field_name": f"outcome.{number}",
            "canonical_value": f"outcome value {number}",
            "raw_values": [f"outcome value {number}"],
            "evidence_ids": [evidence_id],
        }
        for number, evidence_id in enumerate(experiment_ids, start=1)
    ]
    replayed["quarantined_conflicts"] = [
        {
            "conflict_id": f"QC-900-{number}",
            "reason": "Competing values",
            "evidence_ids": [evidence_id],
        }
        for number, evidence_id in enumerate(final_ids, start=1)
    ]
    replayed["validation_findings"] = []
    evidence.extend(
        {
            "evidence_id": evidence_id,
            "text": f"Evidence {evidence_id}",
            "source": "paper.html",
            "page_number": 4,
            "heading": "Results",
            "table_or_figure": None,
            "used_by_merged_records": True,
        }
        for evidence_id in [*shared_ids, *experiment_ids, *final_ids]
    )

    packets = build_audit_packets(replayed, evidence)

    assert [packet["packet_id"] for packet in packets if packet["packet_type"] == "shared_paper"] == [
        "PILOT-900:shared-paper:001",
        "PILOT-900:shared-paper:002",
    ]
    assert [packet["packet_id"] for packet in packets if packet["packet_type"] == "experiment"] == [
        "PILOT-900:experiment:EXP-900-1:001",
        "PILOT-900:experiment:EXP-900-1:002",
    ]
    assert [packet["packet_id"] for packet in packets if packet["packet_type"] == "final_consistency"] == [
        "PILOT-900:final-consistency:001",
        "PILOT-900:final-consistency:002",
    ]
    assert all(len(packet["evidence"]) <= 15 for packet in packets)
    assert all(len(json.dumps(packet, ensure_ascii=False)) < 45_000 for packet in packets)
    assert {
        evidence_id
        for packet in packets
        for evidence_id in packet["issued_ids"]["evidence_ids"]
    } >= set(shared_ids + experiment_ids + final_ids)


def test_build_audit_packets_includes_proposal_only_output_contract(packet_inputs):
    replayed, evidence = packet_inputs

    packet = build_audit_packets(replayed, evidence)[0]
    schema = packet["output_schema"]

    assert set(schema["properties"]) == {
        "disposition",
        "proposals",
        "unresolved_reason",
    }
    assert schema["properties"]["disposition"]["enum"] == ["proposals", "abstained"]
    assert schema["additionalProperties"] is False
    assert "observations" not in schema["properties"]
    assert "findings" not in schema["properties"]


def test_build_audit_packets_rejects_duplicate_full_evidence_before_excerpt_truncation(
    packet_inputs,
):
    replayed, evidence = packet_inputs
    duplicate = deepcopy(evidence[0])
    duplicate["text"] = "x" * 1_800 + "different suffix"
    evidence[0]["text"] = "x" * 1_800 + "original suffix"
    evidence.append(duplicate)

    with pytest.raises(ValueError, match="conflicting evidence inventory rows"):
        build_audit_packets(replayed, evidence)
