import copy

import pytest

from src.extraction.experimental_arms import (
    ARM_PROPOSAL_VERSION,
    PAIRING_TYPES,
    build_experimental_arm_schema,
    build_np002_kupffer_arm_proposal,
    validate_experimental_arm_response,
    validate_arm_review,
)
from src.extraction.compact_contracts import CompactExtractionResponse


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
                "E-QUANT-BOUND",
                "We injected mice intravenously with 0.3 mg/kg QUANT DNA "
                "carried by either MC3 or cKK-E12 LNPs and measured "
                "biodistribution to Kupffer cells.",
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
                "We repeated the Cre mRNA experiment at 0.3 mg/kg using both "
                "cKK-E12 and MC3 and observed the expected decrease in "
                "percent tdTomato positive cells.",
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
    ["E-QUANT-BOUND", "E-CRE-MODEL", "E-CRE-TARGET"],
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

    if removed_evidence_id == "E-QUANT-BOUND":
        assert all(
            row["payload"] != "QUANT DNA" for row in report["proposed_arms"]
        )
    else:
        assert all(
            row["payload"] != "Cre mRNA" for row in report["proposed_arms"]
        )


@pytest.mark.parametrize("same_experiment", [True, False])
def test_never_joins_separate_formulation_and_dose_clauses(
    same_experiment,
):
    formulation_experiment = ["EXP-1"]
    condition_experiment = ["EXP-1" if same_experiment else "EXP-2"]
    packet = {
        "paper_id": "NP-002",
        "evidence": [
            {
                **_evidence(
                    "E-X1",
                    "We analyzed the biodistribution of MC3 and cKK-E12 "
                    "LNPs to Kupffer cells.",
                ),
                "experiment_candidate_ids": formulation_experiment,
            },
            {
                **_evidence(
                    "E-X2",
                    "Mice were injected with 0.3 mg/kg QUANT DNA and Kupffer "
                    "cells were isolated.",
                ),
                "experiment_candidate_ids": condition_experiment,
            },
            _evidence(
                "E-X3",
                "Mice were injected intravenously via the lateral tail vein.",
            ),
        ],
    }

    report = build_np002_kupffer_arm_proposal(packet)

    assert report["proposed_arms"] == []
    assert report["quarantined_arms"][0]["family"] == "QUANT DNA 0.3 mg/kg"
    assert report["quarantined_arms"][0]["reason"] == (
        "relationship_not_explicit"
    )


def test_quarantines_unsupported_family_when_other_arms_are_supported():
    packet = np002_packet()
    packet["evidence"] = [
        row
        for row in packet["evidence"]
        if row["evidence_id"] != "E-QUANT-BOUND"
    ]
    packet["evidence"].extend(
        [
            _evidence(
                "E-MIX-Q1",
                "We analyzed biodistribution of MC3 and cKK-E12 LNPs to "
                "Kupffer cells.",
            ),
            _evidence(
                "E-MIX-Q2",
                "Mice received 0.3 mg/kg QUANT DNA in a separate experiment.",
            ),
        ]
    )

    report = build_np002_kupffer_arm_proposal(packet)

    assert {
        row["payload"] for row in report["proposed_arms"]
    } == {"Cre mRNA"}
    assert report["quarantined_arms"] == [
        {
            "family": "QUANT DNA 0.3 mg/kg",
            "reason": "relationship_not_explicit",
            "evidence_ids": ["E-QUANT-OUT", "E-MIX-Q1", "E-MIX-Q2"],
        }
    ]


def test_respectively_parses_reversed_formulation_order():
    packet = respectively_packet()
    packet["evidence"][0]["text"] = (
        "Mice were injected intravenously with cKK-E12 carrying QUANT DNA "
        "and MC3 carrying Cre mRNA at 0.3 and 1.0 mg/kg, respectively; "
        "delivery to Kupffer cells was measured."
    )

    report = build_np002_kupffer_arm_proposal(packet)

    assert [
        (row["formulation"], row["payload"], row["dose"])
        for row in report["proposed_arms"]
    ] == [
        ("cKK-E12", "QUANT DNA", 0.3),
        ("MC3", "Cre mRNA", 1.0),
    ]


