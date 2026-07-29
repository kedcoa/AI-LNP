"""Local contracts for v1.2 claim atomization and experiment boundaries.

These records are built before any paid extraction call.  A biological noun
mention is not an outcome claim by itself: an atomic outcome must contain an
evidence-backed relationship and at least one asserted object or result.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from src.extraction.compact_contracts import StrictContract


MentionType = Literal[
    "formulation",
    "payload",
    "cell",
    "tissue_or_organ",
    "species",
    "model",
    "intervention",
    "assay",
    "endpoint",
    "value",
    "other",
]
ClaimKind = Literal[
    "outcome",
    "intervention",
    "assay",
    "context",
    "comparison",
]
PredicateV12 = Literal[
    "administered_to",
    "carries_payload",
    "delivered_to",
    "uptake_by",
    "expressed",
    "edited",
    "increased",
    "decreased",
    "reduced",
    "reached",
    "maintained",
    "colocalized_with",
    "localized_to",
    "recognized",
    "phagocytosed",
    "eliminated",
    "measured_by",
    "compared_with",
    "associated_with",
]


class EvidenceReferenceV12(StrictContract):
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    locator_type: Literal["text", "table_cell", "figure_region"] = "text"
    row_label: str | None = None
    column_label: str | None = None
    panel_label: str | None = None


class MentionV12(StrictContract):
    """A grounded noun/value mention; it is not automatically a candidate."""

    mention_id: str = Field(pattern=r"^MEN-[A-Za-z0-9._-]+$")
    mention_type: MentionType
    text: str = Field(min_length=1)
    evidence: list[EvidenceReferenceV12] = Field(min_length=1)


class AtomicClaimV12(StrictContract):
    """One asserted relationship, which may omit an endpoint or numeric value."""

    claim_id: str = Field(pattern=r"^ACL-[A-Za-z0-9._-]+$")
    claim_kind: ClaimKind
    subject_text: str = Field(min_length=1)
    predicate: PredicateV12
    object_text: str | None = None
    endpoint_text: str | None = None
    qualitative_result: str | None = None
    numeric_value: float | None = None
    value_text: str | None = None
    unit: str | None = None
    polarity: Literal["positive", "negative", "neutral"]
    intervention_context: list[str] = Field(default_factory=list)
    provisional_experiment_id: str | None = Field(
        default=None,
        pattern=r"^PEX-[A-Za-z0-9._-]+$",
    )
    evidence: list[EvidenceReferenceV12] = Field(min_length=1)
    review_status: Literal["supported", "needs_review"] = "supported"

    @model_validator(mode="after")
    def outcome_requires_an_asserted_result(self) -> "AtomicClaimV12":
        if self.claim_kind == "outcome" and not any(
            (
                self.object_text,
                self.endpoint_text,
                self.qualitative_result,
                self.numeric_value is not None,
                self.value_text,
            )
        ):
            raise ValueError(
                "An atomic outcome requires an asserted object, endpoint, or result"
            )
        if self.numeric_value is None and self.unit is not None:
            raise ValueError("A unit cannot be reported without a numeric value")
        return self


class ExperimentAnchorV12(StrictContract):
    anchor_type: Literal[
        "formulation",
        "payload",
        "intervention",
        "model",
        "cell_context",
        "assay",
        "dose",
        "route",
        "timepoint",
        "result_cluster",
    ]
    value: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class ProvisionalExperimentV12(StrictContract):
    provisional_experiment_id: str = Field(
        pattern=r"^PEX-[A-Za-z0-9._-]+$"
    )
    label: str = Field(min_length=1)
    anchors: list[ExperimentAnchorV12] = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    shared_context_claim_ids: list[str] = Field(default_factory=list)
    boundary_status: Literal["explicit", "inferred", "ambiguous"]
    boundary_reason: str = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def sparse_boundaries_must_abstain(self) -> "ProvisionalExperimentV12":
        discriminating = {
            "formulation",
            "payload",
            "intervention",
            "model",
            "cell_context",
            "assay",
        }
        if (
            not any(anchor.anchor_type in discriminating for anchor in self.anchors)
            and self.boundary_status != "ambiguous"
        ):
            raise ValueError(
                "A boundary without a discriminating anchor must be ambiguous"
            )
        return self


class ProvisionalExperimentInventoryV12(StrictContract):
    inventory_version: Literal["provisional-experiments-1.2.0"]
    paper_id: str = Field(min_length=1)
    source_packet_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiments: list[ProvisionalExperimentV12]
    unassigned_claim_ids: list[str] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_inventory(self) -> "ProvisionalExperimentInventoryV12":
        experiment_ids = [
            experiment.provisional_experiment_id
            for experiment in self.experiments
        ]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("provisional_experiment_id values must be unique")
        if any(identifier.startswith(("GX-", "GO-")) for identifier in experiment_ids):
            raise ValueError("gold identifiers cannot enter a provisional inventory")

        assigned_claim_ids = [
            claim_id
            for experiment in self.experiments
            for claim_id in experiment.claim_ids
        ]
        if len(assigned_claim_ids) != len(set(assigned_claim_ids)):
            raise ValueError("an atomic claim cannot belong to two experiments")
        if set(assigned_claim_ids) & set(self.unassigned_claim_ids):
            raise ValueError("a claim cannot be both assigned and unassigned")
        return self


class AtomicOutcomeCandidateV12(StrictContract):
    """A structurally deduplicated candidate backed by one or more claims."""

    candidate_id: str = Field(pattern=r"^AOC-[A-Za-z0-9._-]+$")
    paper_id: str = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)
    provisional_experiment_id: str | None = Field(
        default=None,
        pattern=r"^PEX-[A-Za-z0-9._-]+$",
    )
    subject_text: str = Field(min_length=1)
    predicate: PredicateV12
    object_text: str | None = None
    endpoint_text: str | None = None
    qualitative_result: str | None = None
    numeric_value: float | None = None
    value_text: str | None = None
    unit: str | None = None
    polarity: Literal["positive", "negative", "neutral"]
    evidence_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    route_hint: Literal["text", "vision"]
    confidence: Literal["high", "medium"]
    review_reasons: list[str] = Field(default_factory=list)
    structural_signature: str = Field(min_length=1)
