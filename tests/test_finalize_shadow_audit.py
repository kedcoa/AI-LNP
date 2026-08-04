from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from src.extraction.build_shadow_benchmark import build_audit_packets
from src.extraction.finalize_shadow_audit import finalize_audit_results


def _packet() -> dict:
    return {
        "packet_id": "PILOT-900:experiment:EXP-900-1",
        "packet_type": "experiment",
        "paper_id": "PILOT-900",
        "issued_ids": {
            "paper_ids": ["PILOT-900"],
            "experiment_ids": ["EXP-900-1"],
            "candidate_ids": ["PEC-900-1"],
            "evidence_ids": ["EV-900-1"],
            "record_ids": [],
            "fact_ids": [],
            "entity_ids": [],
            "arm_ids": [],
            "arm_links": {},
        },
        "current_merged_facts": {
            "experiment_id": "EXP-900-1",
            "candidate_id": "PEC-900-1",
            "facts": [],
        },
        "evidence": [
            {
                "evidence_id": "EV-900-1",
                "excerpt": "The experiment used a dose of 1 mg/kg.",
            }
        ],
    }


def _proposal() -> dict:
    return {
        "proposal_id": "AP-900-1",
        "proposal_type": "add_fact",
        "experiment_id": "EXP-900-1",
        "candidate_id": "PEC-900-1",
        "field_name": "dose",
        "raw_values": ["1 mg/kg"],
        "evidence_ids": ["EV-900-1"],
        "quoted_support": "The experiment used a dose of 1 mg/kg.",
    }


def _result(packet_path: Path, proposals: list[dict], number: int) -> dict:
    return {
        "packet_path": str(packet_path),
        "terminal_disposition": "accepted",
        "parsed_result": {
            "disposition": "proposals",
            "proposals": proposals,
            "unresolved_reason": None,
        },
        "attempt_count": 1,
        "retry_count": 0,
        "attempts": [
            {
                "input_tokens": 100 + number,
                "output_tokens": 10 + number,
                "cached_input_tokens": 20,
                "latency_seconds": 2.0,
                "model": "gpt-test",
            }
        ],
    }


def test_finalize_audit_results_validates_merges_and_accounts_for_every_proposal(
    tmp_path,
):
    first_packet = tmp_path / "packet-1.json"
    second_packet = tmp_path / "packet-2.json"
    first_packet.write_text(json.dumps(_packet()), encoding="utf-8")
    second_packet.write_text(json.dumps(_packet()), encoding="utf-8")
    rejected = deepcopy(_proposal())
    rejected["proposal_id"] = "AP-900-2"
    rejected["quoted_support"] = "unsupported quote"
    baseline = {
        "paper_id": "PILOT-900",
        "shared_facts": [],
        "experiments": [
            {
                "experiment_id": "EXP-900-1",
                "candidate_id": "PEC-900-1",
                "facts": [],
            }
        ],
    }

    summary, audited = finalize_audit_results(
        [
            _result(first_packet, [_proposal()], 1),
            _result(second_packet, [rejected], 2),
        ],
        {"PILOT-900": baseline},
    )

    assert summary["terminal_packets"] == 2
    assert summary["proposal_accounting"] == {
        "proposed": 2,
        "accepted": 1,
        "rejected": 1,
        "rejection_reasons": {"quote_mismatch": 1},
    }
    assert summary["usage"] == {
        "models": ["gpt-test"],
        "input_tokens": 203,
        "output_tokens": 23,
        "cached_input_tokens": 40,
        "attempts_missing_token_measurement": 0,
        "attempt_count": 2,
        "latency_seconds": 4.0,
    }
    assert len(audited["PILOT-900"]["experiments"][0]["facts"]) == 1
    assert baseline["experiments"][0]["facts"] == []


def test_finalize_audit_results_issues_live_replay_replacement_targets(tmp_path):
    baseline = {
        "paper_id": "PILOT-900",
        "shared_facts": [],
        "experiments": [
            {
                "experiment_id": "EXP-900-1",
                "candidate_id": "PEC-900-1",
                "facts": [
                    {
                        "field_name": "dose",
                        "canonical_value": "1 mg/kg",
                        "raw_values": ["1 mg/kg"],
                        "evidence_ids": ["EV-900-1"],
                    }
                ],
            }
        ],
    }
    evidence = [
        {
            "evidence_id": "EV-900-1",
            "text": "The experiment used a dose of 2 mg/kg.",
            "source": "paper.pdf",
            "page_number": 1,
            "heading": "Methods",
            "table_or_figure": None,
            "used_by_merged_records": True,
        }
    ]
    packet = next(
        row
        for row in build_audit_packets(baseline, evidence)
        if row["packet_type"] == "experiment"
    )
    current = packet["current_merged_facts"]["facts"][0]
    proposal = {
        "proposal_id": "AP-900-replace",
        "proposal_type": "replace_fact",
        "experiment_id": "EXP-900-1",
        "candidate_id": "PEC-900-1",
        "field_name": "dose",
        "raw_values": ["2 mg/kg"],
        "evidence_ids": ["EV-900-1"],
        "quoted_support": "The experiment used a dose of 2 mg/kg.",
        "record_id": current["record_id"],
        "fact_id": current["fact_id"],
        "entity_ids": None,
        "arm_id": None,
    }
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    _summary, audited = finalize_audit_results(
        [_result(packet_path, [proposal], 1)], {"PILOT-900": baseline}
    )

    fact = audited["PILOT-900"]["experiments"][0]["facts"][0]
    assert fact["canonical_value"] == "2 mg/kg"
    assert baseline["experiments"][0]["facts"][0]["canonical_value"] == "1 mg/kg"
