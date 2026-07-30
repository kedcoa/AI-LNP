import hashlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import src.extraction.build_v12_structural_repair_tasks as text_builder
from src.extraction.build_missing_record_vision_tasks import (
    build,
    build_for_run,
)
from src.extraction.run_missing_record_vision import run
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


def test_visual_task_carries_candidate_facts_and_semantic_summaries(tmp_path):
    task = _visual_task(tmp_path)

    assert [row.candidate_id for row in task.candidate_facts] == ["OC-1"]
    assert [row.experiment_id for row in task.existing_experiment_summaries] == [
        "E1"
    ]
    assert task.existing_outcome_summaries == []
    assert task.crop_path.endswith(".png")
    assert task.task_version == "missing-record-vision-task-1.1.0"


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

    with pytest.raises(ValidationError):
        run(
            task,
            model="test",
            client=client,
            output_root=tmp_path / "runs",
        )

    raw_paths = list((tmp_path / "runs").rglob("response.raw.json"))
    assert len(raw_paths) == 1
    assert "truncated {" in raw_paths[0].read_text(encoding="utf-8")
