from __future__ import annotations

from copy import deepcopy

import pytest

from src.extraction.validate_shadow_audit import (
    merge_validated_proposals,
    validate_proposal,
)


@pytest.fixture
def packet() -> dict:
    return {
        "packet_id": "PILOT-900:experiment:EXP-900-1",
        "packet_type": "experiment",
        "paper_id": "PILOT-900",
        "issued_ids": {
            "paper_ids": ["PILOT-900"],
            "experiment_ids": ["EXP-900-1"],
            "candidate_ids": ["PEC-900-1"],
            "evidence_ids": ["EV-900-1"],
        },
        "current_merged_facts": {
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
        },
        "evidence": [
            {
                "evidence_id": "EV-900-1",
                "excerpt": "Experiment EXP-900-1 used a dose of 1 mg/kg.",
            }
        ],
    }


@pytest.fixture
def proposal() -> dict:
    return {
        "proposal_id": "AP-900-1",
        "proposal_type": "add_fact",
        "experiment_id": "EXP-900-1",
        "candidate_id": "PEC-900-1",
        "field_name": "dose",
        "raw_values": ["1 mg/kg"],
        "evidence_ids": ["EV-900-1"],
        "quoted_support": "Experiment EXP-900-1 used a dose of 1 mg/kg.",
    }


def test_validator_accepts_supported_proposal_with_issued_arm(packet, proposal):
    validation = validate_proposal(proposal, packet)

    assert validation["accepted"] is True
    assert validation["rejection_reasons"] == []
    assert validation["proposal"] == proposal


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda row: row.update(evidence_ids=["EV-invented"]), "unknown_evidence_id"),
        (lambda row: row.update(raw_values=["2 mg/kg"]), "unsupported_exact_number"),
        (lambda row: row.update(quoted_support="Dose was estimated."), "quote_mismatch"),
        (lambda row: row.update(experiment_id="EXP-900-2"), "unknown_experiment_id"),
        (lambda row: row.update(candidate_id="PEC-900-2"), "unknown_candidate_id"),
        (lambda row: row.update(record_id="REC-invented"), "unknown_record_id"),
    ],
)
def test_validator_rejects_unissued_or_unsupported_proposal_fields(
    packet, proposal, change, reason
):
    proposed = deepcopy(proposal)
    change(proposed)

    validation = validate_proposal(proposed, packet)

    assert validation["accepted"] is False
    assert reason in validation["rejection_reasons"]


def test_validator_rejects_cross_experiment_evidence_and_wrong_arm_link(packet, proposal):
    scoped_packet = deepcopy(packet)
    scoped_packet["evidence"][0]["experiment_id"] = "EXP-900-2"
    scoped_packet["issued_ids"]["experiment_ids"].append("EXP-900-2")
    scoped_packet["issued_ids"]["candidate_ids"].append("PEC-900-2")
    proposed = deepcopy(proposal)
    proposed["candidate_id"] = "PEC-900-2"

    validation = validate_proposal(proposed, scoped_packet)

    assert validation["accepted"] is False
    assert "cross_experiment_evidence" in validation["rejection_reasons"]
    assert "wrong_arm_link" in validation["rejection_reasons"]


def test_merge_copies_baseline_and_only_attaches_accepted_proposals_with_provenance(
    packet, proposal
):
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
        "quarantined_conflicts": [],
        "validation_findings": [],
    }
    original = deepcopy(baseline)
    accepted = validate_proposal(proposal, packet)
    rejected = {"accepted": False, "proposal": {**proposal, "proposal_id": "AP-bad"}}

    audited = merge_validated_proposals(baseline, [accepted, rejected])

    assert baseline == original
    assert audited is not baseline
    fact = audited["experiments"][0]["facts"]
    assert len(fact) == 1
    assert fact[0]["raw_values"] == ["1 mg/kg"]
    assert fact[0]["audit_provenance"] == {
        "proposal_id": "AP-900-1",
        "evidence_ids": ["EV-900-1"],
        "quoted_support": "Experiment EXP-900-1 used a dose of 1 mg/kg.",
    }


def test_merge_refuses_to_apply_malformed_accepted_validation():
    with pytest.raises(ValueError, match="accepted validation"):
        merge_validated_proposals({}, [{"accepted": True, "proposal": {}}])