def test_respectively_fails_closed_for_mismatched_lists():
    packet = respectively_packet()
    packet["evidence"][0]["text"] = (
        "Mice were injected intravenously with MC3 carrying QUANT DNA and "
        "cKK-E12 carrying Cre mRNA at 0.1, 0.3, and 1.0 mg/kg, respectively; "
        "delivery to Kupffer cells was measured."
    )

    report = build_np002_kupffer_arm_proposal(packet)

    assert report["proposed_arms"] == []
    assert report["quarantined_arms"][0]["family"] == (
        "paired_correspondence"
    )


def _paired_inventory_packet(*, malformed_pairing):
    packet = np002_packet()
    packet["evidence"] = [
        row
        for row in packet["evidence"]
        if row["evidence_id"] not in {"E-QUANT-BOUND", "E-CRE-03-COND"}
    ]
    paired = respectively_packet()["evidence"]
    if malformed_pairing:
        paired[0]["text"] = (
            "Mice were injected intravenously with MC3 carrying QUANT DNA "
            "and cKK-E12 carrying Cre mRNA at 0.1, 0.3, and 1.0 mg/kg, "
            "respectively; delivery to Kupffer cells was measured."
        )
    packet["evidence"].extend(
        [
            _evidence(
                "E-MIX-Q1",
                "We analyzed biodistribution of MC3 and cKK-E12 LNPs to "
                "Kupffer cells.",
            ),
            _evidence(
                "E-MIX-Q2",
                "Mice received 0.3 mg/kg QUANT DNA in another experiment.",
            ),
            *paired,
        ]
    )
    return packet


def test_valid_paired_relationship_merges_inventory_arms_and_quarantines():
    report = build_np002_kupffer_arm_proposal(
        _paired_inventory_packet(malformed_pairing=False)
    )

    assert [row["candidate_id"] for row in report["proposed_arms"]] == [
        "KUP-01",
        "KUP-02",
        "KUP-03",
        "KUP-04",
    ]
    assert {
        row["pairing_type"] for row in report["proposed_arms"][:2]
    } == {"paired_correspondence"}
    assert any(
        row["family"] == "QUANT DNA 0.3 mg/kg"
        for row in report["quarantined_arms"]
    )


def test_malformed_paired_relationship_does_not_suppress_inventory_results():
    report = build_np002_kupffer_arm_proposal(
        _paired_inventory_packet(malformed_pairing=True)
    )

    assert [row["candidate_id"] for row in report["proposed_arms"]] == [
        "KUP-03",
        "KUP-04",
    ]
    assert {
        row["family"] for row in report["quarantined_arms"]
    } == {"paired_correspondence", "QUANT DNA 0.3 mg/kg"}


def test_paired_and_inventory_candidate_id_conflicts_fail_closed():
    packet = np002_packet()
    packet["evidence"].extend(respectively_packet()["evidence"])

    report = build_np002_kupffer_arm_proposal(packet)

    candidate_ids = [
        row["candidate_id"] for row in report["proposed_arms"]
    ]
    assert candidate_ids == [f"KUP-{index:02d}" for index in range(1, 7)]
    assert len(candidate_ids) == len(set(candidate_ids))
    conflicts = [
        row
        for row in report["quarantined_arms"]
        if row["reason"] == "candidate_id_conflict"
    ]
    assert [row["candidate_id"] for row in conflicts] == [
        "KUP-01",
        "KUP-02",
    ]


def _multiple_respectively_packet(*, malformed_first):
    valid = copy.deepcopy(respectively_packet()["evidence"][0])
    valid["evidence_id"] = "E-PAIR-VALID"
    malformed = copy.deepcopy(valid)
    malformed["evidence_id"] = "E-PAIR-MALFORMED"
    malformed["text"] = (
        "Mice were injected intravenously with MC3 carrying QUANT DNA and "
        "cKK-E12 carrying Cre mRNA at 0.1, 0.3, and 1.0 mg/kg, respectively; "
        "delivery to Kupffer cells was measured."
    )
    rows = [malformed, valid] if malformed_first else [valid, malformed]
    return {
        "paper_id": "NP-002",
        "evidence": [
            *rows,
            _evidence(
                "E-PAIR-OUT",
                "The corresponding Kupffer-cell outcomes were directly measured.",
            ),
        ],
    }


