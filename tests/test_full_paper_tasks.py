from __future__ import annotations

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

import src.extraction.full_paper_tasks as full_paper_tasks
from src.extraction.full_paper_contracts import (
    CandidateOutcomeBundle,
    OutcomeAssertion,
    PaperMapResponse,
)
from src.extraction.full_paper_inventory import (
    FullPaperEvidenceBlock,
    FullPaperEvidenceInventory,
)
from src.extraction.full_paper_tasks import (
    build_context_tasks,
    build_paper_map_request,
    validate_context_response,
)


def _inventory(*, long_outcomes: bool = False) -> FullPaperEvidenceInventory:
    filler = " quantified response" * (1_600 if long_outcomes else 1)
    blocks = [
        (
            "E-SHARED-A",
            "Zephyr-9 contains amphiphile A, helper B, sterol C, and "
            "polymer-lipid D at 45:40:12:3 molar ratio.",
            ["formulation", "component_ratio", "ratio_basis"],
        ),
        (
            "E-SHARED-B",
            "Nimbus-4 contains amphiphile Q and helper R at a 3:2 mass ratio.",
            ["formulation", "component_ratio", "ratio_basis"],
        ),
        (
            "E-PAYLOAD-A",
            "The cargo was cobalt luciferase RNA.",
            ["payload"],
        ),
        (
            "E-PAYLOAD-B",
            "A separate arm carried amber antisense RNA.",
            ["payload"],
        ),
        (
            "E-JOINT-1",
            "Zephyr-9 carrying cobalt RNA was infused at 0.4 mg/kg into "
            "ferrets; stellate-like cells were measured after 8 hours.",
            ["formulation", "payload", "route", "species", "model", "cell"],
        ),
        (
            "E-OUT-1",
            "Reporter signal increased in stellate-like cells." + filler,
            ["outcome", "cell"],
        ),
        (
            "E-JOINT-2",
            "Zephyr-9 carrying cobalt RNA was infused at 0.9 mg/kg into "
            "ferrets; stellate-like cells were measured after 20 hours.",
            ["formulation", "payload", "route", "species", "model", "cell"],
        ),
        (
            "E-OUT-2",
            "A dose-dependent signal was measured by luminometry." + filler,
            ["outcome"],
        ),
        (
            "E-JOINT-3",
            "Nimbus-4 carrying amber antisense RNA was applied at 2 µg/mL "
            "to a canine organoid; sinusoidal-like cells were measured at 2 days.",
            ["formulation", "payload", "route", "species", "model", "cell"],
        ),
        (
            "E-OUT-3",
            "Target transcript abundance decreased." + filler,
            ["outcome"],
        ),
        (
            "E-UNRELATED",
            "An unrelated behavioral observation was recorded.",
            ["outcome"],
        ),
    ]
    return FullPaperEvidenceInventory(
        paper_id="SYNTH-77",
        source_pdf="synthetic.html",
        evidence_blocks=[
            FullPaperEvidenceBlock(
                evidence_id=evidence_id,
                page_number=index,
                heading="Synthetic study",
                text=text,
                retrieval_tags=tags,
            )
            for index, (evidence_id, text, tags) in enumerate(blocks, start=1)
        ],
        coverage_diagnostics=[],
        missing_categories=[],
    )


