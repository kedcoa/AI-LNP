import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import src.extraction.build_v12_structural_repair_tasks as repair_builder
from src.extraction.compact_contracts import ExperimentRecord, OutcomeRecord
from src.extraction.compact_validation import ValidationFinding, ValidationReport
from src.extraction.missing_record_contracts import (
    MissingRecordFragment,
    MissingRecordTask,
)
from src.extraction.repair_contracts import RepairEvidence
from src.extraction.run_missing_record_repair import (
    PROMPT as TEXT_PROMPT,
    PROMPT_VERSION as TEXT_PROMPT_VERSION,
    build_openai_request,
    fingerprint,
    run,
    validate_response,
)
from src.extraction.run_missing_record_vision import (
    PROMPT as VISION_PROMPT,
)
from src.extraction.route_compact_findings import route


def _reported(value):
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": ["E-1"],
        "missing_reason": None,
    }


@pytest.mark.parametrize(
    "required_text",
    [
        "already_represented",
        "recovered_existing_experiment",
        "recovered_new_experiment",
        "unresolved",
        "provisional experiment context is not a binding target",
        "distinct experiments require distinct outcomes",
        "preserve the comparator",
    ],
)
def test_text_and_vision_prompts_define_resolution_semantics(required_text):
    assert required_text in TEXT_PROMPT
    assert required_text in VISION_PROMPT


def test_text_prompt_uses_v1_2_version():
    assert TEXT_PROMPT_VERSION == "missing-record-repair-prompt-1.2.0"


def _missing():
    return {
        "value": None,
        "status": "missing",
        "evidence_ids": [],
        "missing_reason": "Not reported.",
    }


def _experiment():
    return ExperimentRecord(
        experiment_id="E2",
        formulation_id="F1",
        payload_type=_reported("mRNA"),
        payload_name=_reported("GFP mRNA"),
        encoded_product=_reported("GFP"),
        molecular_target=_missing(),
        delivery_recipient_cell=_reported("hepatocyte"),
        therapeutic_target_cell=_reported("hepatocyte"),
        tissue_or_organ=_reported("liver"),
        species=_reported("mouse"),
        disease_model=_missing(),
        experimental_context=_reported("in_vivo"),
        dose=_missing(),
        dose_unit=_missing(),
        route=_missing(),
        timepoint=_missing(),
        timepoint_unit=_missing(),
    )


def _outcome():
    return OutcomeRecord(
        outcome_id="O2",
        experiment_id="E2",
        assay=_reported("microscopy"),
        endpoint=_reported("GFP expression"),
        comparator=_missing(),
        outcome_value=_reported(80.0),
        outcome_unit=_reported("%"),
        qualitative_outcome=_reported("More than 80% expressed GFP."),
    )


def _outcome_for(outcome_id, experiment_id):
    outcome = _outcome()
    outcome.outcome_id = outcome_id
    outcome.experiment_id = experiment_id
    return outcome


def _task():
    return MissingRecordTask(
        task_version="missing-record-task-1.0.0",
        paper_id="GP-X",
        route_ids=["RT-1", "RT-2"],
        candidate_ids=["OC-1", "OC-2"],
        evidence=[
            RepairEvidence(evidence_id="E-1", text="More than 80%.", source_ids=["S1"])
        ],
        existing_formulation_ids=["F1"],
        existing_experiment_ids=["E1"],
        existing_outcome_ids=["O1"],
        permitted_new_experiments=1,
        permitted_new_outcomes=2,
        source_result_sha256="a" * 64,
        source_inventory_sha256="b" * 64,
        task_checksum="c" * 64,
    )


def _experiment_summary(experiment_id):
    return {
        "experiment_id": experiment_id,
        "formulation_id": "F1",
        "payload_type": "mRNA",
        "payload_name": "GFP mRNA",
        "encoded_product": "GFP",
        "molecular_target": None,
        "delivery_recipient_cell": "hepatocyte",
        "therapeutic_target_cell": "hepatocyte",
        "tissue_or_organ": "liver",
        "species": "mouse",
        "disease_model": None,
        "experimental_context": "in_vivo",
        "dose": None,
        "dose_unit": None,
        "route": None,
        "timepoint": None,
        "timepoint_unit": None,
        "outcome_endpoints": ["GFP expression"],
        "comparator_context": [],
    }


