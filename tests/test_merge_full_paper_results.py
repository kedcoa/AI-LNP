from __future__ import annotations

from copy import deepcopy

from src.extraction.full_paper_contracts import (
    ContextCandidate,
    ContextTask,
    build_context_response_schema,
)
from src.extraction.full_paper_tasks import stable_experiment_id
from src.extraction.merge_full_paper_results import merge_full_paper_results


def _candidate(**overrides: object) -> ContextCandidate:
    values: dict[str, object] = {
        "experiment_id": "EXP-placeholder",
        "candidate_id": "CTX-A",
        "provisional_context_id": "CTX-A",
        "formulation_id": "FORM-A",
        "formulation": "LNP A",
        "payload_id": "PAY-A",
        "payload": "mRNA A",
        "dose": 1.0,
        "dose_unit": "mg/kg",
        "route": "intravenous",
        "species": "mouse",
        "experimental_model": "healthy mouse",
        "recipient_cell": "hepatocyte",
        "organ": "liver",
        "timepoint": 24.0,
        "timepoint_unit": "hour",
        "field_evidence_ids": {
            "formulation": ["E-FORM"],
            "payload": ["E-PAY"],
            "dose": ["E-JOINT"],
            "dose_unit": ["E-JOINT"],
            "route": ["E-JOINT"],
            "species": ["E-JOINT"],
            "experimental_model": ["E-JOINT"],
            "recipient_cell": ["E-JOINT"],
            "organ": ["E-JOINT"],
            "timepoint": ["E-JOINT"],
            "timepoint_unit": ["E-JOINT"],
        },
        "joint_evidence_ids": ["E-JOINT"],
        "outcome_evidence_ids": ["E-OUT"],
        "pairing_metadata": None,
    }
    values.update(overrides)
    return ContextCandidate.model_validate(values)


def _paper_map() -> dict:
    return {
        "paper_id": "PAPER-1",
        "shared_facts": [
            {
                "field_name": "formulation",
                "raw_value": "LNP A",
                "evidence_ids": ["E-FORM"],
            }
        ],
        "experiments": [
            {"experiment_id": "EXP-A", "candidate_id": "CTX-A"},
            {"experiment_id": "EXP-B", "candidate_id": "CTX-B"},
        ],
        "candidate_evidence_envelopes": {
            "CTX-A": ["E-TEXT"],
            "CTX-B": ["E-OTHER-ARM"],
        },
        "visual_tasks": [
            {
                "experiment_ids": ["EXP-A", "EXP-B"],
                "allowed_evidence_ids": ["E-VISUAL"],
            }
        ],
        "issued_evidence_ids": ["E-FORM", "E-FORM-2"],
    }


def _text_for(experiment_id: str, *, candidate_id: str = "CTX-A") -> dict:
    return {
        "experiment_facts": [
            {
                "experiment_id": experiment_id,
                "candidate_id": candidate_id,
                "facts": [
                    {
                        "field_name": "assay",
                        "raw_value": "ddPCR",
                        "evidence_ids": ["E-TEXT"],
                    }
                ],
            }
        ]
    }


def _vision_for(experiment_id: str, *, candidate_id: str = "CTX-A") -> dict:
    return {
        "experiment_facts": [
            {
                "experiment_id": experiment_id,
                "candidate_id": candidate_id,
                "facts": [
                    {
                        "field_name": "assay",
                        "raw_value": "digital droplet PCR",
                        "evidence_ids": ["E-VISUAL"],
                    }
                ],
            }
        ]
    }


def test_stable_experiment_id_uses_identity_and_evidence_not_candidate_label() -> None:
    original = _candidate(candidate_id="CTX-A", provisional_context_id="CTX-A")
    renamed = _candidate(candidate_id="CTX-RENAMED", provisional_context_id="CTX-RENAMED")

    assert stable_experiment_id("PAPER-1", original) == stable_experiment_id(
        "PAPER-1", renamed
    )
    assert stable_experiment_id("PAPER-1", original).startswith("EXP-")


def test_stable_experiment_id_separates_dose_timepoint_and_evidence_identity() -> None:
    original = _candidate()
    changed_dose = _candidate(dose=2.0)
    changed_timepoint = _candidate(timepoint=48.0)
    changed_evidence = _candidate(joint_evidence_ids=["E-OTHER-JOINT"])

    issued = stable_experiment_id("PAPER-1", original)

    assert issued != stable_experiment_id("PAPER-1", changed_dose)
    assert issued != stable_experiment_id("PAPER-1", changed_timepoint)
    assert issued != stable_experiment_id("PAPER-1", changed_evidence)


def test_context_schema_allows_only_locally_issued_experiment_ids() -> None:
    candidate = _candidate(experiment_id="EXP-ISSUED")

    schema = build_context_response_schema([candidate])

    assert schema["$defs"]["ExperimentRecord"]["properties"][
        "experiment_id"
    ]["enum"] == ["EXP-ISSUED"]
    assert schema["$defs"]["OutcomeRecord"]["properties"][
        "experiment_id"
    ]["enum"] == ["EXP-ISSUED"]