def _paper_map(*, include_second_context: bool = True) -> dict:
    anchor_accounting = {
        f"ANCHOR::{block.evidence_id}": {
            "disposition": "mapped",
            "record_ids": [],
            "evidence_ids": [block.evidence_id],
            "explanation": "The local anchor was reviewed.",
        }
        for block in _inventory().evidence_blocks
    }
    formulations = [
        {
            "formulation_id": "FORM-Z9",
            "name": {"value": "Zephyr-9", "evidence_ids": ["E-SHARED-A"]},
            "components": [
                {
                    "component_id": "COMP-A",
                    "identity": {
                        "value": "amphiphile A",
                        "evidence_ids": ["E-SHARED-A"],
                    },
                    "role": {
                        "value": "ionizable lipid",
                        "evidence_ids": ["E-SHARED-A"],
                    },
                }
            ],
            "ratios": [
                {"value": "45:40:12:3", "evidence_ids": ["E-SHARED-A"]}
            ],
            "ratio_bases": [
                {"value": "molar", "evidence_ids": ["E-SHARED-A"]}
            ],
        },
        {
            "formulation_id": "FORM-N4",
            "name": {"value": "Nimbus-4", "evidence_ids": ["E-SHARED-B"]},
            "components": [],
            "ratios": [{"value": "3:2", "evidence_ids": ["E-SHARED-B"]}],
            "ratio_bases": [
                {"value": "mass", "evidence_ids": ["E-SHARED-B"]}
            ],
        },
    ]
    payloads = [
        {
            "payload_id": "PAY-COBALT",
            "identity": {
                "value": "cobalt luciferase RNA",
                "evidence_ids": ["E-PAYLOAD-A"],
            },
            "role": {
                "value": "reporter",
                "evidence_ids": ["E-PAYLOAD-A"],
            },
        },
        {
            "payload_id": "PAY-AMBER",
            "identity": {
                "value": "amber antisense RNA",
                "evidence_ids": ["E-PAYLOAD-B"],
            },
            "role": {
                "value": "therapeutic",
                "evidence_ids": ["E-PAYLOAD-B"],
            },
        },
    ]

    def provisional(
        context_id: str,
        *,
        formulation_id: str,
        payload_id: str,
        dose: float,
        dose_unit: str,
        route: str,
        species: str,
        model: str,
        cell: str,
        timepoint: float,
        timepoint_unit: str,
        joint: str,
        outcome: str,
        organ: str,
    ) -> dict:
        return {
            "provisional_context_id": context_id,
            "formulation_id": formulation_id,
            "payload_id": payload_id,
            "dose": {"value": dose, "evidence_ids": [joint]},
            "dose_unit": {"value": dose_unit, "evidence_ids": [joint]},
            "route": {"value": route, "evidence_ids": [joint]},
            "species": {"value": species, "evidence_ids": [joint]},
            "experimental_model": {"value": model, "evidence_ids": [joint]},
            "recipient_cell": {"value": cell, "evidence_ids": [joint]},
            "organ": {"value": organ, "evidence_ids": [joint]},
            "timepoint": {"value": timepoint, "evidence_ids": [joint]},
            "timepoint_unit": {
                "value": timepoint_unit,
                "evidence_ids": [joint],
            },
            "joint_evidence_ids": [joint],
            "outcome_evidence_ids": [outcome],
            "pairing_metadata": None,
        }

    contexts = [
        provisional(
            "CTX-STELLATE-LOW",
            formulation_id="FORM-Z9",
            payload_id="PAY-COBALT",
            dose=0.4,
            dose_unit="mg/kg",
            route="infusion",
            species="ferret",
            model="fibrotic ferret",
            cell="stellate-like cell",
            timepoint=8,
            timepoint_unit="hour",
            joint="E-JOINT-1",
            outcome="E-OUT-1",
            organ="liver",
        ),
        provisional(
            "CTX-STELLATE-HIGH",
            formulation_id="FORM-Z9",
            payload_id="PAY-COBALT",
            dose=0.9,
            dose_unit="mg/kg",
            route="infusion",
            species="ferret",
            model="fibrotic ferret",
            cell="stellate-like cell",
            timepoint=20,
            timepoint_unit="hour",
            joint="E-JOINT-2",
            outcome="E-OUT-2",
            organ="liver",
        ),
    ]
    if include_second_context:
        contexts.append(
            provisional(
                "CTX-SINUSOIDAL",
                formulation_id="FORM-N4",
                payload_id="PAY-AMBER",
                dose=2,
                dose_unit="µg/mL",
                route="culture application",
                species="canine",
                model="canine organoid",
                cell="sinusoidal-like cell",
                timepoint=2,
                timepoint_unit="day",
                joint="E-JOINT-3",
                outcome="E-OUT-3",
                organ="liver organoid",
            )
        )
    return {
        "paper_map_version": "full-paper-map-1.0.0",
        "paper_id": "SYNTH-77",
        "formulations": formulations,
        "payloads": payloads,
        "common_routes": [
            {"value": "infusion", "evidence_ids": ["E-JOINT-1"]}
        ],
        "common_species": [
            {"value": "ferret", "evidence_ids": ["E-JOINT-1"]}
        ],
        "common_models": [
            {"value": "fibrotic ferret", "evidence_ids": ["E-JOINT-1"]}
        ],
        "recipient_contexts": [
            {
                "context_id": "RECIP-STELLATE",
                "recipient_cell": {
                    "value": "stellate-like cell",
                    "evidence_ids": ["E-JOINT-1"],
                },
                "organ": {"value": "liver", "evidence_ids": ["E-JOINT-1"]},
            }
        ],
        "provisional_experiment_contexts": contexts,
        "anchor_accounting": anchor_accounting,
        "unresolved_items": [],
    }


