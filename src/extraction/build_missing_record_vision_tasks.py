"""Adapt route-aware semantic repair tasks to accepted visual evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.extraction.missing_record_contracts import (
    MissingRecordTask,
    MissingRecordVisionTask,
)
from src.extraction.run_missing_record_repair import load_task


ROOT = Path(__file__).resolve().parents[2]


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _resolve_image_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()


SEMANTIC_SCOPE_FIELDS = (
    "paper_id",
    "route_ids",
    "candidate_ids",
    "experiment_context",
    "candidate_facts",
    "evidence",
    "existing_formulation_ids",
    "existing_experiment_ids",
    "existing_outcome_ids",
    "existing_experiment_summaries",
    "existing_outcome_summaries",
    "permitted_new_experiments",
    "permitted_new_outcomes",
    "source_result_sha256",
    "source_inventory_sha256",
)


def _semantic_scope(task: MissingRecordTask | MissingRecordVisionTask) -> dict:
    payload = task.model_dump(mode="json")
    return {field: payload[field] for field in SEMANTIC_SCOPE_FIELDS}


def matching_accepted_visual_claims(
    *,
    text_task: MissingRecordTask,
    visual_object_id: str | None,
    claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_ids = {row.evidence_id for row in text_task.evidence}
    return [
        row
        for row in claims
        if row.get("object_id") == visual_object_id
        and row.get("evidence_id") in evidence_ids
    ]


def vision_task_binding_issues(
    *,
    vision_task: MissingRecordVisionTask,
    text_task: MissingRecordTask,
    accepted_visual_claim: dict[str, Any],
) -> list[str]:
    """Verify the full semantic and accepted-image provenance binding."""

    issues: list[str] = []
    if vision_task.source_text_task_checksum != text_task.task_checksum:
        issues.append("source_text_task_checksum_mismatch")
    if _canonical(_semantic_scope(vision_task)) != _canonical(
        _semantic_scope(text_task)
    ):
        issues.append("vision_semantic_scope_mismatch")
    if vision_task.accepted_visual_claim_sha256 != _sha(
        _canonical(accepted_visual_claim)
    ):
        issues.append("accepted_visual_claim_sha256_mismatch")
    expected_image_sha = accepted_visual_claim.get("image_sha256")
    try:
        expected_image_path = _resolve_image_path(
            accepted_visual_claim["image_path"]
        )
        observed_image_sha = _sha(expected_image_path.read_bytes())
    except (KeyError, FileNotFoundError):
        expected_image_path = None
        observed_image_sha = None
    if (
        not expected_image_sha
        or observed_image_sha != expected_image_sha
        or expected_image_path is None
        or Path(vision_task.crop_path).resolve() != expected_image_path
        or vision_task.crop_sha256 != expected_image_sha
    ):
        issues.append("accepted_visual_image_binding_mismatch")
    if vision_task.crop_evidence_id != accepted_visual_claim.get(
        "evidence_id"
    ):
        issues.append("accepted_visual_evidence_binding_mismatch")
    object_id = accepted_visual_claim.get("object_id")
    panel = accepted_visual_claim.get("claim", {}).get("panel_or_cell")
    expected_label = object_id if not panel else f"{object_id}:{panel}"
    if vision_task.figure_or_table != expected_label:
        issues.append("accepted_visual_object_binding_mismatch")
    return issues


def build(
    *,
    text_task: MissingRecordTask,
    accepted_visual_claim: dict[str, Any],
    output_path: Path | None = None,
) -> MissingRecordVisionTask:
    """Wrap one v1.2 semantic task around its accepted visual object."""

    if text_task.task_version != "missing-record-task-1.2.0":
        raise ValueError("Visual repair requires a v1.2 semantic text task")
    evidence_id = accepted_visual_claim.get("evidence_id")
    if evidence_id not in {row.evidence_id for row in text_task.evidence}:
        raise ValueError("Accepted visual claim is outside the task evidence")
    crop_path = _resolve_image_path(accepted_visual_claim["image_path"])
    crop_sha256 = _sha(crop_path.read_bytes())
    expected_sha256 = accepted_visual_claim.get("image_sha256")
    if not expected_sha256:
        raise ValueError("Accepted visual claim is missing image_sha256")
    if expected_sha256 != crop_sha256:
        raise ValueError("Accepted visual image checksum mismatch")
    object_id = accepted_visual_claim.get("object_id")
    if not object_id:
        raise ValueError("Accepted visual claim requires an object_id")
    panel = accepted_visual_claim.get("claim", {}).get("panel_or_cell")
    figure_or_table = object_id if not panel else f"{object_id}:{panel}"
    unsigned = {
        "task_version": "missing-record-vision-task-1.2.0",
        "paper_id": text_task.paper_id,
        "route_ids": text_task.route_ids,
        "candidate_ids": text_task.candidate_ids,
        "experiment_context": (
            text_task.experiment_context.model_dump(mode="json")
            if text_task.experiment_context
            else None
        ),
        "candidate_facts": [
            row.model_dump(mode="json") for row in text_task.candidate_facts
        ],
        "evidence": [
            row.model_dump(mode="json") for row in text_task.evidence
        ],
        "existing_formulation_ids": text_task.existing_formulation_ids,
        "existing_experiment_ids": text_task.existing_experiment_ids,
        "existing_outcome_ids": text_task.existing_outcome_ids,
        "existing_experiment_summaries": [
            row.model_dump(mode="json")
            for row in text_task.existing_experiment_summaries
        ],
        "existing_outcome_summaries": [
            row.model_dump(mode="json")
            for row in text_task.existing_outcome_summaries
        ],
        "permitted_new_experiments": text_task.permitted_new_experiments,
        "permitted_new_outcomes": text_task.permitted_new_outcomes,
        "source_result_sha256": text_task.source_result_sha256,
        "source_inventory_sha256": text_task.source_inventory_sha256,
        "source_pdf": None,
        "source_pdf_sha256": None,
        "page_number": None,
        "figure_or_table": figure_or_table,
        "crop_path": str(crop_path),
        "crop_sha256": crop_sha256,
        "crop_evidence_id": evidence_id,
        "source_text_task_checksum": text_task.task_checksum,
        "accepted_visual_claim_sha256": _sha(
            _canonical(accepted_visual_claim)
        ),
    }
    task = MissingRecordVisionTask.model_validate(
        {**unsigned, "task_checksum": _sha(_canonical(unsigned))}
    )
    binding_issues = vision_task_binding_issues(
        vision_task=task,
        text_task=text_task,
        accepted_visual_claim=accepted_visual_claim,
    )
    if binding_issues:
        raise ValueError(
            f"Vision task binding failed: {binding_issues}"
        )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            task.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    return task


def build_for_run(run_dir: Path) -> dict[str, Any]:
    """Create trusted tasks and quarantine untrusted visual candidates."""

    task_root = run_dir / "structural_repair_tasks"
    manifest = json.loads(
        (task_root / "manifest.json").read_text(encoding="utf-8")
    )
    task_paths = sorted(task_root.glob("task_*.json"))
    if len(task_paths) != len(manifest.get("tasks", [])):
        raise ValueError("Structural task manifest count mismatch")
    support = json.loads(
        (run_dir / "request.json").read_text(encoding="utf-8")
    )["request_payload"]["outcome_recall_support"]
    claims = support.get("accepted_visual_claims", [])
    output_root = run_dir / "missing_record_vision_tasks"
    if output_root.exists():
        raise FileExistsError(
            "Vision task root already exists; refusing to overwrite"
        )
    rows: list[dict[str, Any]] = []
    visual_human_review_candidate_ids: set[str] = set()
    visual_human_review: list[dict[str, Any]] = []
    for task_path, metadata in zip(task_paths, manifest["tasks"], strict=True):
        if metadata.get("repair_route") != "vision":
            continue
        text_task = load_task(task_path)
        matching = matching_accepted_visual_claims(
            text_task=text_task,
            visual_object_id=metadata.get("visual_object_id"),
            claims=claims,
        )
        image_paths = {row.get("image_path") for row in matching}
        reason = None
        if len(matching) != 1 or len(image_paths) != 1:
            reason = "accepted_visual_claim_not_unique"
        elif not matching[0].get("image_sha256"):
            reason = "accepted_visual_claim_missing_image_sha256"
        else:
            try:
                image_path = _resolve_image_path(matching[0]["image_path"])
                if _sha(image_path.read_bytes()) != matching[0]["image_sha256"]:
                    reason = "accepted_visual_image_checksum_mismatch"
            except FileNotFoundError:
                reason = "accepted_visual_image_unavailable"
        if reason is not None:
            visual_human_review_candidate_ids.update(text_task.candidate_ids)
            visual_human_review.append(
                {
                    "source_task_path": str(
                        task_path.relative_to(run_dir)
                    ),
                    "candidate_ids": text_task.candidate_ids,
                    "visual_object_id": metadata.get("visual_object_id"),
                    "reason": reason,
                }
            )
            continue
        output_path = output_root / task_path.name
        vision_task = build(
            text_task=text_task,
            accepted_visual_claim=matching[0],
            output_path=output_path,
        )
        rows.append(
            {
                "source_task_path": str(task_path.relative_to(run_dir)),
                "task_path": str(output_path.relative_to(run_dir)),
                "candidate_ids": vision_task.candidate_ids,
                "visual_object_id": metadata["visual_object_id"],
                "crop_sha256": vision_task.crop_sha256,
            }
        )
    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "vision_task_build_version": "missing-record-vision-build-1.2.0",
        "paper_id": run_dir.name,
        "task_count": len(rows),
        "visual_candidate_count": sum(
            len(row["candidate_ids"]) for row in rows
        ),
        "visual_object_count": len(
            {row["visual_object_id"] for row in rows}
        ),
        "visual_human_review_candidate_ids": sorted(
            visual_human_review_candidate_ids
        ),
        "visual_human_review": visual_human_review,
        "tasks": rows,
        "paid_api_requests": 0,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
