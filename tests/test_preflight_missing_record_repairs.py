import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

import src.extraction.preflight_missing_record_repairs as preflight_module
from src.extraction.build_missing_record_vision_tasks import (
    build_for_run as build_vision_for_run,
)
from src.extraction.missing_record_contracts import MissingRecordFragment
from src.extraction.preflight_missing_record_repairs import strict_schema_issues
from tests.test_missing_record_workflow import _v12_task


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _write_signed_preflight(
    tmp_path,
    *,
    request=None,
    max_output_tokens=4_000,
):
    request = dict(
        request
        or {
            "model": "test",
            "input": [{"role": "system", "content": "approved prompt"}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "schema": {"type": "object"},
                }
            },
        }
    )
    request["max_output_tokens"] = max_output_tokens
    request_path = tmp_path / "approved-request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
    unsigned_manifest = {
        "preflight_version": "missing-record-request-preflight-1.2.0",
        "requests": [
            {
                "request_path": str(request_path),
                "request_sha256": request_sha256,
            }
        ],
    }
    manifest = {
        **unsigned_manifest,
        "manifest_checksum": hashlib.sha256(
            _canonical(unsigned_manifest).encode()
        ).hexdigest(),
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        request_path=request_path,
        sha256=request_sha256,
        manifest_path=manifest_path,
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
    routes = [
        ("OC-TEXT-1", "text", None),
        ("OC-TEXT-2", "text", None),
        ("OC-VISION-1", "vision", "FIGURE-1"),
        ("OC-VISION-2", "vision", "FIGURE-2"),
    ]
    visual_claims = []
    for _candidate_id, route, visual_object_id in routes:
        if route != "vision":
            continue
        crop_path = tmp_path / f"{visual_object_id}.png"
        crop_path.write_bytes(
            f"PNG:{visual_object_id}:".encode() + b"x" * 100_000
        )
        visual_claims.append(
            {
                "evidence_id": "E-1",
                "object_id": visual_object_id,
                "image_path": str(crop_path),
                "image_sha256": hashlib.sha256(
                    crop_path.read_bytes()
                ).hexdigest(),
                "claim": {"panel_or_cell": "A"},
                "support_text": "Visible support.",
            }
        )
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [],
        "accepted_visual_claims": visual_claims,
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
    (task_root / "manifest.json").write_text(
        json.dumps({"task_count": 4, "tasks": metadata}),
        encoding="utf-8",
    )
    vision_root.rmdir()
    build_vision_for_run(run_dir)
    return run_root


def _passed_audit(candidate_count=4):
    return {
        "passed": True,
        "issues": [],
        "repair_candidate_count": candidate_count,
        "papers": [
            {
                "confirmed_candidate_count": 3,
                "repair_candidate_count": candidate_count,
            }
        ],
    }


def _resign_vision_task(path, mutate):
    raw = json.loads(path.read_text(encoding="utf-8"))
    mutate(raw)
    unsigned = {
        key: value for key, value in raw.items() if key != "task_checksum"
    }
    raw["task_checksum"] = hashlib.sha256(
        _canonical(unsigned).encode()
    ).hexdigest()
    path.write_text(json.dumps(raw), encoding="utf-8")


def _quarantine_one_visual_task(run_root):
    run_dir = run_root / "GP-X"
    vision_root = run_dir / "missing_record_vision_tasks"
    manifest_path = vision_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quarantined = manifest["tasks"].pop(0)
    (run_dir / quarantined["task_path"]).unlink()
    review_row = {
        "source_task_path": quarantined["source_task_path"],
        "candidate_ids": quarantined["candidate_ids"],
        "visual_object_id": quarantined["visual_object_id"],
        "reason": "accepted_visual_claim_not_unique",
    }
    manifest.update(
        {
            "task_count": 1,
            "visual_candidate_count": 1,
            "visual_object_count": 1,
            "visual_human_review_candidate_ids": quarantined[
                "candidate_ids"
            ],
            "visual_human_review": [review_row],
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return review_row


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
        lambda root: _passed_audit(),
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
    assert report["sendable_visual_candidate_count"] == 2
    assert report["visual_object_count"] == 2
    assert report["visual_human_review_candidate_count"] == 0
    assert report["visual_human_review_object_count"] == 0
    assert report["visual_human_review"] == []
    assert report["vision_request_count"] == 2
    assert report["total_paid_request_count"] == 4
    assert len(report["request_paths"]) == 4
    assert report["estimated_cost"] is None
    assert report["pricing_status"] == "pricing_not_configured"
    vision_rows = [
        row for row in report["requests"] if row["route"] == "vision"
    ]
    assert all(row["image_input_bytes"] > 100_000 for row in vision_rows)
    assert all(row["estimated_image_tokens"] is None for row in vision_rows)
    assert all(
        row["estimated_input_tokens"] < row["request_bytes"] // 10
        for row in vision_rows
    )
    assert report["estimated_image_tokens"] is None
    assert report["image_token_estimate_status"] == "not_configured"
    assert report["server_request_sent"] is False
    assert report["paid_api_requests"] == 0


def test_preflight_reports_structured_visual_human_review_scope(
    tmp_path, monkeypatch
):
    run_root = _prepared_run(tmp_path)
    review_row = _quarantine_one_visual_task(run_root)
    monkeypatch.setattr(
        preflight_module,
        "audit",
        lambda root: _passed_audit(),
    )

    report = preflight_module.preflight(
        run_root=run_root,
        output_root=tmp_path / "out",
        model="test",
    )

    assert report["sendable_visual_candidate_count"] == 1
    assert report["visual_human_review_candidate_count"] == 1
    assert report["visual_human_review_object_count"] == 1
    assert report["visual_human_review"] == [
        {"paper_id": "GP-X", **review_row}
    ]


def test_preflight_hashes_exact_persisted_request_bytes(
    tmp_path, monkeypatch
):
    run_root = _prepared_run(tmp_path)
    original_write_text = Path.write_text

    def write_text_with_translated_newlines(path, data, **kwargs):
        if path.name.startswith("task_"):
            data = data.replace("\n", "\r\n")
        return original_write_text(path, data, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text_with_translated_newlines)
    monkeypatch.setattr(
        preflight_module,
        "audit",
        lambda root: _passed_audit(),
    )

    report = preflight_module.preflight(
        run_root=run_root,
        output_root=tmp_path / "out",
        model="test",
    )

    for row in report["requests"]:
        request_bytes = Path(row["request_path"]).read_bytes()
        assert row["request_sha256"] == hashlib.sha256(
            request_bytes
        ).hexdigest()
        assert row["request_bytes"] == len(request_bytes)
    unsigned_manifest = {
        key: value
        for key, value in report.items()
        if key != "manifest_checksum"
    }
    assert report["manifest_checksum"] == hashlib.sha256(
        _canonical(unsigned_manifest).encode()
    ).hexdigest()


def test_runner_rejects_request_bytes_not_listed_in_signed_manifest(
    tmp_path,
):
    approved = _write_signed_preflight(tmp_path)
    approved.request_path.write_text(
        '{"model":"different"}\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="approved request"):
        preflight_module.load_approved_request(
            approved.request_path,
            expected_sha256=approved.sha256,
            manifest_path=approved.manifest_path,
        )


def test_approved_request_rejects_output_limit_other_than_4000(tmp_path):
    approved = _write_signed_preflight(
        tmp_path,
        max_output_tokens=4_001,
    )

    with pytest.raises(ValueError, match="4,000"):
        preflight_module.load_approved_request(
            approved.request_path,
            expected_sha256=approved.sha256,
            manifest_path=approved.manifest_path,
        )


def test_approved_request_rejects_tampered_manifest_checksum(tmp_path):
    approved = _write_signed_preflight(tmp_path)
    manifest = json.loads(
        approved.manifest_path.read_text(encoding="utf-8")
    )
    manifest["requests"][0]["request_sha256"] = "f" * 64
    approved.manifest_path.write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="manifest checksum"):
        preflight_module.load_approved_request(
            approved.request_path,
            expected_sha256=approved.sha256,
            manifest_path=approved.manifest_path,
        )


def test_preflight_rejects_resigned_vision_semantic_tampering(
    tmp_path, monkeypatch
):
    run_root = _prepared_run(tmp_path)
    vision_path = (
        run_root
        / "GP-X/missing_record_vision_tasks/task_03.json"
    )
    _resign_vision_task(
        vision_path,
        lambda raw: raw["candidate_facts"][0].update(
            {"subject_text": "tampered subject"}
        ),
    )
    monkeypatch.setattr(
        preflight_module, "audit", lambda root: _passed_audit()
    )

    report = preflight_module.preflight(
        run_root=run_root,
        output_root=tmp_path / "out",
        model="test",
    )

    assert not report["local_preflight_passed"]
    assert report["vision_request_count"] == 1
    assert any(
        "vision_semantic_scope_mismatch" in issue
        for issue in report["issues"]
    )


def test_preflight_rejects_resigned_vision_image_substitution(
    tmp_path, monkeypatch
):
    run_root = _prepared_run(tmp_path)
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(b"replacement image")
    replacement_sha = hashlib.sha256(replacement.read_bytes()).hexdigest()
    vision_path = (
        run_root
        / "GP-X/missing_record_vision_tasks/task_03.json"
    )

    def substitute_image(raw):
        raw["crop_path"] = str(replacement)
        raw["crop_sha256"] = replacement_sha

    _resign_vision_task(vision_path, substitute_image)
    monkeypatch.setattr(
        preflight_module, "audit", lambda root: _passed_audit()
    )

    report = preflight_module.preflight(
        run_root=run_root,
        output_root=tmp_path / "out",
        model="test",
    )

    assert not report["local_preflight_passed"]
    assert report["vision_request_count"] == 1
    assert any(
        "accepted_visual_image_binding_mismatch" in issue
        for issue in report["issues"]
    )


def test_preflight_rejects_resigned_accepted_claim_hash_tampering(
    tmp_path, monkeypatch
):
    run_root = _prepared_run(tmp_path)
    vision_path = (
        run_root
        / "GP-X/missing_record_vision_tasks/task_03.json"
    )
    _resign_vision_task(
        vision_path,
        lambda raw: raw.update(
            {"accepted_visual_claim_sha256": "0" * 64}
        ),
    )
    monkeypatch.setattr(
        preflight_module, "audit", lambda root: _passed_audit()
    )

    report = preflight_module.preflight(
        run_root=run_root,
        output_root=tmp_path / "out",
        model="test",
    )

    assert not report["local_preflight_passed"]
    assert report["vision_request_count"] == 1
    assert any(
        "accepted_visual_claim_sha256_mismatch" in issue
        for issue in report["issues"]
    )
