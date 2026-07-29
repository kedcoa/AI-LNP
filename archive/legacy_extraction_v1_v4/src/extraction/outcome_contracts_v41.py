"""Backward-compatible outcome completeness and atomic graph-patch contracts."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.extraction.contracts_v4 import ClaimV4, EntityV4, EvidenceGraphV4, EvidenceSpanV4


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MechanismStepV41(StrictModel):
    step_number: int = Field(ge=1)
    subject: str
    action: str
    object: str
    subject_role: Literal[
        "formulation", "payload", "recipient_cell", "effector_cell", "therapeutic_target"
    ]
    object_role: Literal[
        "payload", "recipient_cell", "effector_cell", "therapeutic_target", "endpoint"
    ]
    evidence: list[EvidenceSpanV4] = Field(min_length=1)


class ResultCandidateV41(StrictModel):
    candidate_id: str
    clause_id: str
    raw_text: str = Field(min_length=1)
    experiment_hint: str | None = None
    population: str | None = None
    endpoint_hint: str | None = None
    value_text: str = Field(min_length=1)
    value_type: Literal["numeric", "qualitative", "comparative"]
    polarity: Literal["positive", "negative", "neutral", "mixed"]
    detection_status: Literal[
        "detected", "not_detected", "below_detection", "not_applicable", "unclear"
    ]
    comparison: str | None = None
    evidence: list[EvidenceSpanV4] = Field(min_length=1)


class CandidateDispositionV41(StrictModel):
    candidate_id: str
    status: Literal["retained", "duplicate", "out_of_scope", "unsupported", "ambiguous"]
    claim_id: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def retained_requires_claim(self):
        if self.status == "retained" and not self.claim_id:
            raise ValueError("retained candidate disposition requires claim_id")
        if self.status != "retained" and self.claim_id:
            raise ValueError("only retained candidate dispositions may reference claim_id")
        return self


class OutcomeSidecarV41(StrictModel):
    contract_version: Literal["4.1.0"] = "4.1.0"
    paper_id: str
    candidates: list[ResultCandidateV41]
    dispositions: list[CandidateDispositionV41]
    mechanism_steps: list[MechanismStepV41] = Field(default_factory=list)

    @model_validator(mode="after")
    def every_candidate_has_one_disposition(self):
        candidate_ids = [row.candidate_id for row in self.candidates]
        disposition_ids = [row.candidate_id for row in self.dispositions]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate_id values must be unique")
        counts = Counter(disposition_ids)
        missing = set(candidate_ids) - set(disposition_ids)
        duplicates = sorted(key for key, value in counts.items() if value != 1)
        unknown = set(disposition_ids) - set(candidate_ids)
        if missing or duplicates or unknown:
            raise ValueError(
                f"candidate dispositions invalid: missing={sorted(missing)}, "
                f"duplicates={duplicates}, unknown={sorted(unknown)}"
            )
        return self


class ExperimentClaimAdditionV41(StrictModel):
    experiment_id: str
    claim_ids: list[str] = Field(min_length=1)
    source_scope_clause_ids: list[str] = Field(default_factory=list)


class GraphPatchV41(StrictModel):
    contract_version: Literal["4.1.0"] = "4.1.0"
    paper_id: str
    add_entities: list[EntityV4] = Field(default_factory=list)
    add_claims: list[ClaimV4] = Field(default_factory=list)
    experiment_claim_additions: list[ExperimentClaimAdditionV41] = Field(default_factory=list)
    dispositions: list[CandidateDispositionV41] = Field(default_factory=list)
    mechanism_steps: list[MechanismStepV41] = Field(default_factory=list)


def apply_graph_patch(graph: EvidenceGraphV4, patch: GraphPatchV41) -> EvidenceGraphV4:
    """Apply an additive patch atomically and validate the complete v4 graph."""
    if graph.paper_id != patch.paper_id:
        raise ValueError("patch paper_id does not match graph")
    payload = graph.model_dump(mode="json")
    entity_ids = {row["entity_id"] for row in payload["entities"]}
    claim_ids = {row["claim_id"] for row in payload["claims"]}
    experiment_ids = {row["experiment_id"] for row in payload["experiments"]}

    new_entity_ids = [row.entity_id for row in patch.add_entities]
    new_claim_ids = [row.claim_id for row in patch.add_claims]
    if entity_ids & set(new_entity_ids) or len(new_entity_ids) != len(set(new_entity_ids)):
        raise ValueError("patch adds duplicate entity_id")
    if claim_ids & set(new_claim_ids) or len(new_claim_ids) != len(set(new_claim_ids)):
        raise ValueError("patch adds duplicate claim_id")

    payload["entities"].extend(row.model_dump(mode="json") for row in patch.add_entities)
    payload["claims"].extend(row.model_dump(mode="json") for row in patch.add_claims)
    all_claim_ids = claim_ids | set(new_claim_ids)
    additions = {row.experiment_id: row.claim_ids for row in patch.experiment_claim_additions}
    if not set(additions) <= experiment_ids:
        raise ValueError("patch references unknown experiment_id")
    if any(not set(ids) <= all_claim_ids for ids in additions.values()):
        raise ValueError("patch experiment addition references unknown claim_id")
    for experiment in payload["experiments"]:
        for claim_id in additions.get(experiment["experiment_id"], []):
            if claim_id not in experiment["claim_ids"]:
                experiment["claim_ids"].append(claim_id)
        scope_additions = next(
            (row.source_scope_clause_ids for row in patch.experiment_claim_additions
             if row.experiment_id == experiment["experiment_id"]),
            [],
        )
        for clause_id in scope_additions:
            if clause_id not in experiment["source_scope_clause_ids"]:
                experiment["source_scope_clause_ids"].append(clause_id)
    return EvidenceGraphV4.model_validate(payload)
