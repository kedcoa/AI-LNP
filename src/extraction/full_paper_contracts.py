"""Strict, gold-blind contracts for generalized full-paper extraction."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal, Mapping

from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.full_paper_inventory import FullPaperEvidenceBlock


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceBackedText(StrictModel):
    """A source-reported text value and its exact local support."""

    value: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class EvidenceBackedNumber(StrictModel):
    """A source-reported numeric value and its exact local support."""

    value: float
    evidence_ids: list[str] = Field(min_length=1)


class SharedComponent(StrictModel):
    component_id: str = Field(min_length=1)
    identity: EvidenceBackedText
    role: EvidenceBackedText | None = None


class SharedFormulation(StrictModel):
    formulation_id: str = Field(min_length=1)
    name: EvidenceBackedText
    components: list[SharedComponent]
    ratios: list[EvidenceBackedText]
    ratio_bases: list[EvidenceBackedText]

    @model_validator(mode="after")
    def require_unique_component_ids(self) -> "SharedFormulation":
        component_ids = [row.component_id for row in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component IDs must be unique within a formulation")
        return self


class SharedPayload(StrictModel):
    payload_id: str = Field(min_length=1)
    identity: EvidenceBackedText
    role: EvidenceBackedText | None = None


class RecipientContext(StrictModel):
    context_id: str = Field(min_length=1)
    recipient_cell: EvidenceBackedText | None = None
    organ: EvidenceBackedText | None = None

    @model_validator(mode="after")
    def require_recipient_or_organ(self) -> "RecipientContext":
        if self.recipient_cell is None and self.organ is None:
            raise ValueError("recipient context requires a cell or organ")
        return self


class PairingMetadata(StrictModel):
    """Explicit source metadata authorizing a reported joint arm."""

    kind: Literal["paired", "cross_product", "explicit_pairing"]
    paired_fields: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class ProvisionalExperimentContext(StrictModel):
    """One source-backed arm hypothesis; never a local Cartesian product."""

    provisional_context_id: str = Field(min_length=1)
    formulation_id: str = Field(min_length=1)
    payload_id: str = Field(min_length=1)
    dose: EvidenceBackedNumber
    dose_unit: EvidenceBackedText
    route: EvidenceBackedText
    species: EvidenceBackedText
    experimental_model: EvidenceBackedText
    recipient_cell: EvidenceBackedText
    organ: EvidenceBackedText | None = None
    timepoint: EvidenceBackedNumber
    timepoint_unit: EvidenceBackedText
    joint_evidence_ids: list[str] = Field(default_factory=list)
    outcome_evidence_ids: list[str] = Field(min_length=1)
    pairing_metadata: PairingMetadata | None = None

    @model_validator(mode="after")
    def require_supported_joint_membership(
        self,
    ) -> "ProvisionalExperimentContext":
        if not self.joint_evidence_ids and self.pairing_metadata is None:
            raise ValueError(
                "provisional context requires direct joint evidence or "
                "explicit pairing metadata"
            )
        return self


class AnchorAccountingEntry(StrictModel):
    disposition: Literal["mapped", "not_supported", "ambiguous"]
    record_ids: list[str]
    evidence_ids: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)


class PaperMapResponse(StrictModel):
    """Shared paper facts and source-backed provisional experiment contexts."""

    paper_map_version: Literal["full-paper-map-1.0.0"]
    paper_id: str = Field(min_length=1)
    formulations: list[SharedFormulation]
    payloads: list[SharedPayload]
    common_routes: list[EvidenceBackedText]
    common_species: list[EvidenceBackedText]
    common_models: list[EvidenceBackedText]
    recipient_contexts: list[RecipientContext]
    provisional_experiment_contexts: list[ProvisionalExperimentContext]
    anchor_accounting: dict[str, AnchorAccountingEntry]
    unresolved_items: list[str]

    @model_validator(mode="after")
    def validate_local_record_links(self) -> "PaperMapResponse":
        formulation_ids = [row.formulation_id for row in self.formulations]
        payload_ids = [row.payload_id for row in self.payloads]
        context_ids = [
            row.provisional_context_id
            for row in self.provisional_experiment_contexts
        ]
        if len(formulation_ids) != len(set(formulation_ids)):
            raise ValueError("formulation IDs must be unique")
        if len(payload_ids) != len(set(payload_ids)):
            raise ValueError("payload IDs must be unique")
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("provisional context IDs must be unique")
        known_formulations = set(formulation_ids)
        known_payloads = set(payload_ids)
        for context in self.provisional_experiment_contexts:
            if context.formulation_id not in known_formulations:
                raise ValueError(
                    "provisional context references an unknown formulation_id"
                )
            if context.payload_id not in known_payloads:
                raise ValueError(
                    "provisional context references an unknown payload_id"
                )
        return self


class AnchorCandidate(StrictModel):
    """One locally detected evidence anchor requiring map accounting."""

    anchor_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    anchor_types: list[str] = Field(min_length=1)


class ContextCandidate(StrictModel):
    """Resolved, data-driven arm identity with candidate-specific provenance."""

    experiment_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    provisional_context_id: str = Field(min_length=1)
    formulation_id: str = Field(min_length=1)
    formulation: str = Field(min_length=1)
    payload_id: str = Field(min_length=1)
    payload: str = Field(min_length=1)
    dose: float
    dose_unit: str = Field(min_length=1)
    route: str = Field(min_length=1)
    species: str = Field(min_length=1)
    experimental_model: str = Field(min_length=1)
    recipient_cell: str = Field(min_length=1)
    organ: str | None = None
    timepoint: float
    timepoint_unit: str = Field(min_length=1)
    field_evidence_ids: dict[str, list[str]]
    joint_evidence_ids: list[str]
    outcome_evidence_ids: list[str] = Field(min_length=1)
    pairing_metadata: PairingMetadata | None = None

    @model_validator(mode="after")
    def require_all_identity_field_evidence(self) -> "ContextCandidate":
        required = {
            "formulation",
            "payload",
            "dose",
            "dose_unit",
            "route",
            "species",
            "experimental_model",
            "recipient_cell",
            "timepoint",
            "timepoint_unit",
        }
        if self.organ is not None:
            required.add("organ")
        missing = sorted(
            field_name
            for field_name in required
            if not self.field_evidence_ids.get(field_name)
        )
        unknown = sorted(set(self.field_evidence_ids) - required)
        if missing or unknown:
            raise ValueError(
                "candidate field evidence must exactly cover reported identity "
                f"fields; missing={missing}, unknown={unknown}"
            )
        if not self.joint_evidence_ids and self.pairing_metadata is None:
            raise ValueError(
                "candidate requires joint evidence or explicit pairing metadata"
            )
        return self

    @property
    def identity(self) -> tuple[str, ...]:
        return (
            self.formulation.casefold(),
            self.payload.casefold(),
            str(self.dose),
            self.dose_unit.casefold(),
            self.route.casefold(),
            self.species.casefold(),
            self.experimental_model.casefold(),
            self.recipient_cell.casefold(),
            (self.organ or "").casefold(),
            str(self.timepoint),
            self.timepoint_unit.casefold(),
        )


class ContextAccountingEntry(StrictModel):
    disposition: Literal["extracted", "ambiguous", "insufficient_evidence"]
    linked_experiment_ids: list[str]
    linked_outcome_ids: list[str]
    evidence_ids: list[str] = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_links_for_disposition(self) -> "ContextAccountingEntry":
        has_links = bool(
            self.linked_experiment_ids or self.linked_outcome_ids
        )
        if self.disposition == "extracted":
            if not self.linked_experiment_ids or not self.linked_outcome_ids:
                raise ValueError(
                    "extracted accounting requires experiment and outcome links"
                )
        elif has_links:
            raise ValueError(
                "non-extracted accounting entries cannot link returned records"
            )
        if len(self.linked_experiment_ids) != len(
            set(self.linked_experiment_ids)
        ) or len(self.linked_outcome_ids) != len(
            set(self.linked_outcome_ids)
        ):
            raise ValueError("accounting record links must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("accounting evidence IDs must be unique")
        return self


class PreparedRequest(StrictModel):
    """A complete local request artifact; no provider is contacted."""

    prepared_request_version: Literal["full-paper-request-1.0.0"]
    request_kind: Literal["paper_map"]
    paper_id: str
    model: str
    token_budget: int = Field(gt=0)
    estimated_input_tokens: int = Field(ge=0)
    anchor_candidates: list[AnchorCandidate]
    evidence: list[FullPaperEvidenceBlock]
    payload: dict[str, Any]
    response_schema: dict[str, Any]
    request: dict[str, Any]


class ContextTask(StrictModel):
    """One token-bounded, scientifically compatible context request."""

    context_task_version: Literal["full-paper-context-task-1.1.0"]
    task_id: str
    paper_id: str
    context_key: str
    token_budget: int = Field(gt=0)
    estimated_input_tokens: int = Field(ge=0)
    shared_formulations: list[SharedFormulation]
    shared_payloads: list[SharedPayload]
    candidates: list[ContextCandidate] = Field(min_length=1)
    evidence: list[FullPaperEvidenceBlock] = Field(min_length=1)
    candidate_evidence_envelopes: dict[str, list[str]]
    payload: dict[str, Any]
    response_schema: dict[str, Any]

    @model_validator(mode="after")
    def validate_candidate_envelope_keys(self) -> "ContextTask":
        candidate_ids = [row.candidate_id for row in self.candidates]
        if set(self.candidate_evidence_envelopes) != set(candidate_ids):
            raise ValueError(
                "candidate evidence envelopes must exactly match task candidates"
            )
        return self


def _exact_accounting_schema(
    base_schema: Mapping[str, Any],
    *,
    field_name: str,
    identifiers: list[str],
    entry_model: type[BaseModel],
    definition_name: str,
) -> dict[str, Any]:
    if any(not identifier for identifier in identifiers):
        raise ValueError("accounting identifiers cannot be empty")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("accounting identifiers must be unique")
    schema = deepcopy(dict(base_schema))
    entry_schema = to_strict_json_schema(entry_model)
    nested_definitions = entry_schema.pop("$defs", {})
    definitions = schema.setdefault("$defs", {})
    definitions.update(nested_definitions)
    definitions[definition_name] = entry_schema
    properties = schema.setdefault("properties", {})
    properties[field_name] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            identifier: {"$ref": f"#/$defs/{definition_name}"}
            for identifier in identifiers
        },
        "required": identifiers,
    }
    required = list(schema.setdefault("required", []))
    if field_name not in required:
        required.append(field_name)
    schema["required"] = required
    return schema


def build_paper_map_schema(
    anchor_candidates: list[AnchorCandidate],
) -> dict[str, Any]:
    """Require one closed accounting entry for every detected anchor."""

    return _exact_accounting_schema(
        to_strict_json_schema(PaperMapResponse),
        field_name="anchor_accounting",
        identifiers=[row.anchor_id for row in anchor_candidates],
        entry_model=AnchorAccountingEntry,
        definition_name="AnchorAccountingEntry",
    )


def build_context_response_schema(
    candidates: list[ContextCandidate],
) -> dict[str, Any]:
    """Add exact candidate accounting and locally issued experiment IDs."""

    schema = _exact_accounting_schema(
        to_strict_json_schema(CompactExtractionResponse),
        field_name="context_candidate_accounting",
        identifiers=[row.candidate_id for row in candidates],
        entry_model=ContextAccountingEntry,
        definition_name="ContextAccountingEntry",
    )
    issued_ids = list(
        dict.fromkeys(row.experiment_id for row in candidates)
    )
    definitions = schema["$defs"]
    for definition_name in ("ExperimentRecord", "OutcomeRecord"):
        definitions[definition_name]["properties"]["experiment_id"][
            "enum"
        ] = issued_ids
    return schema