def _outcome_summary(outcome_id, experiment_id):
    return {
        "outcome_id": outcome_id,
        "experiment_id": experiment_id,
        "assay": "microscopy",
        "endpoint": "GFP expression",
        "comparator": None,
        "qualitative_outcome": "More than 80% expressed GFP.",
    }


def test_compact_summaries_project_reported_values_without_evidence_wrappers():
    result = {
        "experiments": [_experiment().model_dump(mode="json")],
        "outcomes": [_outcome().model_dump(mode="json")],
    }
    experiment_summary = repair_builder.compact_experiment_summaries(result)[
        0
    ]
    outcome_summary = repair_builder.compact_outcome_summaries(result)[0]
    assert experiment_summary.payload_name == "GFP mRNA"
    assert experiment_summary.outcome_endpoints == ["GFP expression"]
    assert experiment_summary.comparator_context == []
    assert outcome_summary.assay == "microscopy"
    assert outcome_summary.qualitative_outcome == (
        "More than 80% expressed GFP."
    )
    assert "evidence_ids" not in experiment_summary.model_dump_json()
    assert "evidence_ids" not in outcome_summary.model_dump_json()


def test_worst_case_output_estimate_accounts_for_candidates_and_experiments():
    task = _v12_task(
        candidate_ids=["OC-1", "OC-2"],
        permitted_new_experiments=1,
    )
    assert repair_builder.estimate_worst_case_output_tokens(task) == 2_400


def _v12_task_payload(**overrides):
    payload = _task().model_dump(mode="json")
    payload.update(
        {
            "task_version": "missing-record-task-1.2.0",
            "candidate_ids": ["OC-1", "OC-2"],
            "existing_experiment_summaries": [_experiment_summary("E1")],
            "existing_outcome_summaries": [],
            "experiment_context": {
                "provisional_experiment_id": "E2",
                "label": "GFP expression experiment",
                "anchors": [
                    {
                        "anchor_type": "assay",
                        "value": "microscopy",
                        "evidence_ids": ["E-1"],
                    }
                ],
            },
        }
    )
    payload.update(overrides)
    if "candidate_facts" not in overrides:
        payload["candidate_facts"] = [
            {
                "candidate_id": candidate_id,
                "subject_text": "hepatocyte",
                "predicate": "expresses",
                "object_text": "GFP",
                "endpoint_text": "GFP expression",
                "qualitative_result": "More than 80% expressed GFP.",
                "numeric_value": 80.0,
                "value_text": "More than 80%",
                "unit": "%",
                "polarity": "positive",
                "evidence_ids": ["E-1"],
            }
            for candidate_id in payload["candidate_ids"]
        ]
    return payload


def _v12_task(**overrides):
    return MissingRecordTask.model_validate(_v12_task_payload(**overrides))


def _resolution(candidate_id, **overrides):
    payload = {
        "candidate_id": candidate_id,
        "status": "recovered_existing_experiment",
        "outcome_ids": ["O2"],
        "experiment_ids": ["E1"],
        "reason": None,
    }
    payload.update(overrides)
    return payload


def _fragment(
    *,
    recovered=None,
    unresolved=None,
    experiments=None,
    outcomes=None,
    candidate_resolutions=None,
    disposition=None,
):
    recovered = ["OC-1"] if recovered is None else recovered
    unresolved = ["OC-2"] if unresolved is None else unresolved
    experiments = [] if experiments is None else experiments
    outcomes = [_outcome_for("O2", "E1")] if outcomes is None else outcomes
    candidate_resolutions = (
        [
            _resolution("OC-1"),
            _resolution("OC-2", status="unresolved", outcome_ids=[], experiment_ids=[], reason="Ambiguous."),
        ]
        if candidate_resolutions is None
        else candidate_resolutions
    )
    return MissingRecordFragment(
        disposition=("recovered" if recovered else "unresolved")
        if disposition is None
        else disposition,
        recovered_candidate_ids=recovered,
        unresolved_candidate_ids=unresolved,
        experiments=experiments,
        outcomes=outcomes,
        unresolved_reason="Ambiguous." if unresolved else None,
        candidate_resolutions=candidate_resolutions,
    )