@pytest.mark.parametrize("malformed_first", [False, True])
def test_every_respectively_row_is_accounted_for_regardless_of_order(
    malformed_first,
):
    report = build_np002_kupffer_arm_proposal(
        _multiple_respectively_packet(malformed_first=malformed_first)
    )

    assert [row["candidate_id"] for row in report["proposed_arms"]] == [
        "KUP-01",
        "KUP-02",
    ]
    malformed = [
        row
        for row in report["quarantined_arms"]
        if row["reason"] == "relationship_not_explicit"
    ]
    assert malformed == [
        {
            "family": "paired_correspondence",
            "reason": "relationship_not_explicit",
            "evidence_ids": ["E-PAIR-MALFORMED"],
        }
    ]


def test_multiple_valid_respectively_rows_quarantine_candidate_id_conflicts():
    packet = respectively_packet()
    packet["evidence"][0]["evidence_id"] = "E-PAIR-FIRST"
    reversed_row = copy.deepcopy(packet["evidence"][0])
    reversed_row["evidence_id"] = "E-PAIR-SECOND"
    reversed_row["text"] = (
        "Mice were injected intravenously with cKK-E12 carrying QUANT DNA "
        "and MC3 carrying Cre mRNA at 0.3 and 1.0 mg/kg, respectively; "
        "delivery to Kupffer cells was measured."
    )
    packet["evidence"].insert(1, reversed_row)

    report = build_np002_kupffer_arm_proposal(packet)

    assert [
        (row["candidate_id"], row["formulation"])
        for row in report["proposed_arms"]
    ] == [("KUP-01", "MC3"), ("KUP-02", "cKK-E12")]
    conflicts = [
        row
        for row in report["quarantined_arms"]
        if row["reason"] == "candidate_id_conflict"
    ]
    assert [
        (row["candidate_id"], row["evidence_ids"])
        for row in conflicts
    ] == [
        ("KUP-01", ["E-PAIR-SECOND", "E-P2"]),
        ("KUP-02", ["E-PAIR-SECOND", "E-P2"]),
    ]


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


def test_review_rejects_non_kupffer_or_semantically_unsupported_additions():
    proposal = build_np002_kupffer_arm_proposal(np002_packet())
    review = _accepted_review(proposal)
    addition = copy.deepcopy(proposal["proposed_arms"][0])
    addition["candidate_id"] = "KUP-07"
    addition["target_cell"] = "hepatocytes"
    review["additions"] = [addition]

    with pytest.raises(ValueError, match="Kupffer"):
        validate_arm_review(proposal, review)

    arbitrary = copy.deepcopy(addition)
    arbitrary["target_cell"] = "Kupffer cells"
    arbitrary["formulation"] = "invented formulation"
    arbitrary["payload"] = "invented payload"
    arbitrary["existence_evidence_ids"] = ["E-ROUTE"]
    arbitrary["outcome_evidence_ids"] = ["E-ROUTE"]
    review["additions"] = [arbitrary]
    with pytest.raises(ValueError, match="scope|semantic|support"):
        validate_arm_review(proposal, review)


def test_review_rejects_aggregate_token_soup_without_one_binding_record():
    packet = np002_packet()
    packet["evidence"].extend(
        [
            _evidence("E-A1", "MC3 was purchased for formulation work."),
            _evidence(
                "E-A2",
                "Mice in another experiment received 0.3 mg/kg QUANT DNA.",
            ),
            _evidence(
                "E-A3",
                "Kupffer cells are resident macrophages in the liver.",
            ),
            _evidence(
                "E-A4",
                "Mice were injected intravenously via the lateral tail vein.",
            ),
            _evidence(
                "E-A5",
                "An unrelated Kupffer-cell outcome was measured.",
            ),
        ]
    )
    proposal = build_np002_kupffer_arm_proposal(packet)
    review = _accepted_review(proposal)
    addition = copy.deepcopy(proposal["proposed_arms"][0])
    addition["candidate_id"] = "KUP-07"
    addition["existence_evidence_ids"] = [
        "E-A1",
        "E-A2",
        "E-A3",
        "E-A4",
    ]
    addition["outcome_evidence_ids"] = ["E-A5"]
    review["additions"] = [addition]

    with pytest.raises(ValueError, match="binding|relationship"):
        validate_arm_review(proposal, review)


