from __future__ import annotations

from copy import deepcopy

from src.extraction.full_paper_contracts import (
    ContextCandidate,
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