def _approved_request(
    tmp_path,
    task,
    *,
    max_output_tokens=4_000,
    estimated_input_tokens=100,
    paper_id=None,
    route="text",
    task_checksum=None,
):
    request = build_openai_request(
        task,
        model="test",
        max_output_tokens=max_output_tokens,
    )
    preflight_root = tmp_path / f"preflight-{max_output_tokens}"
    request_path = preflight_root / "GP-X/text/task.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
    unsigned_manifest = {
        "preflight_version": "missing-record-request-preflight-1.2.0",
        "local_preflight_passed": True,
        "requests": [
            {
                "paper_id": paper_id or task.paper_id,
                "route": route,
                "task_checksum": task_checksum or task.task_checksum,
                "request_path": str(request_path),
                "request_sha256": request_sha256,
                "estimated_input_tokens": estimated_input_tokens,
            }
        ],
    }
    manifest = {
        **unsigned_manifest,
        "manifest_checksum": hashlib.sha256(
            json.dumps(
                unsigned_manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }
    (preflight_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        request=request,
        path=request_path,
        sha256=request_sha256,
    )


def _api_response(output_text):
    return SimpleNamespace(
        id="resp-test",
        model="test",
        output_text=output_text,
        usage=None,
        model_dump=lambda mode: {
            "id": "resp-test",
            "model": "test",
            "output_text": output_text,
        },
    )


class RecordingClient:
    def __init__(self, output_text):
        self.calls = []
        self.responses = SimpleNamespace(create=self.create)
        self.output_text = output_text

    def create(self, **request):
        self.calls.append(request)
        return _api_response(self.output_text)


class ExplodingClient:
    def __init__(self):
        self.calls = 0
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.calls += 1
        raise AssertionError("provider must not be used")


def test_callable_runner_refuses_before_provider_use_without_confirmation(
    tmp_path,
):
    client = ExplodingClient()

    with pytest.raises(PermissionError, match="confirm_paid_call"):
        run(
            _v12_task(),
            client=client,
            approved_request_path=tmp_path / "request.json",
            approved_request_sha256="0" * 64,
            confirm_paid_call=False,
            output_root=tmp_path / "runs",
        )

    assert client.calls == 0
    assert not (tmp_path / "runs").exists()


def test_runner_sends_exact_approved_dictionary(tmp_path):
    task = _v12_task()
    approved = _approved_request(tmp_path, task)
    client = RecordingClient(_fragment().model_dump_json())

    run(
        task,
        client=client,
        approved_request_path=approved.path,
        approved_request_sha256=approved.sha256,
        confirm_paid_call=True,
        output_root=tmp_path / "runs",
    )

    assert client.calls == [json.loads(approved.path.read_bytes())]


@pytest.mark.parametrize(
    ("row_overrides", "message"),
    [
        ({"task_checksum": "other-task"}, "task checksum"),
        ({"paper_id": "GP-OTHER"}, "paper"),
        ({"route": "vision"}, "route"),
    ],
)
def test_text_runner_rejects_signed_request_for_other_scope(
    tmp_path,
    row_overrides,
    message,
):
    task = _v12_task()
    approved = _approved_request(
        tmp_path,
        task,
        **row_overrides,
    )
    client = ExplodingClient()

    with pytest.raises(ValueError, match=message):
        run(
            task,
            client=client,
            approved_request_path=approved.path,
            approved_request_sha256=approved.sha256,
            confirm_paid_call=True,
            output_root=tmp_path / "runs",
        )

    assert client.calls == 0
    assert not (tmp_path / "runs").exists()


def test_text_runner_rejects_signed_request_above_input_token_cap(
    tmp_path,
):
    task = _v12_task()
    approved = _approved_request(
        tmp_path,
        task,
        estimated_input_tokens=6_001,
    )
    client = ExplodingClient()

    with pytest.raises(ValueError, match="6,000"):
        run(
            task,
            client=client,
            approved_request_path=approved.path,
            approved_request_sha256=approved.sha256,
            confirm_paid_call=True,
            output_root=tmp_path / "runs",
        )

    assert client.calls == 0
    assert not (tmp_path / "runs").exists()


def test_cache_fingerprint_includes_approved_output_limit(tmp_path):
    task = _v12_task()
    approved = _approved_request(tmp_path, task)
    changed = _approved_request(
        tmp_path,
        task,
        max_output_tokens=4_001,
    )

    baseline = fingerprint(
        task,
        approved_request_sha256="a" * 64,
        approved_request=approved.request,
    )
    assert baseline != fingerprint(
        task,
        approved_request_sha256="a" * 64,
        approved_request=changed.request,
    )
    changed_model = {
        **approved.request,
        "model": "different-model",
    }
    assert baseline != fingerprint(
        task,
        approved_request_sha256="a" * 64,
        approved_request=changed_model,
    )
    assert baseline != fingerprint(
        task,
        approved_request_sha256="b" * 64,
        approved_request=approved.request,
    )
    changed_task = task.model_copy(
        update={"task_checksum": "different-task"}
    )
    assert baseline != fingerprint(
        changed_task,
        approved_request_sha256="a" * 64,
        approved_request=approved.request,
    )


def test_complete_cache_hit_does_not_require_paid_call_confirmation(
    tmp_path,
):
    task = _v12_task()
    approved = _approved_request(tmp_path, task)
    output_root = tmp_path / "runs"
    first_client = RecordingClient(_fragment().model_dump_json())
    run(
        task,
        client=first_client,
        approved_request_path=approved.path,
        approved_request_sha256=approved.sha256,
        confirm_paid_call=True,
        output_root=output_root,
    )
    cache_client = ExplodingClient()

    result = run(
        task,
        client=cache_client,
        approved_request_path=approved.path,
        approved_request_sha256=approved.sha256,
        confirm_paid_call=False,
        output_root=output_root,
    )

    assert result["cache_hit"] is True
    assert result["paid_api_requests_this_run"] == 0
    assert cache_client.calls == 0


def test_missing_record_response_accounts_for_every_candidate():
    result = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=["OC-1"],
        unresolved_candidate_ids=["OC-2"],
        experiments=[_experiment()],
        outcomes=[_outcome()],
        unresolved_reason="OC-2 requires a figure.",
    )
    validate_response(result, _task())


def test_missing_record_response_cannot_silently_drop_candidate():
    result = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=["OC-1"],
        unresolved_candidate_ids=[],
        experiments=[_experiment()],
        outcomes=[_outcome()],
        unresolved_reason=None,
    )
    with pytest.raises(ValueError, match="every candidate"):
        validate_response(result, _task())


