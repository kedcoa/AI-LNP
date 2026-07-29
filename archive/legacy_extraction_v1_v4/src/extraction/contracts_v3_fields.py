"""Experiment-scoped field contracts for the third G1 attempt."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceValueV3(StrictModel, Generic[T]):
    value: T | None
    status: Literal["reported", "missing"]
    evidence_sentence_id: str | None
    evidence_quote: str | None
    missing_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def supply_standard_missing_reason(cls, value):
        if isinstance(value, dict) and value.get("status") == "missing":
            return {
                **value,
                "value": None,
                "evidence_sentence_id": None,
                "evidence_quote": None,
                "missing_reason": value.get("missing_reason") or "Not explicitly reported in the approved experiment sentences.",
            }
        return value

    @model_validator(mode="after")
    def source_is_complete(self):
        if self.status == "reported":
            if self.value is None or not self.evidence_sentence_id or not self.evidence_quote:
                raise ValueError("reported values require value, sentence ID, and quote")
            if self.missing_reason is not None:
                raise ValueError("reported values cannot have a missing reason")
        elif any(value is not None for value in (self.value, self.evidence_sentence_id, self.evidence_quote)):
            raise ValueError("missing values require null value, sentence ID, and quote")
        elif not self.missing_reason:
            raise ValueError("missing values require a reason")
        return self


TextValueV3 = SourceValueV3[str]
NumberValueV3 = SourceValueV3[float]


class CellEntityV3(StrictModel):
    cell_entity_id: str
    cell_name_reported: TextValueV3
    cell_type_normalized: SourceValueV3[
        Literal[
            "hepatocyte", "kupffer_cell", "liver_sinusoidal_endothelial_cell",
            "hepatic_stellate_cell", "macrophage", "endothelial_cell",
            "non_parenchymal_cell", "tumor_cell", "other",
        ]
    ]


class LNPComponentV3(StrictModel):
    lnp_component_id: str
    lnp_component_name_reported: TextValueV3
    lnp_component_role: SourceValueV3[
        Literal[
            "ionizable_lipid", "helper_lipid", "sterol", "peg_lipid",
            "targeting_ligand", "targeting_anchor", "sort_lipid",
            "other_lnp_material",
        ]
    ]
    lnp_component_amount_reported: NumberValueV3
    lnp_component_amount_unit_reported: TextValueV3


class LNPOutcomeV3(StrictModel):
    lnp_outcome_id: str
    endpoint_family: SourceValueV3[
        Literal[
            "uptake", "functional_expression", "transfection", "gene_knockdown",
            "gene_editing", "viability", "toxicity", "biodistribution",
            "therapeutic_effect", "molecular_mechanism", "other",
        ]
    ]
    endpoint_name_reported: TextValueV3
    outcome_numeric_value_reported: NumberValueV3
    outcome_unit_reported: TextValueV3
    outcome_qualitative_value_reported: TextValueV3
    comparator_reported: TextValueV3
    timepoint_value_reported: NumberValueV3
    timepoint_unit_reported: TextValueV3


class ExperimentScopedExtractionV3(StrictModel):
    contract_version: Literal["3.1.0"]
    paper_id: str
    lnp_experiment_id: str
    experiment_label: str
    is_lnp_experiment: bool
    lnp_formulation_name_reported: TextValueV3
    lnp_formulation_description_reported: TextValueV3
    lnp_composition_raw_reported: TextValueV3
    lnp_components: list[LNPComponentV3]
    payload_type_reported: SourceValueV3[Literal["mRNA", "siRNA", "sgRNA", "saRNA", "circRNA", "other"]]
    payload_name_reported: TextValueV3
    payload_encoded_product_reported: TextValueV3
    payload_molecular_target_reported: TextValueV3
    targeting_ligand_reported: TextValueV3
    cell_entities: list[CellEntityV3]
    delivery_recipient_cell_entity_ids: list[str]
    therapeutic_target_cell_entity_ids: list[str]
    tissue_or_organ_reported: TextValueV3
    disease_context_reported: TextValueV3
    species_reported: TextValueV3
    experimental_context_reported: SourceValueV3[Literal["in_vitro", "ex_vivo", "in_vivo"]]
    biological_model_reported: TextValueV3
    dose_value_reported: NumberValueV3
    dose_unit_reported: TextValueV3
    administration_route_reported: TextValueV3
    assay_reported: TextValueV3
    comparator_reported: TextValueV3
    lnp_outcomes: list[LNPOutcomeV3]

    @field_validator("delivery_recipient_cell_entity_ids", "therapeutic_target_cell_entity_ids")
    @classmethod
    def unique_references(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("cell entity references must be unique")
        return values

    @model_validator(mode="after")
    def validate_links_and_material_boundary(self):
        cell_ids = {row.cell_entity_id for row in self.cell_entities}
        referenced = set(self.delivery_recipient_cell_entity_ids + self.therapeutic_target_cell_entity_ids)
        if not referenced <= cell_ids:
            raise ValueError("cell role references an unknown cell_entity_id")
        for component in self.lnp_components:
            name = str(component.lnp_component_name_reported.value or "").lower()
            if any(token in name for token in ("mrna", "sirna", "sgrna", "rna payload")):
                raise ValueError("RNA payload cannot be an LNP component")
        return self


class VerificationIssueV3(StrictModel):
    experiment_id: str
    field_name: str
    issue_type: Literal[
        "unsupported_value", "omitted_fact", "wrong_entity", "wrong_link",
        "merged_outcomes", "evidence_mismatch", "over_normalization",
    ]
    severity: Literal["blocking", "review"]
    explanation: str
    supporting_or_corrective_sentence_id: str | None
    supporting_or_corrective_quote: str | None


class PaperVerificationV3(StrictModel):
    contract_version: Literal["3.1.0"]
    paper_id: str
    source_read_again: Literal[True]
    issues: list[VerificationIssueV3]
    completeness_assessment: Literal["complete", "incomplete", "cannot_verify"]
    verifier_summary: str