def test_text_and_visual_facts_join_only_on_issued_experiment_id() -> None:
    result = merge_full_paper_results(
        _paper_map(), [_text_for("EXP-A")], [_vision_for("EXP-A")]
    )

    assert [row.experiment_id for row in result.experiments] == ["EXP-A", "EXP-B"]
    assay = result.experiments[0].facts[0]
    assert assay.field_name == "assay"
    assert assay.canonical_value == "droplet digital pcr"
    assert assay.raw_values == ["ddPCR", "digital droplet PCR"]
    assert assay.evidence_ids == ["E-TEXT", "E-VISUAL"]
    assert result.quarantined_conflicts == []


def test_changed_experiment_id_is_rejected_not_reassigned() -> None:
    result = merge_full_paper_results(
        _paper_map(), [_text_for("EXP-A")], [_vision_for("EXP-Z")]
    )

    assert result.experiments[0].experiment_id == "EXP-A"
    assert [row.code for row in result.quarantined_conflicts] == [
        "unknown_experiment_id"
    ]
    assert result.experiments[0].facts[0].evidence_ids == ["E-TEXT"]


def test_candidate_experiment_mismatch_is_quarantined() -> None:
    result = merge_full_paper_results(
        _paper_map(), [_text_for("EXP-A", candidate_id="CTX-B")], []
    )

    assert result.experiments[0].facts == []
    assert result.quarantined_conflicts[0].code == "candidate_experiment_mismatch"


def test_conflicting_canonical_values_are_quarantined_without_a_winner() -> None:
    context = _text_for("EXP-A")
    visual = _vision_for("EXP-A")
    visual["experiment_facts"][0]["facts"][0]["raw_value"] = "ELISA"

    result = merge_full_paper_results(_paper_map(), [context], [visual])

    assert result.experiments[0].facts == []
    conflict = result.quarantined_conflicts[0]
    assert conflict.code == "conflicting_canonical_values"
    assert conflict.canonical_values == ["droplet digital pcr", "elisa"]
    assert conflict.evidence_ids == ["E-TEXT", "E-VISUAL"]


def test_shared_formulation_fact_is_merged_once_for_multiple_experiments() -> None:
    second_map = deepcopy(_paper_map())
    second_map["shared_facts"].append(
        {
            "field_name": "formulation",
            "raw_value": "  lnp   a ",
            "evidence_ids": ["E-FORM-2"],
        }
    )

    result = merge_full_paper_results(second_map, [], [])

    assert len(result.experiments) == 2
    assert len(result.shared_facts) == 1
    assert result.shared_facts[0].raw_values == ["LNP A", "  lnp   a "]
    assert result.shared_facts[0].evidence_ids == ["E-FORM", "E-FORM-2"]


def test_flat_fact_can_join_inventory_issued_id_without_candidate_echo() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiment_inventory": {
            "EXP-A": {
                "experiment_id": "EXP-A",
                "candidate_id": "CTX-A",
                "visual_evidence_ids": ["E-VISUAL"],
            }
        },
    }
    visual_fact = {
        "experiment_id": "EXP-A",
        "field_name": "endpoint",
        "raw_value": "Reporter signal",
        "evidence_ids": ["E-VISUAL"],
    }

    result = merge_full_paper_results(paper_map, [], [visual_fact])

    assert result.experiments[0].experiment_id == "EXP-A"
    assert result.experiments[0].facts[0].field_name == "endpoint"
    assert result.quarantined_conflicts == []


def test_out_of_envelope_fact_is_quarantined_before_accumulation() -> None:
    paper_map = _paper_map()
    paper_map["candidate_evidence_envelopes"] = {
        "CTX-A": ["E-TEXT"],
        "CTX-B": ["E-OTHER-ARM"],
    }
    invented = _text_for("EXP-A")
    invented["experiment_facts"][0]["facts"][0]["evidence_ids"] = [
        "E-INVENTED"
    ]

    result = merge_full_paper_results(paper_map, [invented], [])

    assert result.experiments[0].facts == []
    assert result.quarantined_conflicts[0].code == (
        "evidence_outside_experiment_envelope"
    )
    assert result.quarantined_conflicts[0].evidence_ids == ["E-INVENTED"]