def test_missing_record_response_rejects_existing_id_collision():
    outcome = _outcome()
    outcome.outcome_id = "O1"
    result = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=["OC-1"],
        unresolved_candidate_ids=["OC-2"],
        experiments=[_experiment()],
        outcomes=[outcome],
        unresolved_reason="OC-2 requires a figure.",
    )
    with pytest.raises(ValueError, match="existing outcome"):
        validate_response(result, _task())


def test_missing_record_response_rejects_made_up_evidence():
    outcome = _outcome()
    outcome.endpoint.evidence_ids = ["E-MADE-UP"]
    result = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=["OC-1"],
        unresolved_candidate_ids=["OC-2"],
        experiments=[_experiment()],
        outcomes=[outcome],
        unresolved_reason="OC-2 requires a figure.",
    )
    with pytest.raises(ValueError, match="unknown evidence"):
        validate_response(result, _task())


def test_structural_task_requires_facts_for_every_opaque_candidate():
    payload = _task().model_dump(mode="json")
    payload["task_version"] = "missing-record-task-1.1.0"
    with pytest.raises(ValueError, match="experiment_context"):
        MissingRecordTask.model_validate(payload)


def test_v12_task_requires_compact_existing_experiment_summaries():
    payload = _v12_task_payload()
    payload["existing_experiment_summaries"] = []
    with pytest.raises(ValueError, match="summary"):
        MissingRecordTask.model_validate(payload)