def _reported(value, evidence_id: str) -> dict:
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": [evidence_id],
        "missing_reason": None,
    }


def _missing(reason: str = "Not required for this synthetic arm.") -> dict:
    return {
        "value": None,
        "status": "missing",
        "evidence_ids": [],
        "missing_reason": reason,
    }


def _valid_context_response(task) -> dict:
    formulation_evidence = task.shared_formulations[0].name.evidence_ids[0]
    formulations = [
        {
            "formulation_id": formulation.formulation_id,
            "formulation_name": _reported(
                formulation.name.value,
                formulation.name.evidence_ids[0],
            ),
            "composition": _reported(
                "reported shared composition",
                formulation.name.evidence_ids[0],
            ),
            "composition_basis": _reported(
                formulation.ratio_bases[0].value,
                formulation.ratio_bases[0].evidence_ids[0],
            ),
            "np_ratio": _missing(),
        }
        for formulation in task.shared_formulations
    ]
    experiments = []
    outcomes = []
    accounting = {}
    candidate_outcomes = {}
    for index, candidate in enumerate(task.candidates, start=1):
        evidence_id = candidate.joint_evidence_ids[0]
        outcome_evidence_id = candidate.outcome_evidence_ids[0]
        experiment_id = f"EXP-{index}"
        outcome_id = f"OUT-{index}"
        experiments.append(
            {
                "experiment_id": experiment_id,
                "formulation_id": candidate.formulation_id,
                "payload_type": _reported("RNA", evidence_id),
                "payload_name": _reported(candidate.payload, evidence_id),
                "payload_role": _reported("reporter", evidence_id),
                "encoded_product": _missing(),
                "molecular_target": _missing(),
                "delivery_recipient_cell": _reported(
                    candidate.recipient_cell,
                    evidence_id,
                ),
                "therapeutic_target_cell": _missing(),
                "tissue_or_organ": _reported(candidate.organ, evidence_id),
                "species": _reported(candidate.species, evidence_id),
                "experimental_model": _reported(
                    candidate.experimental_model,
                    evidence_id,
                ),
                "disease_model": _missing(),
                "experimental_context": _reported("in_vivo", evidence_id),
                "dose": _reported(candidate.dose, evidence_id),
                "dose_unit": _reported(candidate.dose_unit, evidence_id),
                "route": _reported(candidate.route, evidence_id),
                "timepoint": _reported(candidate.timepoint, evidence_id),
                "timepoint_unit": _reported(
                    candidate.timepoint_unit,
                    evidence_id,
                ),
            }
        )
        outcomes.append(
            {
                "outcome_id": outcome_id,
                "experiment_id": experiment_id,
                "assay": _reported("signal assay", outcome_evidence_id),
                "endpoint": _reported("recipient signal", outcome_evidence_id),
                "comparator": _missing(),
                "outcome_value": _missing(),
                "outcome_unit": _missing(),
                "qualitative_outcome": _reported(
                    "changed relative to control",
                    outcome_evidence_id,
                ),
            }
        )
        accounting[candidate.candidate_id] = {
            "disposition": "extracted",
            "linked_experiment_ids": [experiment_id],
            "linked_outcome_ids": [outcome_id],
            "evidence_ids": [evidence_id, outcome_evidence_id],
            "reason_code": "directly_reported",
            "explanation": "The arm and outcome are directly reported.",
        }
        candidate_outcomes[candidate.candidate_id] = {
            "candidate_id": candidate.candidate_id,
            "experiment_id": candidate.experiment_id,
            "foundational_outcomes": [
                {
                    "assertion_type": "foundational",
                    "direction": "present",
                    "subject": candidate.recipient_cell,
                    "comparator": None,
                    "raw_text": "Reporter signal was present.",
                    "value": None,
                    "unit": None,
                    "numeric_provenance": "not_reported",
                    "evidence_ids": [outcome_evidence_id],
                }
            ],
            "comparative_outcomes": [],
            "exact_measurements": [],
        }
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": task.paper_id,
        "eligibility": {
            "decision": "eligible",
            "reason_codes": [
                "ORIGINAL_EXPERIMENT",
                "IDENTIFIABLE_LNP",
                "SUPPORTED_PAYLOAD",
                "TARGET_CELL_EVIDENCE",
                "USABLE_FORMULATION_OUTCOME_LINKAGE",
            ],
            "evidence_ids": [formulation_evidence],
            "explanation": "Synthetic eligible study.",
        },
        "formulations": formulations,
        "components": [],
        "experiments": experiments,
        "outcomes": outcomes,
        "unresolved_items": [],
        "context_candidate_accounting": accounting,
        "candidate_outcomes": candidate_outcomes,
    }


