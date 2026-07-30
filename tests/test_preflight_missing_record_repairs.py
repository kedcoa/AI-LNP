import hashlib
import json

from openai.lib._pydantic import to_strict_json_schema

import src.extraction.preflight_missing_record_repairs as preflight_module
from src.extraction.build_missing_record_vision_tasks import build
from src.extraction.missing_record_contracts import MissingRecordFragment
from src.extraction.preflight_missing_record_repairs import strict_schema_issues
from tests.test_missing_record_workflow import _v12_task


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sign_task(task, *, result_sha256, inventory_sha256, candidate_id):
    raw = task.model_dump(mode="json")
    raw["candidate_ids"] = [candidate_id]
    raw["route_ids"] = [f"structural:{candidate_id}"]
    raw["candidate_facts"] = [
        {
            **raw["candidate_facts"][0],
            "candidate_id": candidate_id,
        }
    ]
    raw["source_result_sha256"] = result_sha256
    raw["source_inventory_sha256"] = inventory_sha256
    unsigned = {key: value for key, value in raw.items() if key != "task_checksum"}
    raw["task_checksum"] = hashlib.sha256(
        _canonical(unsigned).encode()
    ).hexdigest()
    return type(task).model_validate(raw)


def _prepared_run(tmp_path):
    run_root = tmp_path / "prepared"
    run_dir = run_root / "GP-X"
    task_root = run_dir / "structural_repair_tasks"
    vision_root = run_dir / "missing_record_vision_tasks"
    task_root.mkdir(parents=True)
    vision_root.mkdir()

    result_path = run_dir / "result.json"
    result_path.write_text('{"paper_id":"GP-X"}\n', encoding="utf-8")
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [],
        "accepted_visual_claims": [],
    }
    inventory_sha256 = hashlib.sha256(
        _canonical(support).encode()
    ).hexdigest()
    (run_dir / "request.json").write_text(
        json.dumps(
            {
                "request_payload": {
                    "outcome_recall_support": support,
                }
            }
        ),
        encoding="utf-8",
    )

    base_task = _v12_task(candidate_ids=["OC-BASE"])
    routes = [
        ("OC-TEXT-1", "text", None),
        ("OC-TEXT-2", "text", None),
        ("OC-VISION-1", "vision", "FIGURE-1"),
        ("OC-VISION-2", "vision", "FIGURE-2"),
    ]
    metadata = []
    for index, (candidate_id, route, visual_object_id) in enumerate(routes, 1):
        task = _sign_task(
            base_task,
            result_sha256=result_sha256,
            inventory_sha256=inventory_sha256,
            candidate_id=candidate_id,
        )
        task_path = task_root / f"task_{index:02d}.json"
        task_path.write_text(
            task.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        metadata.append(
            {
                "candidate_ids": [candidate_id],
                "repair_route": route,
                "visual_object_id": visual_object_id,
            }
        )
        if route == "vision":
            crop_path = tmp_path / f"{visual_object_id}.png"
            crop_path.write_bytes(f"PNG:{visual_object_id}".encode())
            crop_sha256 = hashlib.sha256(crop_path.read_bytes()).hexdigest()
            visual_task = build(
                text_task=task,
                accepted_visual_claim={
                    "evidence_id": "E-1",
                    "object_id": visual_object_id,
                    "image_path": str(crop_path),
                    "image_sha256": crop_sha256,
                    "claim": {"panel_or_cell": "A"},
                    "support_text": "Visible support.",
                },
            )
            (vision_root / f"task_{index:02d}.json").write_text(
                visual_task.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
    (task_root / "manifest.json").write_text(
        json.dumps({"task_count": 4, "tasks": metadata}),
        encoding="utf-8",
    )
    return run_root


def test_missing_record_response_schema_is_strict_at_every_object():
    schema = to_strict_json_schema(MissingRecordFragment)
    assert "candidate_resolutions" in schema["properties"]
    assert strict_schema_issues(schema) == []


def test_schema_audit_rejects_optional_or_open_object_properties():
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": [],
    }
    assert strict_schema_issues(schema) == [
        "$:additionalProperties_must_be_false",
        "$:all_properties_must_be_required",
    ]


def test_preflight_reports_exact_paid_call_and_route_totals(
    tmp_path, monkeypatch
):
    run_root = _prepared_run(tmp_path)
    monkeypatch.setattr(
        preflight_module,
        "audit",
        lambda root: {
            "passed": True,
            "issues": [],
            "repair_candidate_count": 4,
            "papers": [
                {
                    "confirmed_candidate_count": 3,
                    "repair_candidate_count": 4,
                }
            ],
        },
    )

    report = preflight_module.preflight(
        run_root=run_root,
        output_root=tmp_path / "out",
        model="test",
    )

    assert report["local_match_count"] == 3
    assert report["missing_candidate_count"] == 4
    assert report["text_candidate_count"] == 2
    assert report["text_request_count"] == 2
    assert report["visual_candidate_count"] == 2
    assert report["visual_object_count"] == 2
    assert report["vision_request_count"] == 2
    assert report["total_paid_request_count"] == 4
    assert len(report["request_paths"]) == 4
    assert report["estimated_cost"] is None
    assert report["pricing_status"] == "pricing_not_configured"
    assert report["server_request_sent"] is False
    assert report["paid_api_requests"] == 0