def test_review_rejects_payload_model_mismatch():
    proposal = build_np002_kupffer_arm_proposal(np002_packet())
    review = _accepted_review(proposal)
    addition = copy.deepcopy(proposal["proposed_arms"][0])
    addition["candidate_id"] = "KUP-07"
    addition["model"] = "Ai14 Cre-reporter mice"
    addition["existence_evidence_ids"].append("E-CRE-MODEL")
    review["additions"] = [addition]

    with pytest.raises(ValueError, match="model|QUANT"):
        validate_arm_review(proposal, review)


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


def _reported_value(value, evidence_id="E-ARM"):
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": [evidence_id],
        "missing_reason": None,
    }


def approved_arms():
    return [
        {
            "candidate_id": "KUP-01",
            "formulation": "MC3",
            "payload": "QUANT DNA",
            "dose": 0.3,
            "dose_unit": "mg/kg",
            "route": "intravenous lateral tail vein",
            "species": "mice",
            "model": "mice",
            "target_cell": "Kupffer cells",
        },
        {
            "candidate_id": "KUP-02",
            "formulation": "cKK-E12",
            "payload": "QUANT DNA",
            "dose": 0.3,
            "dose_unit": "mg/kg",
            "route": "intravenous lateral tail vein",
            "species": "mice",
            "model": "mice",
            "target_cell": "Kupffer cells",
        },
        {
            "candidate_id": "KUP-03",
            "formulation": "MC3",
            "payload": "Cre mRNA",
            "dose": 1.0,
            "dose_unit": "mg/kg",
            "route": "intravenous lateral tail vein",
            "species": "mice",
            "model": "Ai14 Cre-reporter mice",
            "target_cell": "Kupffer cells",
        },
        {
            "candidate_id": "KUP-04",
            "formulation": "cKK-E12",
            "payload": "Cre mRNA",
            "dose": 1.0,
            "dose_unit": "mg/kg",
            "route": "intravenous lateral tail vein",
            "species": "mice",
            "model": "Ai14 Cre-reporter mice",
            "target_cell": "Kupffer cells",
        },
        {
            "candidate_id": "KUP-05",
            "formulation": "MC3",
            "payload": "Cre mRNA",
            "dose": 0.3,
            "dose_unit": "mg/kg",
            "route": "intravenous lateral tail vein",
            "species": "mice",
            "model": "Ai14 Cre-reporter mice",
            "target_cell": "Kupffer cells",
        },
        {
            "candidate_id": "KUP-06",
            "formulation": "cKK-E12",
            "payload": "Cre mRNA",
            "dose": 0.3,
            "dose_unit": "mg/kg",
            "route": "intravenous lateral tail vein",
            "species": "mice",
            "model": "Ai14 Cre-reporter mice",
            "target_cell": "Kupffer cells",
        },
    ]


def base_schema():
    return CompactExtractionResponse.model_json_schema()