def test_real_paper_map_deterministically_issues_experiments() -> None:
    paper_map = {
        "paper_map_version": "full-paper-map-1.0.0",
        "paper_id": "PAPER-REAL",
        "formulations": [
            {
                "formulation_id": "FORM-A",
                "name": {"value": "LNP A", "evidence_ids": ["E-FORM"]},
                "components": [],
                "ratios": [],
                "ratio_bases": [],
            }
        ],
        "payloads": [
            {
                "payload_id": "PAY-A",
                "identity": {"value": "mRNA A", "evidence_ids": ["E-PAY"]},
                "role": None,
            }
        ],
        "common_routes": [],
        "common_species": [],
        "common_models": [],
        "recipient_contexts": [],
        "provisional_experiment_contexts": [
            {
                "provisional_context_id": "CTX-REAL",
                "formulation_id": "FORM-A",
                "payload_id": "PAY-A",
                "dose": {"value": 1.0, "evidence_ids": ["E-JOINT"]},
                "dose_unit": {"value": "mg/kg", "evidence_ids": ["E-JOINT"]},
                "route": {"value": "intravenous", "evidence_ids": ["E-JOINT"]},
                "species": {"value": "mouse", "evidence_ids": ["E-JOINT"]},
                "experimental_model": {
                    "value": "healthy mouse",
                    "evidence_ids": ["E-JOINT"],
                },
                "recipient_cell": {
                    "value": "hepatocyte",
                    "evidence_ids": ["E-JOINT"],
                },
                "organ": {"value": "liver", "evidence_ids": ["E-JOINT"]},
                "timepoint": {"value": 24.0, "evidence_ids": ["E-JOINT"]},
                "timepoint_unit": {
                    "value": "hour",
                    "evidence_ids": ["E-JOINT"],
                },
                "joint_evidence_ids": ["E-JOINT"],
                "outcome_evidence_ids": ["E-OUT"],
                "pairing_metadata": None,
            }
        ],
        "anchor_accounting": {},
        "unresolved_items": [],
    }

    issued = merge_full_paper_results(paper_map, [], [])
    repeated = merge_full_paper_results(deepcopy(paper_map), [], [])

    assert len(issued.experiments) == 1
    assert issued.experiments[0].candidate_id == "CTX-REAL"
    assert issued.experiments[0].experiment_id.startswith("EXP-")
    assert repeated.experiments[0].experiment_id == issued.experiments[0].experiment_id


def test_duplicate_experiment_issuance_is_quarantined_and_disabled() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {
                "experiment_id": "EXP-DUP",
                "candidate_id": "CTX-A",
                "evidence_ids": ["E-TEXT"],
            },
            {
                "experiment_id": "EXP-DUP",
                "candidate_id": "CTX-B",
                "evidence_ids": ["E-TEXT"],
            },
        ],
    }

    result = merge_full_paper_results(
        paper_map, [_text_for("EXP-DUP")], []
    )

    assert result.experiments == []
    assert "duplicate_issued_experiment_id" in {
        row.code for row in result.quarantined_conflicts
    }


def test_saved_selective_vision_outcomes_are_ingested_as_scoped_facts() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {"experiment_id": "EXP-A", "candidate_id": "CTX-A"}
        ],
        "visual_tasks": [
            {
                "experiment_inventory": {
                    "EXP-A": {
                        "experiment_id": "EXP-A",
                        "candidate_id": "CTX-A",
                    }
                },
                "allowed_evidence_ids": ["E-FIGURE"],
            }
        ],
    }
    saved_response = {
        "paper_id": "PAPER-1",
        "outcomes": [
            {
                "slot_id": "figure-2-mc3-hepatocytes",
                "experiment_id": "EXP-A",
                "assay": "cellular DNA accumulation",
                "endpoint": "QUANT DNA accumulation",
                "qualitative_outcome": "higher than comparator",
                "evidence_ids": ["E-FIGURE"],
            }
        ],
    }

    result = merge_full_paper_results(paper_map, [], [saved_response])

    assert result.quarantined_conflicts == []
    assert {row.field_name for row in result.experiments[0].facts} == {
        "outcome.figure-2-mc3-hepatocytes.assay",
        "outcome.figure-2-mc3-hepatocytes.endpoint",
        "outcome.figure-2-mc3-hepatocytes.qualitative_outcome",
    }


def test_saved_visual_outcome_with_wrong_arm_identity_is_quarantined() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiment_inventory": {
            "EXP-A": {
                "experiment_id": "EXP-A",
                "candidate_id": "CTX-A",
                "formulation": "LNP A",
                "payload": "mRNA A",
                "dose": {"value": 1.0, "evidence_ids": ["E-JOINT-A"]},
            },
            "EXP-B": {
                "experiment_id": "EXP-B",
                "candidate_id": "CTX-B",
                "formulation": "LNP B",
                "payload": "mRNA A",
                "dose": {"value": 1.0, "evidence_ids": ["E-JOINT-B"]},
            },
        },
        "visual_tasks": [
            {
                "experiment_inventory": {
                    "EXP-A": {"experiment_id": "EXP-A"},
                    "EXP-B": {"experiment_id": "EXP-B"},
                },
                "allowed_evidence_ids": ["E-FIGURE"],
            }
        ],
    }
    wrong_arm = {
        "outcomes": [
            {
                "slot_id": "slot-a",
                "experiment_id": "EXP-B",
                "formulation": "LNP A",
                "payload": "mRNA A",
                "dose": 1.0,
                "endpoint": "reporter signal",
                "evidence_ids": ["E-FIGURE"],
            }
        ]
    }

    result = merge_full_paper_results(paper_map, [], [wrong_arm])

    assert result.experiments[1].facts == []
    assert result.quarantined_conflicts[0].code == (
        "candidate_experiment_mismatch"
    )


def test_context_task_version_marks_experiment_id_contract_change() -> None:
    schema = ContextTask.model_json_schema()

    assert schema["properties"]["context_task_version"]["const"] == (
        "full-paper-context-task-1.1.0"
    )
