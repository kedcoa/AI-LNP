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
                "experiment_evidence_envelopes": {
                    "EXP-A": ["E-VISUAL"],
                    "EXP-B": ["E-VISUAL"],
                },
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
        "visual_tasks": [
            {
                "experiment_id": "EXP-NOT-USED-BY-MAP-ISSUANCE",
                "candidate_id": "CTX-VISUAL",
                "crop_evidence_id": "E-VISUAL",
            }
        ],
    }

    issued = merge_full_paper_results(paper_map, [], [])
    repeated = merge_full_paper_results(deepcopy(paper_map), [], [])

    assert len(issued.experiments) == 2
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


def test_resolved_selective_vision_fragment_is_ingested_with_issued_ids() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {"experiment_id": "EXP-A", "candidate_id": "CTX-A"}
        ],
        "visual_tasks": [
            {
                "experiment_ids": ["EXP-A"],
                "allowed_evidence_ids": ["E-CAPTION", "E-CROP"],
            }
        ],
    }
    response = {
        "experiment_id": "EXP-A",
        "candidate_id": "CTX-A",
        "finding_id": "VF-1",
        "disposition": "resolved",
        "field_name": "qualitative_outcome",
        "corrected_fragment": {
            "qualitative_outcome": {
                "value": "lower fibrosis than comparator",
                "status": "reported",
                "evidence_ids": ["E-CAPTION", "E-CROP"],
                "missing_reason": None,
            }
        },
        "supporting_evidence_ids": ["E-CAPTION", "E-CROP"],
    }

    result = merge_full_paper_results(paper_map, [], [response])

    assert result.quarantined_conflicts == []
    fact = result.experiments[0].facts[0]
    assert fact.field_name == "vision.VF-1.qualitative_outcome"
    assert fact.raw_values == ["lower fibrosis than comparator"]
    assert fact.evidence_ids == ["E-CAPTION", "E-CROP"]


def test_raw_selective_vision_task_rejects_unissued_finding_id() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {"experiment_id": "EXP-A", "candidate_id": "CTX-A"}
        ],
        "visual_tasks": [
            {
                "experiment_id": "EXP-A",
                "candidate_id": "CTX-A",
                "finding": {
                    "finding_id": "VF-ISSUED",
                    "field_name": "qualitative_outcome",
                },
                "crop_evidence_id": "E-CROP",
                "caption": {"evidence_id": "E-CAPTION"},
                "referring_results_passages": [],
                "methods_context": [],
            }
        ],
    }
    response = {
        "experiment_id": "EXP-A",
        "candidate_id": "CTX-A",
        "finding_id": "VF-INVENTED",
        "disposition": "resolved",
        "field_name": "qualitative_outcome",
        "corrected_fragment": {
            "qualitative_outcome": {
                "value": "lower fibrosis than comparator",
                "status": "reported",
                "evidence_ids": ["E-CAPTION", "E-CROP"],
                "missing_reason": None,
            }
        },
        "supporting_evidence_ids": ["E-CAPTION", "E-CROP"],
    }

    result = merge_full_paper_results(paper_map, [], [response])

    assert result.experiments[0].facts == []
    assert [row.code for row in result.quarantined_conflicts] == [
        "visual_contract_mismatch"
    ]


def test_compact_context_reported_fields_are_ingested_as_experiment_facts() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {
                "experiment_id": "EXP-A",
                "candidate_id": "CTX-A",
                "context_evidence_ids": ["E-TEXT"],
            }
        ],
    }
    reported = lambda value: {
        "value": value,
        "status": "reported",
        "evidence_ids": ["E-TEXT"],
        "missing_reason": None,
    }
    response = {
        "formulations": [
            {
                "formulation_id": "FORM-A",
                "formulation_name": reported("LNP A"),
            }
        ],
        "components": [
            {
                "component_id": "COMP-A",
                "formulation_id": "FORM-A",
                "identity": reported("DSPC"),
            }
        ],
        "experiments": [
            {
                "experiment_id": "EXP-A",
                "formulation_id": "FORM-A",
                "payload_name": reported("Cre mRNA"),
                "species": reported("mouse"),
                "delivery_recipient_cell": reported("hepatocyte"),
                "dose": reported(0.5),
                "dose_unit": reported("mg/kg"),
            }
        ],
        "outcomes": [
            {
                "outcome_id": "OUT-1",
                "experiment_id": "EXP-A",
                "assay": reported("histology"),
                "qualitative_outcome": reported("higher signal than control"),
            }
        ],
    }

    result = merge_full_paper_results(paper_map, [response], [])

    assert result.quarantined_conflicts == []
    facts = {row.field_name: row.canonical_value for row in result.experiments[0].facts}
    assert facts["payload"] == "cre mrna"
    assert facts["recipient_cell"] == "hepatocyte"
    assert facts["dose"] == "0.5 mg/kg"
    assert facts["outcome.OUT-1.assay"] == "histology"
    assert facts["outcome.OUT-1.qualitative_outcome"] == "higher signal than control"
    assert any(
        row.field_name == "component.FORM-A.COMP-A.component_identity"
        and row.canonical_value == "dspc"
        for row in result.shared_facts
    )