def _arm_response():
    arms = approved_arms()
    formulations = [
        {
            "formulation_id": "F-MC3",
            "formulation_name": _reported_value("MC3"),
            "composition": _reported_value("lipids"),
            "composition_basis": _reported_value("reported"),
            "np_ratio": _reported_value(6.0),
        },
        {
            "formulation_id": "F-cKK",
            "formulation_name": _reported_value("cKK-E12 LNP"),
            "composition": _reported_value("lipids"),
            "composition_basis": _reported_value("reported"),
            "np_ratio": _reported_value(6.0),
        },
    ]
    experiments = []
    outcomes = []
    accounting = {}
    for index, arm in enumerate(arms, start=1):
        experiment_id = f"EXP-{index}"
        outcome_id = f"OUT-{index}"
        is_quant = arm["payload"] == "QUANT DNA"
        experiments.append(
            {
                "experiment_id": experiment_id,
                "formulation_id": "F-MC3" if arm["formulation"] == "MC3" else "F-cKK",
                "payload_type": _reported_value("DNA" if is_quant else "mRNA"),
                "payload_name": _reported_value(arm["payload"]),
                "encoded_product": _reported_value("QUANT" if is_quant else "Cre"),
                "molecular_target": _reported_value("Kupffer cells"),
                "delivery_recipient_cell": _reported_value("Kupffer cells"),
                "therapeutic_target_cell": _reported_value("Kupffer cells"),
                "tissue_or_organ": _reported_value("liver"),
                "species": _reported_value("mouse"),
                "disease_model": _reported_value(arm["model"]),
                "experimental_context": _reported_value("in_vivo"),
                "dose": _reported_value(arm["dose"]),
                "dose_unit": _reported_value("mg/kg"),
                "route": _reported_value("IV"),
                "timepoint": _reported_value(6.0 if is_quant else 3.0),
                "timepoint_unit": _reported_value("hours" if is_quant else "days"),
            }
        )
        outcomes.append(
            {
                "outcome_id": outcome_id,
                "experiment_id": experiment_id,
                "assay": _reported_value("ddPCR" if is_quant else "flow cytometry"),
                "endpoint": _reported_value("QUANT copies" if is_quant else "tdTomato positive"),
                "comparator": _reported_value("control"),
                "outcome_value": _reported_value(float(index)),
                "outcome_unit": _reported_value("percent"),
                "qualitative_outcome": _reported_value("reported Kupffer-cell result"),
            }
        )
        accounting[arm["candidate_id"]] = {
            "disposition": "extracted",
            "linked_experiment_ids": [experiment_id],
            "linked_outcome_ids": [outcome_id],
            "evidence_ids": ["E-ARM"],
            "reason_code": "extracted",
            "explanation": "The returned records match this approved arm.",
        }
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": "NP-002",
        "eligibility": {
            "decision": "eligible",
            "reason_codes": [
                "ORIGINAL_EXPERIMENT",
                "IDENTIFIABLE_LNP",
                "SUPPORTED_PAYLOAD",
                "TARGET_CELL_EVIDENCE",
                "USABLE_FORMULATION_OUTCOME_LINKAGE",
            ],
            "evidence_ids": ["E-ARM"],
            "explanation": "The controlled arm extraction is eligible.",
        },
        "formulations": formulations,
        "components": [],
        "experiments": experiments,
        "outcomes": outcomes,
        "unresolved_items": [],
        "experimental_arm_accounting": accounting,
    }


def _error_codes(report):
    return {row["code"] for row in report["errors"]}


def test_dynamic_schema_requires_the_six_approved_arm_keys():
    schema = build_experimental_arm_schema(base_schema(), approved_arms())

    accounting = schema["properties"]["experimental_arm_accounting"]
    assert accounting["required"] == [
        "KUP-01",
        "KUP-02",
        "KUP-03",
        "KUP-04",
        "KUP-05",
        "KUP-06",
    ]
    assert accounting["additionalProperties"] is False
    for candidate_id in accounting["required"]:
        assert accounting["properties"][candidate_id]["$ref"].endswith(
            "ExperimentalArmAccountingEntry"
        )


def test_dynamic_schema_closes_entries_and_encodes_extracted_and_ambiguous_shapes():
    schema = build_experimental_arm_schema(base_schema(), approved_arms())

    entry = schema["$defs"]["ExperimentalArmAccountingEntry"]
    assert entry["properties"]["disposition"]["enum"] == [
        "extracted",
        "ambiguous",
    ]
    variants = entry["oneOf"]
    assert [variant["properties"]["disposition"] for variant in variants] == [
        {"const": "extracted"},
        {"const": "ambiguous"},
    ]
    assert variants[0]["properties"]["linked_experiment_ids"]["minItems"] == 1
    assert variants[0]["properties"]["linked_outcome_ids"]["minItems"] == 1
    assert variants[1]["properties"]["linked_experiment_ids"]["maxItems"] == 0
    assert variants[1]["properties"]["reason_code"]["enum"] == [
        "conflicting_evidence",
        "candidate_not_grounded",
    ]


def test_validator_confirms_all_six_exact_arm_mappings():
    report = validate_experimental_arm_response(
        _arm_response(), approved_arms(), {"E-ARM"}
    )

    assert report == {
        "sent": 6,
        "accounted": 6,
        "structurally_valid_extracted": 6,
        "scientifically_confirmed": 6,
        "ambiguous": 0,
        "confirmed_candidate_ids": [
            "KUP-01",
            "KUP-02",
            "KUP-03",
            "KUP-04",
            "KUP-05",
            "KUP-06",
        ],
        "errors": [],
    }


