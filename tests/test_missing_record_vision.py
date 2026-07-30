import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import src.extraction.build_v12_structural_repair_tasks as text_builder
import src.extraction.preflight_missing_record_repairs as preflight_module
from src.extraction.build_missing_record_vision_tasks import (
    build,
    build_for_run,
)
from src.extraction.missing_record_contracts import (
    MissingRecordFragment,
    MissingRecordVisionResponse,
)
from src.extraction.run_missing_record_vision import (
    PROMPT_VERSION,
    build_openai_request,
    load_task,
    run,
)
from tests.test_build_v12_structural_repair_tasks import _write_run
from tests.test_deterministic_coverage_v12 import candidate
from tests.test_missing_record_workflow import _v12_task


def _visual_task(tmp_path):
    crop_path = tmp_path / "accepted-figure.png"
    crop_path.write_bytes(b"\x89PNG\r\naccepted visual")
    crop_sha256 = hashlib.sha256(crop_path.read_bytes()).hexdigest()
    return build(
        text_task=_v12_task(
            candidate_ids=["OC-1"],
            candidate_facts=[
                {
                    "candidate_id": "OC-1",
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
            ],
        ),
        accepted_visual_claim={
            "evidence_id": "E-1",
            "object_id": "FIGURE-1",
            "image_path": str(crop_path),
            "image_sha256": crop_sha256,
            "claim": {"panel_or_cell": "A"},
            "support_text": "The printed panel reports GFP expression.",
        },
    )


def test_vision_prompt_uses_v1_2_version():
    assert PROMPT_VERSION == "missing-record-vision-prompt-1.2.0"


def _approved_vision_request(
    tmp_path,
    task,
    *,
    estimated_input_tokens=100,
    paper_id=None,
    route="vision",
    task_checksum=None,
):
    request = build_openai_request(task, model="test")
    preflight_root = tmp_path / "vision-preflight"
    request_path = preflight_root / "GP-X/vision/task.json"
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


def _valid_vision_response_json():
    fragment = MissingRecordFragment(
        disposition="unresolved",
        recovered_candidate_ids=[],
        unresolved_candidate_ids=["OC-1"],
        experiments=[],
        outcomes=[],
        unresolved_reason="Not resolved.",
        candidate_resolutions=[
            {
                "candidate_id": "OC-1",
                "status": "unresolved",
                "outcome_ids": [],
                "experiment_ids": [],
                "reason": "Not resolved.",
            }
        ],
    )
    return MissingRecordVisionResponse(
        fragment=fragment,
        value_status="not_resolved",
        panel_or_table_cell=None,
        visible_support="No exact printed value was resolved.",
        derivation=None,
        requires_human_review=False,
    ).model_dump_json()


class RecordingVisionClient:
    def __init__(self, output_text):
        self.calls = []
        self.responses = SimpleNamespace(create=self.create)
        self.output_text = output_text

    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(
            id="resp-vision",
            model="test",
            output_text=self.output_text,
            usage=None,
            model_dump=lambda mode: {
                "id": "resp-vision",
                "model": "test",
                "output_text": self.output_text,
            },
        )


class ExplodingVisionClient:
    def __init__(self):
        self.calls = 0
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.calls += 1
        raise AssertionError("provider must not be used")


def test_callable_vision_runner_refuses_without_confirmation(tmp_path):
    client = ExplodingVisionClient()

    with pytest.raises(PermissionError, match="confirm_paid_call"):
        run(
            _visual_task(tmp_path),
            client=client,
            approved_request_path=tmp_path / "request.json",
            approved_request_sha256="0" * 64,
            confirm_paid_call=False,
            output_root=tmp_path / "runs",
        )

    assert client.calls == 0
    assert not (tmp_path / "runs").exists()


def test_vision_runner_sends_exact_approved_dictionary(tmp_path):
    task = _visual_task(tmp_path)
    approved = _approved_vision_request(tmp_path, task)
    client = RecordingVisionClient(_valid_vision_response_json())

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
        ({"route": "text"}, "route"),
    ],
)
def test_vision_runner_rejects_signed_request_for_other_scope(
    tmp_path,
    row_overrides,
    message,
):
    task = _visual_task(tmp_path)
    approved = _approved_vision_request(
        tmp_path,
        task,
        **row_overrides,
    )
    client = ExplodingVisionClient()

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