def _error_codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def _assert_closed_strict_objects(value) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" and "properties" in value:
            assert value.get("additionalProperties") is False
            assert set(value.get("required", [])) == set(value["properties"])
        for child in value.values():
            _assert_closed_strict_objects(child)
    elif isinstance(value, list):
        for child in value:
            _assert_closed_strict_objects(child)


def test_paper_map_request_has_exact_dynamic_anchor_accounting() -> None:
    inventory = _inventory()

    prepared = build_paper_map_request(
        inventory,
        model="local-synthetic-model",
        token_budget=100_000,
    )

    anchor_ids = [anchor.anchor_id for anchor in prepared.anchor_candidates]
    accounting = prepared.response_schema["properties"]["anchor_accounting"]
    assert accounting["required"] == anchor_ids
    assert set(accounting["properties"]) == set(anchor_ids)
    assert accounting["additionalProperties"] is False
    assert prepared.request["model"] == "local-synthetic-model"
    assert prepared.estimated_input_tokens <= prepared.token_budget
    assert {row.evidence_id for row in prepared.evidence} == {
        block.evidence_id for block in inventory.evidence_blocks
    }


def test_prepared_response_schemas_are_recursively_strict() -> None:
    prepared = build_paper_map_request(
        _inventory(),
        model="local-synthetic-model",
        token_budget=100_000,
    )
    context_task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]

    _assert_closed_strict_objects(prepared.response_schema)
    _assert_closed_strict_objects(context_task.response_schema)


def test_paper_map_request_rejects_budget_that_cannot_hold_all_anchors() -> None:
    with pytest.raises(ValueError, match="token_budget"):
        build_paper_map_request(
            _inventory(),
            model="local-synthetic-model",
            token_budget=100,
        )


def test_context_tasks_use_only_supported_candidates_and_exact_evidence() -> None:
    inventory = _inventory()
    paper_map = PaperMapResponse.model_validate(_paper_map())

    tasks = build_context_tasks(paper_map, inventory, token_budget=100_000)

    assert {candidate.candidate_id for task in tasks for candidate in task.candidates} == {
        "CTX-STELLATE-LOW",
        "CTX-STELLATE-HIGH",
        "CTX-SINUSOIDAL",
    }
    assert len(tasks) == 2
    for task in tasks:
        candidate_ids = [candidate.candidate_id for candidate in task.candidates]
        schema = task.response_schema["properties"][
            "context_candidate_accounting"
        ]
        assert schema["required"] == candidate_ids
        assert set(schema["properties"]) == set(candidate_ids)
        assert schema["additionalProperties"] is False
        outcomes_schema = task.response_schema["properties"][
            "candidate_outcomes"
        ]
        assert outcomes_schema["required"] == candidate_ids
        assert set(outcomes_schema["properties"]) == set(candidate_ids)
        assert outcomes_schema["additionalProperties"] is False
        assert task.estimated_input_tokens <= task.token_budget
        allowed = set().union(
            *(
                set(task.candidate_evidence_envelopes[candidate_id])
                for candidate_id in candidate_ids
            )
        )
        assert {row.evidence_id for row in task.evidence} == allowed
        assert "E-UNRELATED" not in allowed