def test_native_paper_map_components_remain_repeatable_shared_facts() -> None:
    paper_map = _paper_map()
    paper_map["formulations"] = [
        {
            "formulation_id": "FORM-A",
            "name": {"value": "LNP A", "evidence_ids": ["E-FORM"]},
            "components": [
                {
                    "component_id": "C-1",
                    "identity": {"value": "Lipid A", "evidence_ids": ["E-FORM"]},
                    "role": None,
                },
                {
                    "component_id": "C-2",
                    "identity": {"value": "DSPC", "evidence_ids": ["E-FORM"]},
                    "role": None,
                },
            ],
            "ratios": [
                {"value": "50:10:38.5:1.5", "evidence_ids": ["E-FORM"]}
            ],
            "ratio_bases": [
                {"value": "molar", "evidence_ids": ["E-FORM"]}
            ],
        }
    ]

    result = merge_full_paper_results(paper_map, [], [])

    components = [
        row.canonical_value
        for row in result.shared_facts
        if row.field_name.endswith(".component_identity")
    ]
    assert components == ["lipid a", "dspc"]
    assert result.quarantined_conflicts == []


def test_literal_weight_ratio_in_basis_emits_mass_ratio_fact() -> None:
    paper_map = _paper_map()
    paper_map["issued_evidence_ids"] = ["E-FORM", "E-MOLAR", "E-MASS"]
    paper_map["formulations"] = [
        {
            "formulation_id": "FORM-A",
            "name": {"value": "LNP A", "evidence_ids": ["E-FORM"]},
            "components": [],
            "ratios": [
                {"value": "26.5:20:52:1.5", "evidence_ids": ["E-MOLAR"]}
            ],
            "ratio_bases": [
                {
                    "value": "Molar ratio of lipid components",
                    "evidence_ids": ["E-MOLAR"],
                },
                {
                    "value": "Ionizable lipid:mRNA weight ratio 10:1",
                    "evidence_ids": ["E-MASS"],
                },
            ],
        }
    ]

    result = merge_full_paper_results(paper_map, [], [])

    assert any(
        row.field_name == "formulation.FORM-A.mass_ratio"
        and row.canonical_value == "10:1"
        and row.evidence_ids == ["E-MASS"]
        for row in result.shared_facts
    )


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
        "full-paper-context-task-1.2.0"
    )


def test_multi_experiment_visual_task_rejects_task_wide_only_evidence() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {"experiment_id": "EXP-A", "candidate_id": "CTX-A"},
            {"experiment_id": "EXP-B", "candidate_id": "CTX-B"},
        ],
        "visual_tasks": [
            {
                "experiment_ids": ["EXP-A", "EXP-B"],
                "allowed_evidence_ids": ["E-TASK-WIDE"],
            }
        ],
    }
    fact_without_identity_echo = {
        "experiment_id": "EXP-A",
        "field_name": "endpoint",
        "raw_value": "reporter signal",
        "evidence_ids": ["E-TASK-WIDE"],
    }

    result = merge_full_paper_results(
        paper_map, [], [fact_without_identity_echo]
    )

    assert result.experiments[0].facts == []
    assert result.quarantined_conflicts[0].code == (
        "missing_visual_evidence_envelope"
    )


def test_multi_experiment_visual_task_enforces_per_experiment_envelope() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {"experiment_id": "EXP-A", "candidate_id": "CTX-A"},
            {"experiment_id": "EXP-B", "candidate_id": "CTX-B"},
        ],
        "visual_tasks": [
            {
                "experiment_ids": ["EXP-A", "EXP-B"],
                "allowed_evidence_ids": ["E-A", "E-B"],
                "experiment_evidence_envelopes": {
                    "EXP-A": ["E-A"],
                    "EXP-B": ["E-B"],
                },
            }
        ],
    }
    cross_arm = {
        "experiment_id": "EXP-A",
        "field_name": "endpoint",
        "raw_value": "reporter signal",
        "evidence_ids": ["E-B"],
    }

    result = merge_full_paper_results(paper_map, [], [cross_arm])

    assert result.experiments[0].facts == []
    assert result.quarantined_conflicts[0].code == (
        "evidence_outside_experiment_envelope"
    )


def test_single_experiment_visual_task_can_use_task_wide_envelope() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {"experiment_id": "EXP-A", "candidate_id": "CTX-A"}
        ],
        "visual_tasks": [
            {
                "experiment_ids": ["EXP-A"],
                "allowed_evidence_ids": ["E-SINGLE"],
            }
        ],
    }
    fact = {
        "experiment_id": "EXP-A",
        "field_name": "endpoint",
        "raw_value": "reporter signal",
        "evidence_ids": ["E-SINGLE"],
    }

    result = merge_full_paper_results(paper_map, [], [fact])

    assert result.experiments[0].facts[0].evidence_ids == ["E-SINGLE"]
    assert result.quarantined_conflicts == []