def test_vision_runner_rejects_signed_request_above_input_token_cap(
    tmp_path,
):
    task = _visual_task(tmp_path)
    approved = _approved_vision_request(
        tmp_path,
        task,
        estimated_input_tokens=6_001,
    )
    client = ExplodingVisionClient()

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


def test_visual_task_carries_candidate_facts_and_semantic_summaries(tmp_path):
    task = _visual_task(tmp_path)

    assert [row.candidate_id for row in task.candidate_facts] == ["OC-1"]
    assert [row.experiment_id for row in task.existing_experiment_summaries] == [
        "E1"
    ]
    assert task.existing_outcome_summaries == []
    assert task.crop_path.endswith(".png")
    assert task.task_version == "missing-record-vision-task-1.2.0"
    assert task.source_text_task_checksum
    assert task.accepted_visual_claim_sha256


def test_visual_task_rejects_a_changed_accepted_image(tmp_path):
    crop_path = tmp_path / "accepted-figure.png"
    crop_path.write_bytes(b"\x89PNG\r\nchanged visual")

    with pytest.raises(ValueError, match="checksum"):
        build(
            text_task=_v12_task(),
            accepted_visual_claim={
                "evidence_id": "E-1",
                "object_id": "FIGURE-1",
                "image_path": str(crop_path),
                "image_sha256": "a" * 64,
                "claim": {"panel_or_cell": "A"},
                "support_text": "Visible support.",
            },
        )


