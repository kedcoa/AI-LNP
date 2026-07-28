"""Render one page per missing-record visual referral and create signed tasks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.extraction.build_selective_vision_tasks import render_pdf_region
from src.extraction.missing_record_contracts import (
    MissingRecordVisionReferral,
    MissingRecordVisionTask,
)
from src.extraction.outcome_inventory_contracts import OutcomeInventory
from src.extraction.repair_contracts import RepairEvidence
from src.rag.compact_api_packet import CompactApiPacket


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def build(
    *,
    referral: MissingRecordVisionReferral,
    inventory: OutcomeInventory,
    packet: CompactApiPacket,
    result_path: Path,
    output_root: Path,
) -> MissingRecordVisionTask:
    if not (referral.paper_id == inventory.paper_id == packet.paper_id):
        raise ValueError("Referral, inventory, and packet paper IDs differ")
    pdf_path = Path(referral.source_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    evidence_by_id = {row.evidence_id: row for row in packet.evidence}
    missing = set(referral.evidence_ids) - set(evidence_by_id)
    if missing:
        raise ValueError(f"Referral evidence absent from packet: {sorted(missing)}")
    result_bytes = result_path.read_bytes()
    result = json.loads(result_bytes)
    task_dir = output_root / referral.paper_id / _sha(_canonical(referral.model_dump()))[:16]
    crop_path = task_dir / "page.png"
    render_pdf_region(pdf_path, referral.page_number, None, crop_path)
    crop_sha = _sha(crop_path.read_bytes())
    unsigned = {
        "task_version": "missing-record-vision-task-1.0.0",
        "paper_id": referral.paper_id,
        "route_ids": referral.route_ids,
        "candidate_ids": referral.candidate_ids,
        "evidence": [
            RepairEvidence(
                evidence_id=evidence_by_id[evidence_id].evidence_id,
                text=evidence_by_id[evidence_id].text,
                source_ids=evidence_by_id[evidence_id].source_ids,
            ).model_dump(mode="json")
            for evidence_id in referral.evidence_ids[:12]
        ],
        "existing_formulation_ids": [
            row["formulation_id"] for row in result.get("formulations", [])
        ],
        "existing_experiment_ids": [
            row["experiment_id"] for row in result.get("experiments", [])
        ],
        "existing_outcome_ids": [
            row["outcome_id"] for row in result.get("outcomes", [])
        ],
        "permitted_new_experiments": 1,
        "permitted_new_outcomes": min(8, max(1, len(referral.candidate_ids) * 2)),
        "source_result_sha256": _sha(result_bytes),
        "source_inventory_sha256": _sha(inventory.model_dump_json(exclude_none=True)),
        "source_pdf": str(pdf_path),
        "source_pdf_sha256": _sha(pdf_path.read_bytes()),
        "page_number": referral.page_number,
        "figure_or_table": referral.figure_or_table,
        "crop_path": str(crop_path),
        "crop_sha256": crop_sha,
        "crop_evidence_id": f"V-{crop_sha[:16]}",
    }
    task = MissingRecordVisionTask.model_validate(
        {**unsigned, "task_checksum": _sha(_canonical(unsigned))}
    )
    (task_dir / "task.json").write_text(
        task.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return task