def test_same_candidate_duplicate_with_conflicting_identity_is_disabled() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {
                "experiment_id": "EXP-DUP",
                "candidate_id": "CTX-A",
                "formulation": "LNP A",
                "evidence_ids": ["E-A"],
            },
            {
                "experiment_id": "EXP-DUP",
                "candidate_id": "CTX-A",
                "formulation": "LNP B",
                "evidence_ids": ["E-A"],
            },
        ],
    }

    result = merge_full_paper_results(
        paper_map, [_text_for("EXP-DUP")], []
    )

    assert result.experiments == []
    assert result.quarantined_conflicts[0].code == (
        "duplicate_issued_experiment_id"
    )


def test_same_candidate_duplicate_with_conflicting_evidence_is_disabled() -> None:
    paper_map = {
        "paper_id": "PAPER-1",
        "experiments": [
            {
                "experiment_id": "EXP-DUP",
                "candidate_id": "CTX-A",
                "context_evidence_ids": ["E-A"],
            },
            {
                "experiment_id": "EXP-DUP",
                "candidate_id": "CTX-A",
                "context_evidence_ids": ["E-B"],
            },
        ],
    }

    result = merge_full_paper_results(
        paper_map, [_text_for("EXP-DUP")], []
    )

    assert result.experiments == []
    assert result.quarantined_conflicts[0].code == (
        "duplicate_issued_experiment_id"
    )


def test_context_task_duplicate_with_conflicting_envelope_is_disabled() -> None:
    candidate = _candidate(
        experiment_id="EXP-DUP",
        candidate_id="CTX-A",
        provisional_context_id="CTX-A",
    ).model_dump(mode="json")
    paper_map = {
        "paper_id": "PAPER-1",
        "context_tasks": [
            {
                "candidates": [candidate],
                "candidate_evidence_envelopes": {"CTX-A": ["E-A"]},
            },
            {
                "candidates": [candidate],
                "candidate_evidence_envelopes": {"CTX-A": ["E-B"]},
            },
        ],
    }

    result = merge_full_paper_results(
        paper_map, [_text_for("EXP-DUP")], []
    )

    assert result.experiments == []
    assert result.quarantined_conflicts[0].code == (
        "duplicate_issued_experiment_id"
    )


def test_visual_task_duplicate_with_conflicting_envelope_is_disabled() -> None:
    inventory = {
        "EXP-DUP": {
            "experiment_id": "EXP-DUP",
            "candidate_id": "CTX-A",
        }
    }
    paper_map = {
        "paper_id": "PAPER-1",
        "visual_tasks": [
            {
                "experiment_inventory": inventory,
                "allowed_evidence_ids": ["E-A"],
                "experiment_evidence_envelopes": {"EXP-DUP": ["E-A"]},
            },
            {
                "experiment_inventory": inventory,
                "allowed_evidence_ids": ["E-B"],
                "experiment_evidence_envelopes": {"EXP-DUP": ["E-B"]},
            },
        ],
    }

    result = merge_full_paper_results(
        paper_map, [], [_vision_for("EXP-DUP")]
    )

    assert result.experiments == []
    assert result.quarantined_conflicts[0].code == (
        "duplicate_issued_experiment_id"
    )


def test_repeated_identical_task_envelopes_remain_valid() -> None:
    candidate = _candidate(
        experiment_id="EXP-A",
        candidate_id="CTX-A",
        provisional_context_id="CTX-A",
    ).model_dump(mode="json")
    inventory = {
        "EXP-A": {
            "experiment_id": "EXP-A",
            "candidate_id": "CTX-A",
        }
    }
    context_task = {
        "candidates": [candidate],
        "candidate_evidence_envelopes": {"CTX-A": ["E-TEXT"]},
    }
    visual_task = {
        "experiment_inventory": inventory,
        "allowed_evidence_ids": ["E-VISUAL"],
        "experiment_evidence_envelopes": {"EXP-A": ["E-VISUAL"]},
    }
    paper_map = {
        "paper_id": "PAPER-1",
        "context_tasks": [deepcopy(context_task), deepcopy(context_task)],
        "visual_tasks": [deepcopy(visual_task), deepcopy(visual_task)],
    }

    result = merge_full_paper_results(
        paper_map, [_text_for("EXP-A")], [_vision_for("EXP-A")]
    )

    assert len(result.experiments) == 1
    assert result.experiments[0].facts[0].evidence_ids == [
        "E-TEXT",
        "E-VISUAL",
    ]
    assert result.quarantined_conflicts == []
