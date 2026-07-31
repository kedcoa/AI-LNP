import copy

import pytest

from src.extraction.experimental_arms import (
    ARM_PROPOSAL_VERSION,
    PAIRING_TYPES,
    build_np002_kupffer_arm_proposal,
    validate_arm_review,
)


def _evidence(evidence_id, text):
    return {"evidence_id": evidence_id, "text": text}


def np002_packet():
    return {
        "paper_id": "NP-002",
        "prior_llm_result": {
            "proposed_arms": [
                {
                    "candidate_id": "UNTRUSTED",
                    "formulation": "invented formulation",
                }
            ]
        },
        "evidence": [
            _evidence(
                "E-ROUTE",
                "Mice were injected intravenously via the lateral tail vein.",
            ),
            _evidence(
                "E-QUANT-REL",
                "We first analyzed the biodistribution of MC3 and cKK-E12 "
                "LNPs to liver endothelial cells, Kupffer cells, and hepatocytes.",
            ),
            _evidence(
                "E-QUANT-COND",
                "Six hours after injecting mice with 0.3 mg/kg QUANT DNA, "
                "we utilized FACS to isolate endothelial cells, Kupffer cells, "
                "and hepatocytes.",
            ),
            _evidence(
                "E-QUANT-OUT",
                "These data suggested that both cKK-E12 and MC3 distribute "
                "broadly to all three tested cell types within the liver, "
                "including Kupffer cells.",
            ),
            _evidence(
                "E-CRE-MODEL",
                "We utilized Ai14 Cre-reporter mice in these experiments to "
                "quantify mRNA delivery at the cellular level.",
            ),
            _evidence(
                "E-CRE-1",
                "We administered Cre mRNA at a dose of 1.0 mg/kg using "
                "cKK-E12 and MC3.",
            ),
            _evidence(
                "E-CRE-TARGET",
                "We isolated cells with flow cytometry and quantified the "
                "percentage of hepatocytes, endothelial cells, or Kupffer "
                "cells that were tdTomato positive.",
            ),
            _evidence(
                "E-CRE-03-COND",
                "We repeated the experiment at a lower dose, 0.3 mg/kg "
                "Cre mRNA.",
            ),
            _evidence(
                "E-CRE-03-OUT",
                "We observed the expected decrease in percent tdTomato "
                "positive cells for both cKK-E12 and MC3 at 0.3 mg/kg, "
                "compared to the 1.0 mg/kg dose.",
            ),
        ],
    }


def unrelated_clause_packet():
    return {
        "paper_id": "NP-002",
        "evidence": [
            _evidence(
                "E-U1",
                "MC3 and cKK-E12 were available as formulation materials.",
            ),
            _evidence(
                "E-U2",
                "Mice received 0.3 mg/kg QUANT DNA in another experiment.",
            ),
            _evidence(
                "E-U3",
                "Kupffer cells are resident macrophages in the liver.",
            ),
            _evidence(
                "E-U4",
                "Mice were injected intravenously via the lateral tail vein.",
            ),
        ],
    }


def respectively_packet():
    return {
        "paper_id": "NP-002",
        "evidence": [
            _evidence(
                "E-P1",
                "Mice were injected intravenously with MC3 carrying QUANT "
                "DNA and cKK-E12 carrying Cre mRNA at 0.3 and 1.0 mg/kg, "
                "respectively; delivery to Kupffer cells was measured.",
            ),
            _evidence(
                "E-P2",
                "The corresponding Kupffer-cell outcomes were directly "
                "measured for both treatments.",
            ),
        ],
    }


def test_builds_six_kupffer_arms_from_explicit_relationships():
    report = build_np002_kupffer_arm_proposal(np002_packet())

    assert report["proposal_version"] == ARM_PROPOSAL_VERSION
    assert [
        (
            row["candidate_id"],
            row["formulation"],
            row["payload"],
            row["dose"],
        )
        for row in report["proposed_arms"]
    ] == [
        ("KUP-01", "MC3", "QUANT DNA", 0.3),
        ("KUP-02", "cKK-E12", "QUANT DNA", 0.3),
        ("KUP-03", "MC3", "Cre mRNA", 1.0),
        ("KUP-04", "cKK-E12", "Cre mRNA", 1.0),
        ("KUP-05", "MC3", "Cre mRNA", 0.3),
        ("KUP-06", "cKK-E12", "Cre mRNA", 0.3),
    ]
    assert all(
        row["target_cell"] == "Kupffer cells"
        for row in report["proposed_arms"]
    )
    assert report["quarantined_arms"] == []


def test_every_arm_has_complete_fields_and_packet_evidence_only():
    packet = np002_packet()
    report = build_np002_kupffer_arm_proposal(packet)
    packet_ids = {row["evidence_id"] for row in packet["evidence"]}
    required = {
        "candidate_id",
        "formulation",
        "payload",
        "dose",
        "dose_unit",
        "route",
        "species",
        "model",
        "target_cell",
        "pairing_type",
        "existence_evidence_ids",
        "outcome_evidence_ids",
        "confidence",
    }

    assert report["packet_evidence_ids"] == [
        row["evidence_id"] for row in packet["evidence"]
    ]
    assert all(set(row) == required for row in report["proposed_arms"])
    assert all(
        row["existence_evidence_ids"] and row["outcome_evidence_ids"]
        for row in report["proposed_arms"]
    )
    assert all(
        set(row["existence_evidence_ids"] + row["outcome_evidence_ids"])
        <= packet_ids
        for row in report["proposed_arms"]
    )
    assert "UNTRUSTED" not in {
        row["candidate_id"] for row in report["proposed_arms"]
    }


