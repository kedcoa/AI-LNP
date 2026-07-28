"""Contracts for one consolidated missing-record request per paper."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from src.extraction.missing_record_contracts import StrictModel
from src.extraction.repair_contracts import RepairEvidence


class RecoveryVisualAsset(StrictModel):
    label: str
    image_path: str
    image_sha256: str
    crop_evidence_id: str
    source_path: str
    page_number: int | None


class ConsolidatedRecoveryTask(StrictModel):
    task_version: Literal["consolidated-recovery-task-1.0.0"]
    paper_id: str
    purpose: str
    candidate_ids: list[str] = Field(min_length=1)
    evidence: list[RepairEvidence] = Field(min_length=1, max_length=24)
    visual_assets: list[RecoveryVisualAsset] = Field(max_length=4)
    existing_formulation_ids: list[str]
    existing_experiment_ids: list[str]
    existing_outcome_ids: list[str]
    existing_experiments: list[dict[str, Any]]
    existing_outcomes: list[dict[str, Any]]
    permitted_new_outcome_ids: list[str] = Field(min_length=2, max_length=2)
    permitted_new_experiments: int = Field(ge=0, le=2)
    permitted_new_outcomes: int = Field(ge=1, le=2)
    source_result_sha256: str
    source_inventory_sha256: str
    task_checksum: str