def test_context_task_identity_changes_with_response_schema(
    monkeypatch,
) -> None:
    baseline = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    original_builder = full_paper_tasks.build_context_response_schema

    def changed_schema(candidates):
        schema = original_builder(candidates)
        schema["$comment"] = "contract changed"
        return schema

    monkeypatch.setattr(
        full_paper_tasks,
        "build_context_response_schema",
        changed_schema,
    )

    changed = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]

    assert baseline.context_task_version == "full-paper-context-task-1.2.0"
    assert changed.task_id != baseline.task_id


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("candidate_id",), "CTX-INVENTED"),
        (("experiment_id",), "EXP-INVENTED"),
        (
            ("foundational_outcomes", 0, "assertion_type"),
            "comparison",
        ),
        (
            ("exact_measurements", 0, "numeric_provenance"),
            "graph_estimated",
        ),
    ],
)
def test_candidate_outcome_schema_enforces_local_semantics(
    path,
    replacement,
) -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    candidate = task.candidates[0]
    response = _valid_context_response(task)
    bundle = deepcopy(response["candidate_outcomes"][candidate.candidate_id])
    bundle["exact_measurements"] = [
        {
            "assertion_type": "measurement",
            "direction": "reported",
            "subject": "recipient signal",
            "comparator": None,
            "raw_text": "Signal was exactly 40%.",
            "value": 40,
            "unit": "%",
            "numeric_provenance": "exact_reported",
            "evidence_ids": [candidate.outcome_evidence_ids[0]],
        }
    ]
    bundle_ref = task.response_schema["properties"]["candidate_outcomes"][
        "properties"
    ][candidate.candidate_id]
    bundle_schema = {
        "$ref": bundle_ref["$ref"],
        "$defs": task.response_schema["$defs"],
    }
    validator = Draft202012Validator(bundle_schema)
    validator.validate(bundle)
    target = bundle
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(JsonSchemaValidationError):
        validator.validate(bundle)


def test_unlabeled_graph_number_cannot_be_exact() -> None:
    with pytest.raises(ValidationError):
        CandidateOutcomeBundle(
            candidate_id="C-1",
            experiment_id="EXP-1",
            foundational_outcomes=[],
            comparative_outcomes=[],
            exact_measurements=[
                OutcomeAssertion(
                    assertion_type="measurement",
                    direction="reported",
                    subject="C-1",
                    comparator=None,
                    raw_text="bar appears near 40",
                    value=40,
                    unit="%",
                    numeric_provenance="graph_estimated",
                    evidence_ids=["FIG-2"],
                )
            ],
        )


@pytest.mark.parametrize(
    ("numeric_provenance", "value"),
    [("exact_reported", None), ("not_reported", 40)],
)
def test_outcome_assertion_value_matches_numeric_provenance(
    numeric_provenance,
    value,
) -> None:
    with pytest.raises(ValidationError):
        OutcomeAssertion(
            assertion_type="measurement",
            direction="reported",
            subject="recipient signal",
            comparator=None,
            raw_text="A numeric result was discussed.",
            value=value,
            unit="%",
            numeric_provenance=numeric_provenance,
            evidence_ids=["E-OUT-1"],
        )


def test_context_task_packing_starts_new_task_before_budget_overflow() -> None:
    inventory = _inventory(long_outcomes=True)
    paper_map = PaperMapResponse.model_validate(
        _paper_map(include_second_context=False)
    )

    tasks = build_context_tasks(paper_map, inventory, token_budget=18_000)

    assert len(tasks) == 2
    assert all(len(task.candidates) == 1 for task in tasks)
    assert all(task.estimated_input_tokens <= 18_000 for task in tasks)


def test_context_tasks_reject_context_without_joint_pairing_evidence() -> None:
    paper_map = _paper_map(include_second_context=False)
    paper_map["provisional_experiment_contexts"][0]["joint_evidence_ids"] = []

    with pytest.raises(ValueError, match="joint evidence|pairing metadata"):
        build_context_tasks(paper_map, _inventory(), token_budget=100_000)


def test_valid_context_response_passes_compact_and_candidate_validation() -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]

    report = validate_context_response(_valid_context_response(task), task)

    assert report.status == "valid"
    assert report.findings == []
    candidate_id = task.candidates[0].candidate_id
    accepted = report.accepted_candidate_outcomes[candidate_id]
    assert isinstance(accepted, CandidateOutcomeBundle)
    assert accepted.experiment_id == task.candidates[0].experiment_id


