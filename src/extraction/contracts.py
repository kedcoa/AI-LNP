"""Schema-valid, evidence-gated contracts for detailed LNP extraction.

These models intentionally do not import screening code. Screening decides
whether a paper is relevant; only a later, explicit pipeline step may create
these detailed extraction objects.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


T = TypeVar("T")


class StrictContract(BaseModel):
    """Reject unknown keys so malformed LLM output cannot pass silently."""

    model_config = ConfigDict(extra="forbid")


class EvidenceBoundValue(StrictContract, Generic[T]):
    """A reported value with evidence, or an explicitly missing value."""

    value: T | None
    value_status: Literal["reported", "missing"]
    evidence_ids: list[str] = Field(default_factory=list)
    missing_reason: str | None

    @model_validator(mode="after")
    def enforce_evidence_boundary(self) -> "EvidenceBoundValue[T]":
        if self.value_status == "reported":
            if self.value is None:
                raise ValueError("reported values must not be null")
            if not self.evidence_ids:
                raise ValueError("reported values require at least one evidence_id")
            if self.missing_reason is not None:
                raise ValueError("reported values cannot have a missing_reason")
        else:
            if self.value is not None:
                raise ValueError("missing values must be null")
            if self.evidence_ids:
                raise ValueError("missing values cannot cite evidence as support")
            if not self.missing_reason:
                raise ValueError("missing values require a missing_reason")
        return self


TextValue = EvidenceBoundValue[str]
NumberValue = EvidenceBoundValue[float]


class FormulationExtraction(StrictContract):
    formulation_id: str
    paper_id: str
    formulation_name: TextValue
    composition_raw: TextValue
    composition_basis: EvidenceBoundValue[
        Literal["mol%", "weight%", "molar_ratio", "mass_ratio", "other"]
    ]
    np_ratio: NumberValue
    formulation_notes: TextValue


class ComponentExtraction(StrictContract):
    component_id: str
    formulation_id: str
    component_name_reported: TextValue
    component_name_normalized: TextValue
    component_role: EvidenceBoundValue[
        Literal[
            "ionizable_lipid",
            "helper_lipid",
            "sterol",
            "peg_lipid",
            "targeting_ligand",
            "targeting_anchor",
            "targeting_or_tracer_polymer",
            "sort_lipid",
            "payload",
            "other",
        ]
    ]
    inchikey: TextValue
    percentage: NumberValue
    percentage_unit: TextValue


class ExperimentExtraction(StrictContract):
    experiment_id: str
    paper_id: str
    formulation_id: str
    delivery_recipient_cell: EvidenceBoundValue[
        Literal["hepatocyte", "kupffer_cell", "lsec", "hsc", "other"]
    ]
    therapeutic_target_cell: TextValue
    cell_source: TextValue
    species: TextValue
    model_context: EvidenceBoundValue[
        Literal["in_vitro", "ex_vivo", "in_vivo"]
    ]
    payload_type: TextValue
    payload_name: TextValue
    reporter: TextValue
    dose: NumberValue
    dose_unit: TextValue
    route: TextValue
    timepoint: NumberValue
    timepoint_unit: TextValue
    assay: TextValue
    comparator_type: TextValue
    comparator_description: TextValue
    protocol_reference: TextValue


class OutcomeExtraction(StrictContract):
    outcome_id: str
    experiment_id: str
    endpoint_family: EvidenceBoundValue[
        Literal[
            "uptake",
            "functional_expression",
            "transfection",
            "gene_knockdown",
            "cre_recombination",
            "viability",
            "toxicity",
            "biodistribution",
            "therapeutic_effect",
            "other",
        ]
    ]
    endpoint_name: TextValue
    outcome_value: NumberValue
    outcome_unit: TextValue
    normalization_basis: TextValue
    uncertainty_value: NumberValue
    uncertainty_type: TextValue
    qualitative_outcome: TextValue
    comparator: TextValue


class EvidenceExtraction(StrictContract):
    evidence_id: str
    paper_id: str
    evidence_text: str = Field(min_length=1)
    evidence_location_type: Literal[
        "abstract",
        "results",
        "methods",
        "table",
        "figure",
        "figure_caption",
        "supplement",
        "other",
    ]
    section_name: str | None
    page_number: str | None
    table_number: str | None
    figure_number: str | None
    supplement_identifier: str | None
    extraction_method: Literal["manual", "text_extraction", "structured_table", "ocr", "vision"]
    extraction_confidence: Literal["high", "medium", "low"]


class ExtractionBundle(StrictContract):
    """One independently validated detailed-extraction payload."""

    contract_version: Literal["1.0.0"]
    paper_id: str
    formulations: list[FormulationExtraction]
    components: list[ComponentExtraction]
    experiments: list[ExperimentExtraction]
    outcomes: list[OutcomeExtraction]
    evidence: list[EvidenceExtraction]

    @model_validator(mode="after")
    def validate_links(self) -> "ExtractionBundle":
        evidence_ids = {item.evidence_id for item in self.evidence}
        formulation_ids = {item.formulation_id for item in self.formulations}
        experiment_ids = {item.experiment_id for item in self.experiments}

        for record in [*self.formulations, *self.components, *self.experiments, *self.outcomes]:
            for field_name in record.__class__.model_fields:
                field_value = getattr(record, field_name)
                if isinstance(field_value, EvidenceBoundValue):
                    unknown = set(field_value.evidence_ids) - evidence_ids
                    if unknown:
                        raise ValueError(f"{field_name} references unknown evidence IDs: {sorted(unknown)}")

        if any(item.formulation_id not in formulation_ids for item in self.components):
            raise ValueError("component references an unknown formulation_id")
        if any(item.formulation_id not in formulation_ids for item in self.experiments):
            raise ValueError("experiment references an unknown formulation_id")
        if any(item.experiment_id not in experiment_ids for item in self.outcomes):
            raise ValueError("outcome references an unknown experiment_id")
        if any(item.paper_id != self.paper_id for item in self.evidence):
            raise ValueError("evidence paper_id must match bundle paper_id")
        return self
