"""Evidence-bounded contracts for adding omitted experiments and outcomes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.extraction.compact_contracts import ExperimentRecord, OutcomeRecord
from src.extraction.repair_contracts import RepairEvidence


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MissingRecordExperimentAnchor(StrictModel):
    anchor_type: str
    value: str
    evidence_ids: list[str]


class MissingRecordExperimentContext(StrictModel):
    provisional_experiment_id: str
    label: str
    anchors: list[MissingRecordExperimentAnchor] = Field(min_length=1)


class MissingRecordCandidateFact(StrictModel):
    """The actual fact represented by one otherwise opaque candidate ID."""

    candidate_id: str
    subject_text: str
    predicate: str
    object_text: str | None
    endpoint_text: str | None
    qualitative_result: str | None
    numeric_value: float | None
    value_text: str | None
    unit: str | None
    polarity: str
    evidence_ids: list[str] = Field(min_length=1)


class MissingRecordExperimentSummary(StrictModel):
    experiment_id: str
    formulation_id: str
    payload_type: str | None
    payload_name: str | None
    encoded_product: str | None
    molecular_target: str | None
    delivery_recipient_cell: str | None
    therapeutic_target_cell: str | None
    tissue_or_organ: str | None
    species: str | None
    disease_model: str | None
    experimental_context: str | None
    dose: float | None
    dose_unit: str | None
    route: str | None
    timepoint: float | None
    timepoint_unit: str | None
    outcome_endpoints: list[str]
    comparator_context: list[str]


class MissingRecordOutcomeSummary(StrictModel):
    outcome_id: str
    experiment_id: str
    assay: str | None
    endpoint: str | None
    comparator: str | None
    qualitative_outcome: str | None


class MissingRecordCandidateResolution(StrictModel):
    candidate_id: str
    status: Literal[
        "already_represented",
        "recovered_existing_experiment",
        "recovered_new_experiment",
        "unresolved",
    ]
    outcome_ids: list[str]
    experiment_ids: list[str]
    reason: str | None


class MissingRecordTask(StrictModel):
    task_version: Literal[
        "missing-record-task-1.0.0",
        "missing-record-task-1.1.0",
        "missing-record-task-1.2.0",
    ]
    paper_id: str
    route_ids: list[str] = Field(min_length=1)
    candidate_ids: list[str] = Field(min_length=1)
    experiment_context: MissingRecordExperimentContext | None = None
    candidate_facts: list[MissingRecordCandidateFact] = Field(
        default_factory=list, max_length=8
    )
    evidence: list[RepairEvidence] = Field(min_length=1, max_length=12)
    existing_formulation_ids: list[str]
    existing_experiment_ids: list[str]
    existing_outcome_ids: list[str]
    existing_experiment_summaries: list[MissingRecordExperimentSummary] = Field(
        default_factory=list
    )
    existing_outcome_summaries: list[MissingRecordOutcomeSummary] = Field(
        default_factory=list
    )
    permitted_new_experiments: int = Field(ge=0, le=2)
    permitted_new_outcomes: int = Field(ge=1, le=8)
    source_result_sha256: str
    source_inventory_sha256: str
    task_checksum: str

    @model_validator(mode="after")
    def validate_candidate_facts(self) -> "MissingRecordTask":
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate_ids must be unique")
        if self.task_version in {
            "missing-record-task-1.1.0",
            "missing-record-task-1.2.0",
        }:
            if self.experiment_context is None:
                raise ValueError(
                    "v1.1 structural tasks require experiment_context"
                )
            fact_ids = [row.candidate_id for row in self.candidate_facts]
            if len(set(fact_ids)) != len(fact_ids):
                raise ValueError("candidate_facts IDs must be unique")
            if set(fact_ids) != set(self.candidate_ids):
                raise ValueError(
                    "candidate_facts must describe every candidate ID exactly "
                    "once"
                )
            allowed_evidence = {row.evidence_id for row in self.evidence}
            for anchor in self.experiment_context.anchors:
                unknown_anchor_evidence = (
                    set(anchor.evidence_ids) - allowed_evidence
                )
                if unknown_anchor_evidence:
                    raise ValueError(
                        "experiment_context references unavailable task "
                        f"evidence: {sorted(unknown_anchor_evidence)}"
                    )
            for fact in self.candidate_facts:
                unknown = set(fact.evidence_ids) - allowed_evidence
                if unknown:
                    raise ValueError(
                        f"{fact.candidate_id} references unavailable task "
                        f"evidence: {sorted(unknown)}"
                    )
        if self.task_version == "missing-record-task-1.2.0":
            summary_ids = [row.experiment_id for row in self.existing_experiment_summaries]
            if set(summary_ids) != set(self.existing_experiment_ids):
                raise ValueError(
                    "existing experiment summary IDs must match existing_experiment_ids"
                )
            if len(set(summary_ids)) != len(summary_ids):
                raise ValueError("existing experiment summary IDs must be unique")
        return self


class MissingRecordFragment(StrictModel):
    disposition: Literal["recovered", "unresolved"]
    recovered_candidate_ids: list[str]
    unresolved_candidate_ids: list[str]
    experiments: list[ExperimentRecord] = Field(max_length=2)
    outcomes: list[OutcomeRecord] = Field(max_length=8)
    unresolved_reason: str | None
    candidate_resolutions: list[MissingRecordCandidateResolution] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_disposition(self) -> "MissingRecordFragment":
        if len(set(self.recovered_candidate_ids)) != len(self.recovered_candidate_ids):
            raise ValueError("recovered_candidate_ids must be unique")
        if len(set(self.unresolved_candidate_ids)) != len(self.unresolved_candidate_ids):
            raise ValueError("unresolved_candidate_ids must be unique")
        if (
            self.disposition == "recovered"
            and not self.outcomes
            and not self.candidate_resolutions
        ):
            raise ValueError("Recovered fragment requires at least one outcome")
        if self.unresolved_candidate_ids and not self.unresolved_reason:
            raise ValueError("Unresolved candidates require a reason")
        if not self.unresolved_candidate_ids and self.unresolved_reason:
            raise ValueError("unresolved_reason requires an unresolved candidate")
        if self.disposition == "unresolved":
            if self.recovered_candidate_ids:
                raise ValueError("Unresolved fragment cannot claim recovered candidates")
            if self.experiments or self.outcomes:
                raise ValueError("Unresolved fragment cannot contain records")
            if not self.unresolved_reason:
                raise ValueError("Unresolved fragment requires a reason")
        return self


class MissingRecordVisionReferral(StrictModel):
    referral_version: Literal["missing-record-vision-referral-1.0.0"]
    paper_id: str
    route_ids: list[str] = Field(min_length=1)
    candidate_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    source_path: str
    page_number: int = Field(ge=1)
    figure_or_table: str
    reason: str


class MissingRecordVisionTask(StrictModel):
    task_version: Literal["missing-record-vision-task-1.0.0"]
    paper_id: str
    route_ids: list[str] = Field(min_length=1)
    candidate_ids: list[str] = Field(min_length=1)
    evidence: list[RepairEvidence] = Field(min_length=1, max_length=12)
    existing_formulation_ids: list[str]
    existing_experiment_ids: list[str]
    existing_outcome_ids: list[str]
    permitted_new_experiments: int = Field(ge=0, le=2)
    permitted_new_outcomes: int = Field(ge=1, le=8)
    source_result_sha256: str
    source_inventory_sha256: str
    source_pdf: str
    source_pdf_sha256: str
    page_number: int = Field(ge=1)
    figure_or_table: str
    crop_path: str
    crop_sha256: str
    crop_evidence_id: str
    task_checksum: str


class MissingRecordVisionResponse(StrictModel):
    fragment: MissingRecordFragment
    value_status: Literal[
        "exact_reported", "derived", "visually_estimated", "not_resolved"
    ]
    panel_or_table_cell: str | None
    visible_support: str = Field(min_length=1, max_length=500)
    derivation: str | None
    requires_human_review: bool

    @model_validator(mode="after")
    def enforce_visual_safety(self) -> "MissingRecordVisionResponse":
        if self.value_status == "visually_estimated":
            if not self.requires_human_review:
                raise ValueError("Visual estimates require human review")
            if self.fragment.disposition != "unresolved":
                raise ValueError("Visual estimates cannot be automatically recovered")
        if self.fragment.disposition == "recovered":
            if self.value_status not in {"exact_reported", "derived"}:
                raise ValueError("Recovered records require exact or derived support")
            if self.requires_human_review:
                raise ValueError("Human-review records cannot be auto-merged")
            if not self.panel_or_table_cell:
                raise ValueError("Recovered visual records require a cell/panel location")
        if self.value_status == "derived" and not self.derivation:
            raise ValueError("Derived records require a derivation")
        return self