@pytest.mark.parametrize("mutation", ["missing", "invented"])
def test_context_response_rejects_inexact_candidate_accounting(mutation) -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    if mutation == "missing":
        response["context_candidate_accounting"].pop("CTX-STELLATE-HIGH")
        expected_code = "missing_candidate_ids"
    else:
        response["context_candidate_accounting"]["CTX-INVENTED"] = deepcopy(
            response["context_candidate_accounting"]["CTX-STELLATE-LOW"]
        )
        expected_code = "invented_candidate_ids"

    report = validate_context_response(response, task)

    assert report.status == "invalid"
    assert expected_code in _error_codes(report)


@pytest.mark.parametrize("mutation", ["missing", "invented"])
def test_context_response_rejects_inexact_candidate_outcomes(mutation) -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    if mutation == "missing":
        response["candidate_outcomes"].pop("CTX-STELLATE-HIGH")
        expected_code = "missing_candidate_outcome_ids"
    else:
        response["candidate_outcomes"]["CTX-INVENTED"] = deepcopy(
            response["candidate_outcomes"]["CTX-STELLATE-LOW"]
        )
        expected_code = "invented_candidate_outcome_ids"

    report = validate_context_response(response, task)

    assert report.status == "invalid"
    assert report.accepted_candidate_outcomes == {}
    assert expected_code in _error_codes(report)


def test_context_response_rejects_wrong_record_links() -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    response["context_candidate_accounting"]["CTX-STELLATE-LOW"][
        "linked_outcome_ids"
    ] = ["OUT-2"]

    report = validate_context_response(response, task)

    assert "outcome_experiment_link_mismatch" in _error_codes(report)


def test_context_response_rejects_incompatible_outcome_reuse() -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    response["context_candidate_accounting"]["CTX-STELLATE-HIGH"][
        "linked_outcome_ids"
    ] = ["OUT-1"]
    response["context_candidate_accounting"]["CTX-STELLATE-HIGH"][
        "linked_experiment_ids"
    ] = ["EXP-1"]

    report = validate_context_response(response, task)

    assert "outcome_reused_across_incompatible_candidates" in _error_codes(report)


def test_context_response_rejects_evidence_outside_candidate_envelope() -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    response["context_candidate_accounting"]["CTX-STELLATE-LOW"][
        "evidence_ids"
    ] = ["E-JOINT-2"]

    report = validate_context_response(response, task)

    assert "candidate_evidence_outside_envelope" in _error_codes(report)


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected_code"),
    [
        ("candidate_id", "CTX-INVENTED", "candidate_outcome_id_mismatch"),
        (
            "experiment_id",
            "EXP-INVENTED",
            "candidate_outcome_experiment_id_mismatch",
        ),
    ],
)
def test_context_response_rejects_wrong_outcome_bundle_identity(
    field_name,
    replacement,
    expected_code,
) -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    response["candidate_outcomes"]["CTX-STELLATE-LOW"][field_name] = replacement

    report = validate_context_response(response, task)

    assert expected_code in _error_codes(report)


def test_context_response_rejects_outcome_assertion_evidence_outside_envelope(
) -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    response["candidate_outcomes"]["CTX-STELLATE-LOW"][
        "foundational_outcomes"
    ][0]["evidence_ids"] = ["E-JOINT-2"]

    report = validate_context_response(response, task)

    assert "candidate_outcome_evidence_outside_envelope" in _error_codes(report)


def test_context_response_rejects_unaccounted_returned_experiment() -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    unaccounted = deepcopy(response["experiments"][0])
    unaccounted["experiment_id"] = "EXP-UNACCOUNTED"
    response["experiments"].append(unaccounted)

    report = validate_context_response(response, task)

    finding = next(
        row
        for row in report.findings
        if row.code == "unaccounted_returned_experiment_ids"
    )
    assert report.status == "invalid"
    assert finding.location == ["experiments"]
    assert "EXP-UNACCOUNTED" in finding.message


def test_context_response_rejects_unaccounted_returned_outcome() -> None:
    task = build_context_tasks(
        _paper_map(include_second_context=False),
        _inventory(),
        token_budget=100_000,
    )[0]
    response = _valid_context_response(task)
    unaccounted = deepcopy(response["outcomes"][0])
    unaccounted["outcome_id"] = "OUT-UNACCOUNTED"
    response["outcomes"].append(unaccounted)

    report = validate_context_response(response, task)

    finding = next(
        row
        for row in report.findings
        if row.code == "unaccounted_returned_outcome_ids"
    )
    assert report.status == "invalid"
    assert finding.location == ["outcomes"]
    assert "OUT-UNACCOUNTED" in finding.message