def test_v12_task_requires_context_for_every_opaque_candidate():
    payload = _v12_task_payload()
    payload["experiment_context"] = None
    with pytest.raises(ValueError, match="experiment_context"):
        MissingRecordTask.model_validate(payload)


def test_v12_task_requires_facts_for_every_opaque_candidate():
    payload = _v12_task_payload()
    payload["candidate_facts"] = []
    with pytest.raises(ValueError, match="candidate_facts"):
        MissingRecordTask.model_validate(payload)


@pytest.mark.parametrize(
    ("outcome_summaries", "message"),
    [
        (
            [_outcome_summary("O1", "E1"), _outcome_summary("O1", "E1")],
            "unique",
        ),
        ([_outcome_summary("O-MADE-UP", "E1")], "existing_outcome_ids"),
        ([_outcome_summary("O1", "E-MADE-UP")], "existing experiment"),
    ],
)
def test_v12_task_requires_unique_known_outcome_summaries(
    outcome_summaries, message
):
    with pytest.raises(ValueError, match=message):
        _v12_task(
            existing_outcome_ids=["O1"],
            existing_outcome_summaries=outcome_summaries,
        )


def test_response_requires_one_resolution_for_every_candidate():
    response = _fragment(candidate_resolutions=[_resolution("OC-1")])
    with pytest.raises(ValueError, match="candidate resolution"):
        validate_response(response, _v12_task())


def test_one_candidate_may_resolve_to_distinct_experiment_linked_outcomes():
    validate_response(
        _fragment(
            recovered=["OC-1"],
            unresolved=[],
            outcomes=[
                _outcome_for("O2", "E1"),
                _outcome_for("O3", "E2"),
            ],
            candidate_resolutions=[
                _resolution(
                    "OC-1",
                    status="recovered_existing_experiment",
                    outcome_ids=["O2", "O3"],
                    experiment_ids=["E1", "E2"],
                )
            ],
        ),
        _v12_task(
            candidate_ids=["OC-1"],
            existing_experiment_ids=["E1", "E2"],
            existing_experiment_summaries=[
                _experiment_summary("E1"),
                _experiment_summary("E2"),
            ],
        ),
    )


def test_unresolved_resolution_cannot_reference_records():
    response = _fragment(
        recovered=[],
        unresolved=["OC-1", "OC-2"],
        outcomes=[],
        candidate_resolutions=[
            _resolution(
                "OC-1",
                status="unresolved",
                outcome_ids=[],
                experiment_ids=[],
                reason="Ambiguous.",
            ),
            _resolution(
                "OC-2",
                status="unresolved",
                outcome_ids=["O2"],
                experiment_ids=[],
                reason="Ambiguous.",
            ),
        ],
    )
    with pytest.raises(ValueError, match="unresolved"):
        validate_response(response, _v12_task())


def test_already_represented_resolution_requires_linked_existing_outcome_summary():
    response = _fragment(
        recovered=["OC-1"],
        unresolved=["OC-2"],
        outcomes=[],
        candidate_resolutions=[
            _resolution(
                "OC-1",
                status="already_represented",
                outcome_ids=["O1"],
                experiment_ids=["E2"],
            ),
            _resolution(
                "OC-2",
                status="unresolved",
                outcome_ids=[],
                experiment_ids=[],
                reason="Ambiguous.",
            ),
        ],
    )
    with pytest.raises(ValueError, match="outcome summary"):
        validate_response(
            response,
            _v12_task(
                existing_experiment_ids=["E1", "E2"],
                existing_experiment_summaries=[
                    _experiment_summary("E1"),
                    _experiment_summary("E2"),
                ],
                existing_outcome_ids=["O1"],
                existing_outcome_summaries=[_outcome_summary("O1", "E1")],
            ),
        )


