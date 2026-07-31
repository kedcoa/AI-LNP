"""Compact, evidence-ID-only extraction contract for the v7 pipeline.

The response intentionally contains no evidence quotations. Evidence text and
coordinates remain in the local evidence packet and are joined by
``evidence_ids`` after the model response is validated.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


T = TypeVar("T")


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportedField(StrictContract, Generic[T]):
    """A directly reported value or an explicit evidence-based abstention."""

    value: T | None
    status: Literal["reported", "missing"]
    evidence_ids: list[str] = Field(default_factory=list)
    missing_reason: str | None

    @model_validator(mode="after")
    def require_evidence_or_missing(self) -> "ReportedField[T]":
        if self.status == "reported":
            if self.value is None:
                raise ValueError("reported fields must contain a value")
            if not self.evidence_ids:
                raise ValueError("reported fields require at least one evidence_id")
            if self.missing_reason is not None:
                raise ValueError("reported fields cannot contain a missing_reason")
        else:
            if self.value is not None:
                raise ValueError("missing fields must contain a null value")
            if self.evidence_ids:
                raise ValueError("missing fields cannot cite evidence as value support")
            if not self.missing_reason:
                raise ValueError("missing fields require a missing_reason")
        return self


TextField = ReportedField[str]
NumberField = ReportedField[float]


EligibilityReason = Literal[
    "ORIGINAL_EXPERIMENT",
    "IDENTIFIABLE_LNP",
    "SUPPORTED_PAYLOAD",
    "TARGET_CELL_EVIDENCE",
    "USABLE_FORMULATION_OUTCOME_LINKAGE",
    "NOT_ORIGINAL_RESEARCH",
    "NOT_ELIGIBLE_LNP",
    "UNSUPPORTED_PAYLOAD",
    "NO_TARGET_CELL_EVIDENCE",
    "NO_FORMULATION_OUTCOME_LINKAGE",
    "DUPLICATE_SCIENTIFIC_REPORT",
    "RETRACTED_OR_INVALID",
    "FULL_TEXT_REQUIRED",
    "PUBLICATION_TYPE_AMBIGUOUS",
    "LNP_IDENTITY_AMBIGUOUS",
    "PAYLOAD_AMBIGUOUS",
    "TARGET_CELL_AMBIGUOUS",
    "FORMULATION_INCOMPLETE",
    "OUTCOME_LINKAGE_AMBIGUOUS",
    "CHEMISTRY_AMBIGUOUS",
]

ELIGIBLE_REASONS = {
    "ORIGINAL_EXPERIMENT",
    "IDENTIFIABLE_LNP",
    "SUPPORTED_PAYLOAD",
    "TARGET_CELL_EVIDENCE",
    "USABLE_FORMULATION_OUTCOME_LINKAGE",
}
INELIGIBLE_REASONS = {
    "NOT_ORIGINAL_RESEARCH",
    "NOT_ELIGIBLE_LNP",
    "UNSUPPORTED_PAYLOAD",
    "NO_TARGET_CELL_EVIDENCE",
    "NO_FORMULATION_OUTCOME_LINKAGE",
    "DUPLICATE_SCIENTIFIC_REPORT",
    "RETRACTED_OR_INVALID",
}
UNCERTAIN_REASONS = {
    "FULL_TEXT_REQUIRED",
    "PUBLICATION_TYPE_AMBIGUOUS",
    "LNP_IDENTITY_AMBIGUOUS",
    "PAYLOAD_AMBIGUOUS",
    "TARGET_CELL_AMBIGUOUS",
    "FORMULATION_INCOMPLETE",
    "OUTCOME_LINKAGE_AMBIGUOUS",
    "CHEMISTRY_AMBIGUOUS",
}


class EligibilityRecord(StrictContract):
    """Evidence-grounded final paper disposition for the extraction task."""

    decision: Literal["eligible", "ineligible", "uncertain"]
    reason_codes: list[EligibilityReason] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_decision_reasons(self) -> "EligibilityRecord":
        reasons = set(self.reason_codes)
        if len(reasons) != len(self.reason_codes):
            raise ValueError("eligibility reason_codes must be unique")
        if self.decision == "eligible":
            if not ELIGIBLE_REASONS <= reasons:
                raise ValueError(
                    "eligible requires all five positive eligibility reason codes"
                )
            if not self.evidence_ids:
                raise ValueError("eligible requires at least one evidence_id")
        elif self.decision == "ineligible":
            if not reasons & INELIGIBLE_REASONS:
                raise ValueError("ineligible requires an exclusion reason code")
            if not self.evidence_ids:
                raise ValueError("ineligible requires at least one evidence_id")
        elif not reasons & UNCERTAIN_REASONS:
            raise ValueError("uncertain requires a manual-review reason code")
        return self


class FormulationRecord(StrictContract):
    formulation_id: str
    formulation_name: TextField
    composition: TextField
    composition_basis: TextField
    np_ratio: NumberField


class ComponentRecord(StrictContract):
    component_id: str
    formulation_id: str
    identity: TextField
    role: ReportedField[
        Literal[
            "ionizable_lipid",
            "helper_lipid",
            "cholesterol",
            "peg_lipid",
            "targeting_ligand",
            "sort_lipid",
            "other",
        ]
    ]
    amount: NumberField
    amount_unit: TextField


class ExperimentRecord(StrictContract):
    experiment_id: str
    formulation_id: str
    payload_type: TextField
    payload_name: TextField
    payload_role: (
        ReportedField[
            Literal[
                "therapeutic",
                "reporter",
                "biodistribution_tracer",
                "screening_barcode",
            ]
        ]
        | None
    ) = None
    encoded_product: TextField
    molecular_target: TextField
    delivery_recipient_cell: TextField
    therapeutic_target_cell: TextField
    tissue_or_organ: TextField
    species: TextField
    disease_model: TextField
    experimental_context: ReportedField[
        Literal["in_vitro", "ex_vivo", "in_vivo"]
    ]
    dose: NumberField
    dose_unit: TextField
    route: TextField
    timepoint: NumberField
    timepoint_unit: TextField


class OutcomeRecord(StrictContract):
    outcome_id: str
    experiment_id: str
    assay: TextField
    endpoint: TextField
    comparator: TextField
    outcome_value: NumberField
    outcome_unit: TextField
    qualitative_outcome: TextField


class CompactExtractionResponse(StrictContract):
    """One paper response joined to a local evidence packet after validation."""

    contract_version: Literal["compact-1.1.0"]
    paper_id: str
    eligibility: EligibilityRecord
    formulations: list[FormulationRecord]
    components: list[ComponentRecord]
    experiments: list[ExperimentRecord]
    outcomes: list[OutcomeRecord]
    unresolved_items: list[str]

    @model_validator(mode="after")
    def validate_record_links(self) -> "CompactExtractionResponse":
        records = [
            *self.formulations,
            *self.components,
            *self.experiments,
            *self.outcomes,
        ]
        if self.eligibility.decision != "eligible" and records:
            raise ValueError(
                "ineligible or uncertain papers must return empty extraction lists"
            )
        if self.eligibility.decision == "eligible" and not (
            self.formulations and self.experiments and self.outcomes
        ):
            raise ValueError(
                "eligible papers require formulation, experiment, and outcome records"
            )
        formulation_ids = {item.formulation_id for item in self.formulations}
        experiment_ids = {item.experiment_id for item in self.experiments}

        if len(formulation_ids) != len(self.formulations):
            raise ValueError("formulation_id values must be unique")
        if len(experiment_ids) != len(self.experiments):
            raise ValueError("experiment_id values must be unique")
        if any(item.formulation_id not in formulation_ids for item in self.components):
            raise ValueError("component references an unknown formulation_id")
        if any(item.formulation_id not in formulation_ids for item in self.experiments):
            raise ValueError("experiment references an unknown formulation_id")
        if any(item.experiment_id not in experiment_ids for item in self.outcomes):
            raise ValueError("outcome references an unknown experiment_id")
        return self

    def validate_evidence_ids(self, allowed_evidence_ids: set[str]) -> None:
        """Reject model citations that do not exist in the local packet."""

        unknown_eligibility = (
            set(self.eligibility.evidence_ids) - allowed_evidence_ids
        )
        if unknown_eligibility:
            raise ValueError(
                "EligibilityRecord references unknown evidence IDs: "
                f"{sorted(unknown_eligibility)}"
            )

        for record in [
            *self.formulations,
            *self.components,
            *self.experiments,
            *self.outcomes,
        ]:
            for field_name in record.__class__.model_fields:
                value = getattr(record, field_name)
                if not isinstance(value, ReportedField):
                    continue
                unknown = set(value.evidence_ids) - allowed_evidence_ids
                if unknown:
                    raise ValueError(
                        f"{record.__class__.__name__}.{field_name} references "
                        f"unknown evidence IDs: {sorted(unknown)}"
                    )