def test_legacy_vision_task_checksum_uses_its_original_raw_fields(tmp_path):
    current = _visual_task(tmp_path).model_dump(mode="json")
    current["task_version"] = "missing-record-vision-task-1.0.0"
    for field in (
        "experiment_context",
        "candidate_facts",
        "existing_experiment_summaries",
        "existing_outcome_summaries",
        "source_text_task_checksum",
        "accepted_visual_claim_sha256",
    ):
        current.pop(field)
    unsigned = {
        key: value
        for key, value in current.items()
        if key != "task_checksum"
    }
    current["task_checksum"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    task_path = tmp_path / "legacy-task.json"
    task_path.write_text(json.dumps(current), encoding="utf-8")

    assert load_task(task_path).task_version == (
        "missing-record-vision-task-1.0.0"
    )


def test_route_manifest_builds_only_candidate_level_vision_tasks(
    tmp_path, monkeypatch
):
    crop_path = tmp_path / "accepted-figure.png"
    crop_path.write_bytes(b"\x89PNG\r\naccepted visual")
    text_candidate = candidate(
        candidate_id="AOC-TEXT",
        claim_ids=["ACL-TEXT"],
        evidence_ids=["E-TEXT"],
    )
    visual_candidate = candidate(
        candidate_id="AOC-VISION",
        claim_ids=["ACL-VISION"],
        evidence_ids=["E-VISION"],
        source_ids=["FIGURE-1"],
        route_hint="vision",
    )
    run_dir = _write_run(
        tmp_path,
        candidates=[text_candidate, visual_candidate],
        accepted_visual_claims=[
            {
                "evidence_id": "E-VISION",
                "object_id": "FIGURE-1",
                "image_path": str(crop_path),
                "image_sha256": hashlib.sha256(
                    crop_path.read_bytes()
                ).hexdigest(),
                "claim": {"panel_or_cell": "A"},
                "support_text": "Visible support.",
            }
        ],
    )
    monkeypatch.setattr(
        text_builder, "estimate_input_tokens", lambda task, model: 2_000
    )
    text_builder.build_for_run(run_dir)

    manifest = build_for_run(run_dir)

    assert manifest["task_count"] == 1
    assert manifest["visual_candidate_count"] == 1
    assert manifest["visual_object_count"] == 1
    assert manifest["tasks"][0]["candidate_ids"] == ["AOC-VISION"]
    assert (
        run_dir / manifest["tasks"][0]["task_path"]
    ).is_file()


@pytest.mark.parametrize("provenance_issue", ["missing_digest", "mismatch"])
def test_untrusted_visual_claim_is_quarantined_without_task_or_request(
    tmp_path, monkeypatch, provenance_issue
):
    crop_path = tmp_path / "unsigned-figure.png"
    crop_path.write_bytes(b"\x89PNG\r\nunsigned visual")
    visual_candidate = candidate(
        candidate_id="AOC-UNSIGNED",
        claim_ids=["ACL-UNSIGNED"],
        evidence_ids=["E-UNSIGNED"],
        source_ids=["FIGURE-UNSIGNED"],
        route_hint="vision",
    )
    accepted_visual_claim = {
        "evidence_id": "E-UNSIGNED",
        "object_id": "FIGURE-UNSIGNED",
        "image_path": str(crop_path),
        "claim": {"panel_or_cell": "A"},
        "support_text": "Visible support.",
    }
    if provenance_issue == "mismatch":
        accepted_visual_claim["image_sha256"] = hashlib.sha256(
            crop_path.read_bytes()
        ).hexdigest()
    run_dir = _write_run(
        tmp_path,
        candidates=[visual_candidate],
        accepted_visual_claims=[accepted_visual_claim],
    )
    monkeypatch.setattr(
        text_builder, "estimate_input_tokens", lambda task, model: 2_000
    )
    text_builder.build_for_run(run_dir)
    if provenance_issue == "mismatch":
        crop_path.write_bytes(b"\x89PNG\r\nsubstituted visual")

    manifest = build_for_run(run_dir)

    assert manifest["task_count"] == 0
    assert manifest["visual_human_review_candidate_ids"] == [
        "AOC-UNSIGNED"
    ]
    assert not list(
        (run_dir / "missing_record_vision_tasks").glob("task_*.json")
    )

    monkeypatch.setattr(
        preflight_module,
        "audit",
        lambda root: {
            "passed": True,
            "issues": [],
            "repair_candidate_count": 1,
            "papers": [
                {
                    "confirmed_candidate_count": 0,
                    "repair_candidate_count": 1,
                }
            ],
        },
    )
    report = preflight_module.preflight(
        run_root=tmp_path,
        output_root=tmp_path / "preflight",
        model="test",
    )
    assert report["local_preflight_passed"]
    assert report["vision_request_count"] == 0
    assert report["visual_human_review_candidate_ids"] == [
        "AOC-UNSIGNED"
    ]
    assert not any(row["route"] == "vision" for row in report["requests"])


def test_visual_raw_response_is_persisted_before_invalid_json_is_parsed(
    tmp_path,
):
    task = _visual_task(tmp_path)
    response = SimpleNamespace(
        id="resp-vision",
        model="test",
        output_text="truncated {",
        usage=None,
        model_dump=lambda mode: {
            "id": "resp-vision",
            "model": "test",
            "output_text": "truncated {",
        },
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **request: response)
    )
    approved = _approved_vision_request(tmp_path, task)

    with pytest.raises(ValidationError):
        run(
            task,
            client=client,
            approved_request_path=approved.path,
            approved_request_sha256=approved.sha256,
            confirm_paid_call=True,
            output_root=tmp_path / "runs",
        )

    raw_paths = list((tmp_path / "runs").rglob("response.raw.json"))
    assert len(raw_paths) == 1
    assert "truncated {" in raw_paths[0].read_text(encoding="utf-8")