def test_does_not_cross_product_unrelated_formulation_and_dose_clauses():
    report = build_np002_kupffer_arm_proposal(unrelated_clause_packet())

    assert report["proposed_arms"] == []
    assert report["quarantined_arms"][0]["reason"] == (
        "relationship_not_explicit"
    )


def test_respectively_uses_paired_correspondence_not_cross_product():
    report = build_np002_kupffer_arm_proposal(respectively_packet())

    assert len(report["proposed_arms"]) == 2
    assert {
        row["pairing_type"] for row in report["proposed_arms"]
    } == {"paired_correspondence"}
    assert [
        (row["formulation"], row["payload"], row["dose"])
        for row in report["proposed_arms"]
    ] == [
        ("MC3", "QUANT DNA", 0.3),
        ("cKK-E12", "Cre mRNA", 1.0),
    ]


@pytest.mark.parametrize(
    "removed_evidence_id",
    ["E-QUANT-COND", "E-CRE-MODEL", "E-CRE-TARGET"],
)
def test_requires_direct_target_cell_and_experimental_model_evidence(
    removed_evidence_id,
):
    packet = np002_packet()
    packet["evidence"] = [
        row
        for row in packet["evidence"]
        if row["evidence_id"] != removed_evidence_id
    ]
    packet["evidence"].append(
        _evidence(
            "E-BACKGROUND",
            "Kupffer cells are resident macrophages lining liver sinusoids.",
        )
    )

    report = build_np002_kupffer_arm_proposal(packet)

    if removed_evidence_id == "E-QUANT-COND":
        assert all(
            row["payload"] != "QUANT DNA" for row in report["proposed_arms"]
        )
    else:
        assert all(
            row["payload"] != "Cre mRNA" for row in report["proposed_arms"]
        )


def _accepted_review(proposal):
    return {
        "review_version": "np002-kupffer-arm-review-1.0.0",
        "proposal_sha256": proposal["proposal_sha256"],
        "decisions": [
            {
                "candidate_id": arm["candidate_id"],
                "decision": "accept",
                "reason": "direct evidence",
            }
            for arm in proposal["proposed_arms"]
        ],
    }


def test_validates_exact_immutable_human_review():
    proposal = build_np002_kupffer_arm_proposal(np002_packet())
    review = _accepted_review(proposal)

    report = validate_arm_review(proposal, review)

    assert report["status"] == "valid"
    assert report["approved_arms"] == proposal["proposed_arms"]
    assert report["accepted_candidate_ids"] == [
        f"KUP-{index:02d}" for index in range(1, 7)
    ]
    assert report["corrected_candidate_ids"] == []
    assert report["added_candidate_ids"] == []
    assert report["removed_candidate_ids"] == []

    modified = copy.deepcopy(proposal)
    modified["proposed_arms"][0]["dose"] = 9.9
    with pytest.raises(ValueError, match="proposal.*SHA|modified"):
        validate_arm_review(modified, review)


@pytest.mark.parametrize("problem", ["missing", "duplicate", "unknown"])
def test_review_requires_one_known_decision_per_proposed_arm(problem):
    proposal = build_np002_kupffer_arm_proposal(np002_packet())
    review = _accepted_review(proposal)
    if problem == "missing":
        review["decisions"].pop()
    elif problem == "duplicate":
        review["decisions"].append(copy.deepcopy(review["decisions"][0]))
    else:
        review["decisions"][-1]["candidate_id"] = "KUP-UNKNOWN"

    with pytest.raises(ValueError, match="decision|candidate"):
        validate_arm_review(proposal, review)


def test_correction_and_addition_require_complete_arms_with_packet_evidence():
    proposal = build_np002_kupffer_arm_proposal(np002_packet())
    review = _accepted_review(proposal)
    correction = copy.deepcopy(proposal["proposed_arms"][0])
    correction["confidence"] = "human_confirmed"
    review["decisions"][0] = {
        "candidate_id": "KUP-01",
        "decision": "correct",
        "reason": "reviewed relationship",
        "arm": correction,
    }
    addition = copy.deepcopy(proposal["proposed_arms"][-1])
    addition["candidate_id"] = "KUP-07"
    review["additions"] = [addition]

    report = validate_arm_review(proposal, review)

    assert report["corrected_candidate_ids"] == ["KUP-01"]
    assert report["added_candidate_ids"] == ["KUP-07"]
    assert [row["candidate_id"] for row in report["approved_arms"]][-1] == (
        "KUP-07"
    )

    incomplete = copy.deepcopy(review)
    incomplete["additions"][0].pop("outcome_evidence_ids")
    with pytest.raises(ValueError, match="complete arm"):
        validate_arm_review(proposal, incomplete)

    outside = copy.deepcopy(review)
    outside["decisions"][0]["arm"]["existence_evidence_ids"] = ["E-OUTSIDE"]
    with pytest.raises(ValueError, match="packet evidence"):
        validate_arm_review(proposal, outside)


def test_rejects_wrong_review_version_or_proposal_sha():
    proposal = build_np002_kupffer_arm_proposal(np002_packet())
    review = _accepted_review(proposal)
    review["review_version"] = "wrong"
    with pytest.raises(ValueError, match="review_version"):
        validate_arm_review(proposal, review)

    review = _accepted_review(proposal)
    review["proposal_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="proposal_sha256"):
        validate_arm_review(proposal, review)

    assert PAIRING_TYPES == {
        "single_statement",
        "cross_product",
        "paired_correspondence",
    }
