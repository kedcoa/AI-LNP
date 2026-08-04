from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.extraction.build_shadow_benchmark import build_audit_packets
from src.extraction.finalize_shadow_audit import finalize_audit_results
from src.extraction.finalize_shadow_audit import (
    _promote_evidence_statuses,
    build_proposal_ledger,
    finalize_retained_run,
)


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


def test_retained_finalizer_refuses_incomplete_packets_before_loading_gold(tmp_path):
    run_root = tmp_path / "run"
    audit_root = run_root / "audit-codex"
    packet_root = audit_root / "audit_packets"
    packet_root.mkdir(parents=True)
    (packet_root / "manifest.json").write_text(
        json.dumps(
            {
                "packet_count": 1,
                "packets": [
                    {"packet_id": "PILOT-900:shared-paper", "packet_sha256": "0" * 64}
                ],
                "manifest_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    (audit_root / "packet_results.json").write_text(
        json.dumps({"packet_count": 1, "results": []}), encoding="utf-8"
    )
    (audit_root / "run_manifest.json").write_text(
        json.dumps({"unattempted_packet_paths": [], "attempt_count": 0}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="all issued packets are terminal"):
        finalize_retained_run(
            run_root=run_root,
            artifact_root=tmp_path / "missing-artifacts",
            reference_root=tmp_path / "missing-gold",
            report_path=tmp_path / "missing-report.json",
            output_root=tmp_path / "output",
            codex_cli_version="codex-cli test",
        )


def test_proposal_ledger_contains_only_ids_decision_and_exact_reason_codes():
    summary = {
        "packets": [
            {
                "packet_id": "PILOT-900:shared-paper",
                "paper_id": "PILOT-900",
                "validations": [
                    {
                        "accepted": False,
                        "rejection_reasons": ["posthoc_raw_value_mismatch"],
                        "proposal": {
                            "proposal_id": "PROP-PILOT-900-001",
                            "raw_values": ["provider-only raw value"],
                            "quoted_support": "provider-only quotation",
                        },
                    }
                ],
            }
        ]
    }

    ledger = build_proposal_ledger(summary)

    assert ledger == [
        {
            "proposal_id": "PROP-PILOT-900-001",
            "packet_id": "PILOT-900:shared-paper",
            "accepted": False,
            "reason_codes": ["posthoc_raw_value_mismatch"],
        }
    ]
    assert "provider-only" not in json.dumps(ledger)


def test_proposal_ledger_rejects_model_text_disguised_as_an_identifier():
    summary = {
        "packets": [
            {
                "packet_id": "PILOT-900:shared-paper",
                "paper_id": "PILOT-900",
                "validations": [
                    {
                        "accepted": True,
                        "rejection_reasons": [],
                        "proposal": {
                            "proposal_id": "This proposal says the secret raw value"
                        },
                    }
                ],
            }
        ]
    }

    with pytest.raises(ValueError, match="safe identifier grammar"):
        build_proposal_ledger(summary)


def test_supported_automated_recovery_promotes_partial_evidence_inventory():
    before_evidence = {"REQ-1": "full", "REQ-2": "partial", "REQ-3": "absent"}
    before_automated = {"REQ-1": True, "REQ-2": False, "REQ-3": False}
    after_automated = {"REQ-1": True, "REQ-2": True, "REQ-3": False}

    promoted, recovered_partial_or_absent, recovered_absent = (
        _promote_evidence_statuses(
            before_evidence, before_automated, after_automated
        )
    )

    assert promoted == {"REQ-1": "full", "REQ-2": "full", "REQ-3": "absent"}
    assert recovered_partial_or_absent == 1
    assert recovered_absent == 0


def test_nonaccepted_terminal_result_never_applies_embedded_proposals(tmp_path):
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(_packet()), encoding="utf-8")
    result = _result(packet_path, [_proposal()], 1)
    result["terminal_disposition"] = "schema_failure"
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
        [result], {"PILOT-900": baseline}
    )

    assert summary["proposal_accounting"]["proposed"] == 0
    assert audited["PILOT-900"]["experiments"][0]["facts"] == []