@pytest.mark.parametrize("bad_disposition", ["duplicate", "invalid", "not_core", "insufficient_evidence"])
def test_validator_rejects_unsupported_accounting_dispositions(bad_disposition):
    response = _arm_response()
    response["experimental_arm_accounting"]["KUP-01"]["disposition"] = bad_disposition

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "invalid_disposition" in _error_codes(report)


@pytest.mark.parametrize("problem", ["missing", "invented", "repeated"])
def test_validator_rejects_missing_invented_or_repeated_candidate_ids(problem):
    response = _arm_response()
    arms = approved_arms()
    if problem == "missing":
        response["experimental_arm_accounting"].pop("KUP-06")
    elif problem == "invented":
        response["experimental_arm_accounting"]["KUP-99"] = response[
            "experimental_arm_accounting"
        ]["KUP-06"]
    else:
        arms[-1]["candidate_id"] = "KUP-05"

    if problem == "repeated":
        with pytest.raises(ValueError, match="canonical"):
            validate_experimental_arm_response(response, arms, {"E-ARM"})
        return

    report = validate_experimental_arm_response(response, arms, {"E-ARM"})

    assert f"{problem}_candidate_ids" in _error_codes(report)


def test_validator_rejects_extracted_entry_without_returned_record_links():
    response = _arm_response()
    entry = response["experimental_arm_accounting"]["KUP-01"]
    entry["linked_experiment_ids"] = []
    entry["linked_outcome_ids"] = []

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "extracted_requires_record_links" in _error_codes(report)


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("formulations", 0, "formulation_name", "value"), "wrong LNP"),
        (("experiments", 0, "payload_name", "value"), "wrong payload"),
        (("experiments", 0, "payload_type", "value"), "mRNA"),
        (("experiments", 0, "dose", "value"), 9.9),
        (("experiments", 0, "delivery_recipient_cell", "value"), "hepatocyte"),
        (("experiments", 0, "route", "value"), "intraperitoneal"),
        (("experiments", 0, "disease_model", "value"), "wrong model"),
    ],
)
def test_validator_rejects_scientific_identity_mismatches(path, bad_value):
    response = _arm_response()
    target = response
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "scientific_identity_mismatch" in _error_codes(report)


@pytest.mark.parametrize(
    ("candidate_id", "path", "bad_value", "expected_code"),
    [
        ("KUP-01", ("experiments", 0, "timepoint", "value"), 24.0, "quant_timepoint_required"),
        ("KUP-01", ("outcomes", 0, "assay", "value"), "qPCR", "quant_ddpcr_required"),
        ("KUP-03", ("experiments", 2, "timepoint", "value"), 6.0, "cre_timepoint_required"),
        ("KUP-03", ("outcomes", 2, "endpoint", "value"), "GFP positive", "cre_tdtomato_flow_required"),
    ],
)
def test_validator_requires_payload_specific_timepoint_and_measurement(
    candidate_id, path, bad_value, expected_code
):
    response = _arm_response()
    target = response
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert expected_code in _error_codes(report)
    assert candidate_id not in report["confirmed_candidate_ids"]


def test_validator_rejects_citations_outside_the_evidence_envelope():
    response = _arm_response()
    response["experimental_arm_accounting"]["KUP-01"]["evidence_ids"] = ["E-OUTSIDE"]

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "evidence_outside_envelope" in _error_codes(report)


def test_validator_does_not_confirm_an_arm_with_a_core_citation_outside_envelope():
    response = _arm_response()
    response["outcomes"][0]["endpoint"]["evidence_ids"] = ["E-OUTSIDE"]

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "core_evidence_outside_envelope" in _error_codes(report)
    assert "KUP-01" not in report["confirmed_candidate_ids"]


def test_validator_rejects_one_outcome_reused_across_incompatible_arms():
    response = _arm_response()
    response["experimental_arm_accounting"]["KUP-02"]["linked_outcome_ids"] = ["OUT-1"]
    response["experimental_arm_accounting"]["KUP-02"]["linked_experiment_ids"] = ["EXP-1"]

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "outcome_reused_across_incompatible_arms" in _error_codes(report)


