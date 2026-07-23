"""Evidence-graph contracts for the fourth G1 extraction architecture."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


EntityType = Literal[
    "lnp_formulation",
    "lnp_component",
    "payload",
    "encoded_product",
    "molecular_target",
    "targeting_ligand",
    "cell",
    "tissue_or_organ",
    "disease",
    "physiological_state",
    "species",
    "biological_model",
    "intervention",
    "assay",
    "endpoint",
    "outcome_value",
    "dose",
    "route",
    "timepoint",
]

Predicate = Literal[
    "has_formulation",
    "has_component",
    "has_component_role",
    "has_component_amount",
    "carries_payload",
    "encodes_product",
    "targets_molecule",
    "has_targeting_ligand",
    "delivered_to_cell",
    "therapeutic_target_cell",
    "has_tissue_context",
    "has_disease_context",
    "has_physiological_context",
    "has_species",
    "has_biological_model",
    "has_intervention",
    "has_assay",
    "has_route",
    "has_dose",
    "has_timepoint",
    "measures_endpoint",
    "has_outcome_value",
    "compared_with",
]


class SourceClauseV4(StrictModel):
    clause_id: str
    sentence_id: str
    text: str = Field(min_length=1)


class EvidenceSpanV4(StrictModel):
    clause_id: str
    quote: str = Field(min_length=1)


class EntityV4(StrictModel):
    entity_id: str
    entity_type: EntityType
    reported_name: str = Field(min_length=1)
    normalized_name: str | None = None
    normalization_status: Literal["exact", "synonym", "inferred", "unresolved"]
    evidence: list[EvidenceSpanV4] = Field(min_length=1)


class ClaimV4(StrictModel):
    claim_id: str
    experiment_id: str | Literal["SHARED"]
    subject_entity_id: str
    predicate: Predicate
    object_entity_id: str
    evidence: list[EvidenceSpanV4] = Field(min_length=1)


class ExperimentV4(StrictModel):
    experiment_id: str
    label: str
    claim_ids: list[str] = Field(min_length=1)
    shared_claim_ids: list[str] = []
    source_scope_clause_ids: list[str] = Field(min_length=1)
    boundary_status: Literal["explicit", "inferred", "ambiguous"]
    boundary_reason: str


class EvidenceGraphV4(StrictModel):
    contract_version: Literal["4.0.0"]
    paper_id: str
    source_scope: Literal["abstract_only", "full_text", "full_text_with_supplement"]
    original_lnp_experiments_present: bool
    entities: list[EntityV4]
    claims: list[ClaimV4]
    experiments: list[ExperimentV4]

    @model_validator(mode="after")
    def graph_links_exist(self):
        entity_ids = {row.entity_id for row in self.entities}
        claim_ids = {row.claim_id for row in self.claims}
        if len(entity_ids) != len(self.entities) or len(claim_ids) != len(self.claims):
            raise ValueError("entity_id and claim_id values must be unique")
        experiment_ids = {row.experiment_id for row in self.experiments}
        if len(experiment_ids) != len(self.experiments):
            raise ValueError("experiment_id values must be unique")
        for claim in self.claims:
            if claim.subject_entity_id not in entity_ids or claim.object_entity_id not in entity_ids:
                raise ValueError(f"{claim.claim_id} references an unknown entity")
            if claim.experiment_id != "SHARED" and claim.experiment_id not in experiment_ids:
                raise ValueError(f"{claim.claim_id} references an unknown experiment")
        for experiment in self.experiments:
            if not set(experiment.claim_ids + experiment.shared_claim_ids) <= claim_ids:
                raise ValueError(f"{experiment.experiment_id} references an unknown claim")
            if any(
                next(row for row in self.claims if row.claim_id == claim_id).experiment_id
                not in {experiment.experiment_id, "SHARED"}
                for claim_id in experiment.claim_ids + experiment.shared_claim_ids
            ):
                raise ValueError(f"{experiment.experiment_id} links another experiment's claim")
        if self.original_lnp_experiments_present != bool(self.experiments):
            raise ValueError("experiment presence flag must match experiments")
        return self


class VerifierObservationV4(StrictModel):
    observation_id: str
    experiment_id: str | None
    claim_id: str | None
    issue_type: Literal[
        "unsupported",
        "omitted_claim",
        "wrong_entity_type",
        "wrong_experiment_link",
        "merged_claim",
        "over_normalized",
        "boundary_ambiguity",
    ]
    action: Literal["corrected", "removed", "added", "ambiguous"]
    explanation: str
    evidence: list[EvidenceSpanV4]


class VerifiedEvidenceGraphV4(StrictModel):
    contract_version: Literal["4.0.0"]
    paper_id: str
    source_read_again: Literal[True]
    observations: list[VerifierObservationV4]
    corrected_graph: EvidenceGraphV4
    unresolved_ambiguities: list[str]

    @model_validator(mode="after")
    def paper_matches(self):
        if self.corrected_graph.paper_id != self.paper_id:
            raise ValueError("corrected graph paper_id mismatch")
        return self