def test_recovered_disposition_cannot_coexist_with_all_unresolved_resolutions():
    response = _fragment(
        recovered=[],
        unresolved=["OC-1", "OC-2"],
        outcomes=[],
        candidate_resolutions=[
            _resolution(
                "OC-1",
                status="unresolved",
                outcome_ids=[],
                experiment_ids=[],
                reason="Ambiguous.",
            ),
            _resolution(
                "OC-2",
                status="unresolved",
                outcome_ids=[],
                experiment_ids=[],
                reason="Ambiguous.",
            ),
        ],
        disposition="recovered",
    )
    with pytest.raises(ValueError, match="disposition"):
        validate_response(response, _v12_task())


def test_recovered_existing_experiment_requires_a_returned_outcome():
    response = _fragment(
        recovered=["OC-1"],
        unresolved=["OC-2"],
        outcomes=[],
        candidate_resolutions=[
            _resolution("OC-1", outcome_ids=["O1"], experiment_ids=["E1"]),
            _resolution(
                "OC-2",
                status="unresolved",
                outcome_ids=[],
                experiment_ids=[],
                reason="Ambiguous.",
            ),
        ],
    )
    with pytest.raises(ValueError, match="new outcome"):
        validate_response(
            response,
            _v12_task(
                existing_outcome_ids=["O1"],
                existing_outcome_summaries=[_outcome_summary("O1", "E1")],
            ),
        )


def test_recovered_new_experiment_requires_a_returned_outcome_for_that_experiment():
    response = _fragment(
        recovered=["OC-1"],
        unresolved=["OC-2"],
        experiments=[_experiment()],
        outcomes=[_outcome_for("O2", "E1")],
        candidate_resolutions=[
            _resolution(
                "OC-1",
                status="recovered_new_experiment",
                outcome_ids=["O2"],
                experiment_ids=["E1", "E2"],
            ),
            _resolution(
                "OC-2",
                status="unresolved",
                outcome_ids=[],
                experiment_ids=[],
                reason="Ambiguous.",
            ),
        ],
    )
    with pytest.raises(ValueError, match="new experiment"):
        validate_response(
            response,
            _v12_task(existing_outcome_ids=["O1"]),
        )


def test_whole_response_schema_failure_requires_first_call_not_field_repair():
    finding = ValidationFinding(
        finding_id="VF-schema",
        code="pydantic.literal_error",
        message="Wrong contract version",
        location=["contract_version"],
        record_collection=None,
        record_index=None,
        field_name=None,
        cited_evidence_ids=[],
        repairable=False,
    )
    decision = route(
        paper_id="GP-X",
        complexity_route="complex",
        validation=ValidationReport(
            paper_id="GP-X", status="invalid", findings=[finding]
        ),
        coverage=None,
        inventory=None,
    )
    assert decision.routes[0].route == "first_call_required"


def test_raw_response_is_persisted_before_invalid_json_is_parsed(tmp_path):
    response = SimpleNamespace(
        id="resp-test",
        model="test",
        output_text="truncated {",
        usage=None,
        model_dump=lambda mode: {
            "id": "resp-test",
            "model": "test",
            "output_text": "truncated {",
        },
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **request: response)
    )
    approved = _approved_request(tmp_path, _v12_task())

    with pytest.raises(ValidationError):
        run(
            _v12_task(),
            client=client,
            approved_request_path=approved.path,
            approved_request_sha256=approved.sha256,
            confirm_paid_call=True,
            output_root=tmp_path / "runs",
        )

    raw_paths = list((tmp_path / "runs").rglob("response.raw.json"))
    assert len(raw_paths) == 1
    assert "truncated {" in raw_paths[0].read_text(encoding="utf-8")