def test_validator_counts_ambiguous_candidate_as_accounted_but_not_confirmed():
    response = _arm_response()
    response["experimental_arm_accounting"]["KUP-06"] = {
        "disposition": "ambiguous",
        "linked_experiment_ids": [],
        "linked_outcome_ids": [],
        "evidence_ids": ["E-ARM"],
        "reason_code": "candidate_not_grounded",
        "explanation": "The evidence does not resolve the arm identity.",
    }

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert report["accounted"] == 6
    assert report["ambiguous"] == 1
    assert report["scientifically_confirmed"] == 5
    assert "KUP-06" not in report["confirmed_candidate_ids"]


@pytest.mark.parametrize("candidate_id", ["KUP-01", "KUP-06"])
def test_validator_requires_evidence_for_extracted_and_ambiguous_entries(candidate_id):
    response = _arm_response()
    if candidate_id == "KUP-06":
        response["experimental_arm_accounting"][candidate_id] = {
            "disposition": "ambiguous",
            "linked_experiment_ids": [],
            "linked_outcome_ids": [],
            "evidence_ids": [],
            "reason_code": "candidate_not_grounded",
            "explanation": "The evidence does not resolve the arm identity.",
        }
    else:
        response["experimental_arm_accounting"][candidate_id]["evidence_ids"] = []

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "accounting_evidence_required" in _error_codes(report)


@pytest.mark.parametrize("problem", ["missing", "extra", "substituted"])
def test_schema_and_validator_require_the_canonical_six_approved_arms(problem):
    arms = approved_arms()
    if problem == "missing":
        arms.pop()
    elif problem == "extra":
        extra = copy.deepcopy(arms[-1])
        extra["candidate_id"] = "KUP-07"
        arms.append(extra)
    else:
        arms[-1]["candidate_id"] = "KUP-99"

    with pytest.raises(ValueError, match="canonical"):
        build_experimental_arm_schema(base_schema(), arms)
    with pytest.raises(ValueError, match="canonical"):
        validate_experimental_arm_response(_arm_response(), arms, {"E-ARM"})


def test_validator_requires_accounting_evidence_to_cover_linked_scientific_fields():
    response = _arm_response()
    response["experimental_arm_accounting"]["KUP-01"]["evidence_ids"] = ["E-ACCOUNT"]
    response["formulations"][0]["formulation_name"]["evidence_ids"] = ["E-RECORD"]
    for field in (
        "payload_type",
        "payload_name",
        "dose",
        "dose_unit",
        "route",
        "species",
        "disease_model",
        "delivery_recipient_cell",
        "timepoint",
        "timepoint_unit",
    ):
        response["experiments"][0][field]["evidence_ids"] = ["E-RECORD"]
    for field in ("assay", "endpoint", "qualitative_outcome"):
        response["outcomes"][0][field]["evidence_ids"] = ["E-RECORD"]

    report = validate_experimental_arm_response(
        response, approved_arms(), {"E-ARM", "E-ACCOUNT", "E-RECORD"}
    )

    assert "accounting_evidence_does_not_cover_scientific_fields" in _error_codes(report)
    assert "KUP-01" not in report["confirmed_candidate_ids"]


def test_validator_requires_one_quant_outcome_to_establish_ddpcr():
    response = _arm_response()
    response["outcomes"][0]["assay"]["value"] = "qPCR"
    response["outcomes"][0]["endpoint"]["value"] = "ddPCR copies"

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "quant_ddpcr_required" in _error_codes(report)
    assert "KUP-01" not in report["confirmed_candidate_ids"]


def test_validator_requires_one_cre_outcome_to_establish_flow_cytometry_and_tdtomato():
    response = _arm_response()
    response["outcomes"][2]["endpoint"]["value"] = "GFP positive"
    split_outcome = copy.deepcopy(response["outcomes"][2])
    split_outcome["outcome_id"] = "OUT-CRE-SPLIT"
    split_outcome["assay"]["value"] = "qPCR"
    split_outcome["endpoint"]["value"] = "tdTomato positive"
    response["outcomes"].append(split_outcome)
    response["experimental_arm_accounting"]["KUP-03"]["linked_outcome_ids"].append(
        "OUT-CRE-SPLIT"
    )

    report = validate_experimental_arm_response(response, approved_arms(), {"E-ARM"})

    assert "cre_tdtomato_flow_required" in _error_codes(report)
    assert "KUP-03" not in report["confirmed_candidate_ids"]
