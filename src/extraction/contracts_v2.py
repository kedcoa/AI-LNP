"""Version-2 abstract extraction contracts with explicit scientific boundaries."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceValue(StrictModel, Generic[T]):
    value: T | None
    status: Literal["reported", "missing"]
    evidence_quote: str | None
    confidence: Literal["high", "medium", "low"] = "low"
    missing_reason: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def null_confidence_is_low(cls, value):
        return "low" if value is None else value

    @model_validator(mode="after")
    def validate_source_boundary(self):
        if self.status == "reported":
            if self.value is None or not self.evidence_quote:
                raise ValueError("reported values require a value and evidence_quote")
            if self.missing_reason is not None:
                raise ValueError("reported values cannot have missing_reason")
        else:
            if self.value is not None or self.evidence_quote is not None:
                raise ValueError("missing values require null value and evidence_quote")
            if not self.missing_reason:
                raise ValueError("missing values require missing_reason")
        return self


TextValue = SourceValue[str]
NumberValue = SourceValue[float]


class LNPFormulationV2(StrictModel):
    lnp_formulation_id: str
    lnp_formulation_name_reported: TextValue
    lnp_composition_raw_reported: TextValue
    lnp_composition_basis_reported: TextValue
    lnp_np_ratio_reported: NumberValue
    lnp_formulation_description_reported: TextValue


class LNPComponentV2(StrictModel):
    lnp_component_id: str
    lnp_formulation_id: str
    lnp_component_name_reported: TextValue
    lnp_component_role: SourceValue[
        Literal[
            "ionizable_lipid",
            "helper_lipid",
            "sterol",
            "peg_lipid",
            "targeting_ligand",
            "targeting_anchor",
            "sort_lipid",
            "other_lnp_material",
        ]
    ]
    lnp_component_amount_reported: NumberValue
    lnp_component_amount_unit_reported: TextValue
    lnp_component_identity_reported: TextValue


class LNPExperimentV2(StrictModel):
    lnp_experiment_id: str
    lnp_formulation_id: str
    delivery_recipient_cell_reported: TextValue
    delivery_recipient_cell_normalized: SourceValue[
        Literal["hepatocyte", "kupffer_cell", "lsec", "hsc", "other_liver_macrophage", "other"]
    ]
    therapeutic_target_cell_reported: TextValue
    therapeutic_target_cell_normalized: TextValue
    tissue_or_organ_reported: TextValue
    disease_context_reported: TextValue
    species_reported: TextValue
    experimental_context_reported: SourceValue[Literal["in_vitro", "ex_vivo", "in_vivo"]]
    payload_type_reported: SourceValue[Literal["mRNA", "siRNA", "saRNA", "circRNA", "other"]]
    payload_name_reported: TextValue
    payload_encoded_product_reported: TextValue
    payload_molecular_target_reported: TextValue
    dose_value_reported: NumberValue
    dose_unit_reported: TextValue
    administration_route_reported: TextValue
    timepoint_value_reported: NumberValue
    timepoint_unit_reported: TextValue
    assay_reported: TextValue
    comparator_reported: TextValue


class LNPOutcomeV2(StrictModel):
    lnp_outcome_id: str
    lnp_experiment_id: str
    endpoint_family: SourceValue[
        Literal[
            "uptake",
            "functional_expression",
            "transfection",
            "gene_knockdown",
            "gene_editing",
            "viability",
            "toxicity",
            "biodistribution",
            "therapeutic_effect",
            "other",
        ]
    ]
    endpoint_name_reported: TextValue
    outcome_numeric_value_reported: NumberValue
    outcome_unit_reported: TextValue
    outcome_qualitative_value_reported: TextValue
    normalization_basis_reported: TextValue
    uncertainty_value_reported: NumberValue
    uncertainty_type_reported: TextValue
    comparator_reported: TextValue


class AbstractExtractionV2(StrictModel):
    contract_version: Literal["2.0.0"]
    paper_id: str
    lnp_formulations: list[LNPFormulationV2]
    lnp_components: list[LNPComponentV2]
    lnp_experiments: list[LNPExperimentV2]
    lnp_outcomes: list[LNPOutcomeV2]

    @model_validator(mode="after")
    def validate_links_and_boundaries(self):
        formulation_ids = {row.lnp_formulation_id for row in self.lnp_formulations}
        experiment_ids = {row.lnp_experiment_id for row in self.lnp_experiments}
        if any(row.lnp_formulation_id not in formulation_ids for row in self.lnp_components):
            raise ValueError("lnp_component references unknown lnp_formulation_id")
        if any(row.lnp_formulation_id not in formulation_ids for row in self.lnp_experiments):
            raise ValueError("lnp_experiment references unknown lnp_formulation_id")
        if any(row.lnp_experiment_id not in experiment_ids for row in self.lnp_outcomes):
            raise ValueError("lnp_outcome references unknown lnp_experiment_id")
        for component in self.lnp_components:
            name = str(component.lnp_component_name_reported.value or "").lower()
            role = component.lnp_component_role.value
            if role is not None and any(token in name for token in ("mrna", "sirna", "sgrna", "rna payload")):
                raise ValueError("RNA payload cannot be stored as lnp_component")
        return self


class VerificationIssueV2(StrictModel):
    issue_type: Literal[
        "unsupported_value",
        "omitted_fact",
        "wrong_entity",
        "wrong_link",
        "merged_experiments",
        "merged_outcomes",
        "evidence_mismatch",
        "over_normalization",
    ]
    entity_id: str
    field_name: str
    severity: Literal["blocking", "review"]
    explanation: str
    supporting_or_corrective_quote: str | None


class SecondReadVerificationV2(StrictModel):
    contract_version: Literal["2.0.0"]
    paper_id: str
    source_read_again: Literal[True]
    issues: list[VerificationIssueV2]
    completeness_assessment: Literal["complete", "incomplete", "cannot_verify"]
    verifier_summary: str


class FormulationResponseV2(StrictModel):
    paper_id: str
    lnp_formulations: list[LNPFormulationV2]


class ComponentResponseV2(StrictModel):
    paper_id: str
    lnp_components: list[LNPComponentV2]


class ExperimentResponseV2(StrictModel):
    paper_id: str
    lnp_experiments: list[LNPExperimentV2]


class OutcomeResponseV2(StrictModel):
    paper_id: str
    lnp_outcomes: list[LNPOutcomeV2]
