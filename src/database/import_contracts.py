"""Typed, evidence-preserving contract for one-paper database imports."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")

SUPPORTED_SOURCE_KINDS = frozenset(
    {
        "pdf",
        "xml",
        "html",
        "text",
        "table",
        "figure",
        "supplement",
        "validated_extraction",
        "deterministic_reconciliation",
        "source_inventory",
        "screening_manifest",
        "manual_transcription",
    }
)
EVIDENCE_SOURCE_KINDS = SUPPORTED_SOURCE_KINDS - {"screening_manifest"}

CompletenessStatus = Literal["complete", "incomplete", "conflict", "quarantined"]
VerificationStatus = Literal[
    "unreviewed",
    "automatically_validated",
    "manually_verified",
    "ambiguous",
    "conflict",
    "rejected",
]


@dataclass(frozen=True)
class SourceArtifactRecord:
    artifact_id: str
    path: str
    sha256: str
    source_kind: str
    pipeline_name: str
    pipeline_version: str | None = None
    extraction_run_identifier: str | None = None


@dataclass(frozen=True)
class PaperRecord:
    source_paper_id: str
    artifact_id: str
    title: str
    source_type: str
    retrieval_date: str
    screening_status: str = "manual_review"
    import_status: str = "needs_review"
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    authors: str | None = None
    journal: str | None = None
    publication_year: int | None = None
    source_url: str | None = None
    search_query_id: str | None = None
    full_text_status: str = "unknown"
    screening_reason: str | None = None


@dataclass(frozen=True)
class FormulationRecord:
    record_id: str
    paper_id: str
    artifact_id: str
    formulation_name: str | None = None
    chemical_formulation_total: str | None = None
    lnp_molar_ratio: str | None = None
    composition_raw: str | None = None
    composition_basis: str | None = None
    np_ratio: float | None = None
    formulation_notes: str | None = None
    formulation_review_status: str = "unreviewed"


@dataclass(frozen=True)
class ComponentRecord:
    record_id: str
    paper_id: str
    artifact_id: str
    formulation_id: str
    component_name_reported: str
    component_role: str
    component_name_normalized: str | None = None
    inchikey: str | None = None
    molar_percentage: float | None = None
    percentage_unit: str | None = None
    component_review_status: str = "unreviewed"
    identity_source: str | None = None
    identity_notes: str | None = None
    amount_value: float | None = None
    amount_unit: str | None = None
    amount_raw: str | None = None
    composition_position: int | None = None


@dataclass(frozen=True)
class ArmRecord:
    record_id: str
    paper_id: str
    artifact_id: str
    formulation_id: str
    cell_type: str
    cell_source: str | None = None
    tissue_or_organ: str | None = None
    species: str | None = None
    disease_model: str | None = None
    in_vitro_in_vivo: str | None = None
    payload_type: str | None = None
    payload_name: str | None = None
    payload_encoded_product: str | None = None
    payload_molecular_target: str | None = None
    reporter: str | None = None
    dose: float | None = None
    dose_unit: str | None = None
    route: str | None = None
    timepoint: float | None = None
    timepoint_unit: str | None = None
    assay: str | None = None
    comparator_type: str | None = None
    comparator_description: str | None = None
    protocol_reference: str | None = None
    experiment_notes: str | None = None
    completeness_status: CompletenessStatus = "incomplete"
    verification_status: VerificationStatus = "unreviewed"
    nearest_neighbor_eligible: bool = False
    comet_eligible: bool = False
    quarantine_reason: str | None = None


@dataclass(frozen=True)
class OutcomeRecord:
    record_id: str
    paper_id: str
    artifact_id: str
    arm_id: str
    endpoint_family: str
    endpoint_name: str
    value_status: str
    outcome_value: float | None = None
    outcome_unit: str | None = None
    normalization_basis: str | None = None
    uncertainty_value: float | None = None
    uncertainty_type: str | None = None
    qualitative_outcome: str | None = None
    outcome_notes: str | None = None


@dataclass(frozen=True)
class EvidenceRecord:
    record_id: str
    paper_id: str
    artifact_id: str
    field_name: str
    evidence_location_type: str
    extraction_method: str
    extraction_confidence: str
    evidence_text: str | None = None
    structured_evidence: dict[str, Any] | list[Any] | None = None
    arm_id: str | None = None
    outcome_id: str | None = None
    section_name: str | None = None
    page_number: str | None = None
    table_number: str | None = None
    figure_number: str | None = None
    supplement_identifier: str | None = None
    verification_status: VerificationStatus = "unreviewed"
    reviewer_notes: str | None = None


@dataclass(frozen=True)
class FieldEvidenceLink:
    paper_id: str
    entity_type: Literal["formulation", "component", "arm", "outcome"]
    entity_id: str
    field_name: str
    evidence_ids: tuple[str, ...]
    verification_status: VerificationStatus = "unreviewed"
    notes: str | None = None


@dataclass(frozen=True)
class ReviewRecord:
    record_id: str
    paper_id: str
    artifact_id: str
    reason_code: str
    status: Literal["incomplete", "conflict", "quarantined", "blocked"]
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    arm_id: str | None = None
    outcome_id: str | None = None
    field_name: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ImportBundle:
    paper: PaperRecord
    artifacts: tuple[SourceArtifactRecord, ...] = field(default_factory=tuple)
    formulations: tuple[FormulationRecord, ...] = field(default_factory=tuple)
    components: tuple[ComponentRecord, ...] = field(default_factory=tuple)
    arms: tuple[ArmRecord, ...] = field(default_factory=tuple)
    outcomes: tuple[OutcomeRecord, ...] = field(default_factory=tuple)
    evidence: tuple[EvidenceRecord, ...] = field(default_factory=tuple)
    field_evidence_links: tuple[FieldEvidenceLink, ...] = field(
        default_factory=tuple
    )
    reviews: tuple[ReviewRecord, ...] = field(default_factory=tuple)
    schema_version: str = "day2-import-bundle/v1"

    def __post_init__(self) -> None:
        _validate_bundle(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ImportBundle":
        """Build and validate a bundle from a JSON-compatible mapping."""

        links = []
        for value in payload.get("field_evidence_links", []):
            link = dict(value)
            link["evidence_ids"] = tuple(link.get("evidence_ids", ()))
            links.append(FieldEvidenceLink(**link))
        return cls(
            schema_version=payload.get(
                "schema_version", "day2-import-bundle/v1"
            ),
            artifacts=tuple(
                SourceArtifactRecord(**value)
                for value in payload.get("artifacts", [])
            ),
            paper=PaperRecord(**payload["paper"]),
            formulations=tuple(
                FormulationRecord(**value)
                for value in payload.get("formulations", [])
            ),
            components=tuple(
                ComponentRecord(**value)
                for value in payload.get("components", [])
            ),
            arms=tuple(
                ArmRecord(**value) for value in payload.get("arms", [])
            ),
            outcomes=tuple(
                OutcomeRecord(**value)
                for value in payload.get("outcomes", [])
            ),
            evidence=tuple(
                EvidenceRecord(**value)
                for value in payload.get("evidence", [])
            ),
            field_evidence_links=tuple(links),
            reviews=tuple(_review_from_dict(value) for value in payload.get("reviews", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible representation."""

        return asdict(self)


def _require_unique_ids(records: tuple[Any, ...], kind: str) -> set[str]:
    identifiers = [record.record_id for record in records]
    if any(not value.strip() for value in identifiers):
        raise ValueError(f"{kind} record IDs must not be empty")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate {kind} record ID")
    return set(identifiers)


def _validate_number(
    field_name: str,
    value: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite numeric value")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be a finite numeric value")
    if minimum is not None and numeric < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and numeric > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")


def _review_from_dict(value: dict[str, Any]) -> ReviewRecord:
    review = dict(value)
    review["evidence_ids"] = tuple(review.get("evidence_ids", ()))
    return ReviewRecord(**review)


def _validate_bundle(bundle: ImportBundle) -> None:
    if bundle.schema_version != "day2-import-bundle/v1":
        raise ValueError(f"unsupported import bundle schema: {bundle.schema_version}")
    paper_id = bundle.paper.source_paper_id
    if not paper_id.strip():
        raise ValueError("source paper ID must not be empty")

    artifact_ids = set()
    artifacts = {}
    for artifact in bundle.artifacts:
        if not artifact.artifact_id.strip() or artifact.artifact_id in artifact_ids:
            raise ValueError("source artifact IDs must be non-empty and unique")
        artifact_ids.add(artifact.artifact_id)
        artifacts[artifact.artifact_id] = artifact
        if not artifact.path.strip():
            raise ValueError("source artifact path must not be empty")
        if not _SHA256.fullmatch(artifact.sha256):
            raise ValueError("source artifact SHA-256 must contain 64 hex characters")
        if not artifact.pipeline_name.strip():
            raise ValueError("source artifact pipeline name must not be empty")
        if artifact.source_kind not in SUPPORTED_SOURCE_KINDS:
            raise ValueError(
                f"unsupported source kind: {artifact.source_kind}"
            )

    if bundle.paper.artifact_id not in artifact_ids:
        raise ValueError("paper references unknown source artifact")
    if (
        bundle.paper.screening_status == "exclude"
    ) != (bundle.paper.import_status == "screening_only"):
        raise ValueError("screening exclusion requires screening-only import state")

    scientific_records = (
        bundle.formulations
        + bundle.components
        + bundle.arms
        + bundle.outcomes
        + bundle.evidence
        + bundle.field_evidence_links
    )
    if bundle.paper.import_status == "screening_only" and scientific_records:
        raise ValueError("screening-only papers cannot contain scientific rows")

    for record in scientific_records + bundle.reviews:
        if record.paper_id != paper_id:
            raise ValueError(
                f"cross-paper record link: {record.paper_id} does not match {paper_id}"
            )

    formulations = _require_unique_ids(bundle.formulations, "formulation")
    components = _require_unique_ids(bundle.components, "component")
    arms = _require_unique_ids(bundle.arms, "arm")
    outcomes = _require_unique_ids(bundle.outcomes, "outcome")
    evidence = _require_unique_ids(bundle.evidence, "evidence")
    _require_unique_ids(bundle.reviews, "review")

    for record in (
        bundle.formulations
        + bundle.components
        + bundle.arms
        + bundle.outcomes
        + bundle.evidence
    ):
        if record.artifact_id not in artifact_ids:
            raise ValueError(
                f"{record.record_id} references unknown source artifact"
            )

    for record in bundle.formulations:
        _validate_number("np_ratio", record.np_ratio, minimum=0)
    for record in bundle.components:
        if record.formulation_id not in formulations:
            raise ValueError(
                f"component {record.record_id} references unknown formulation"
            )
        _validate_number("amount_value", record.amount_value, minimum=0)
        _validate_number(
            "molar_percentage",
            record.molar_percentage,
            minimum=0,
            maximum=100,
        )
        if record.composition_position is not None and record.composition_position < 1:
            raise ValueError("composition_position must be a positive integer")
    for record in bundle.arms:
        if record.formulation_id not in formulations:
            raise ValueError(f"arm {record.record_id} references unknown formulation")
        _validate_number("dose", record.dose, minimum=0)
        _validate_number("timepoint", record.timepoint, minimum=0)
        if (record.nearest_neighbor_eligible or record.comet_eligible) and (
            record.completeness_status != "complete"
            or record.verification_status
            not in {"automatically_validated", "manually_verified"}
        ):
            raise ValueError(f"unsafe eligibility state for arm {record.record_id}")
        if record.comet_eligible and record.verification_status != "manually_verified":
            raise ValueError(
                f"COMET eligibility requires manual verification for arm {record.record_id}"
            )
        if record.completeness_status == "quarantined" and not (
            record.quarantine_reason or ""
        ).strip():
            raise ValueError("quarantined arm requires a quarantine reason")

    for record in bundle.outcomes:
        if record.arm_id not in arms:
            raise ValueError(f"outcome {record.record_id} references unknown arm")
        _validate_number("outcome_value", record.outcome_value)
        _validate_number(
            "uncertainty_value", record.uncertainty_value, minimum=0
        )
        if record.value_status in {"reported", "normalized", "derived"}:
            if record.outcome_value is None:
                raise ValueError(
                    f"{record.value_status} outcome requires outcome_value"
                )
        elif record.value_status == "qualitative_only":
            if not (record.qualitative_outcome or "").strip():
                raise ValueError("qualitative outcome requires reported text")
        elif record.value_status != "missing":
            raise ValueError(f"unsupported outcome value status: {record.value_status}")

    evidence_by_id = {record.record_id: record for record in bundle.evidence}
    for record in bundle.evidence:
        if artifacts[record.artifact_id].source_kind not in EVIDENCE_SOURCE_KINDS:
            raise ValueError(
                "unsupported evidence source kind: "
                f"{artifacts[record.artifact_id].source_kind}"
            )
        if not (record.evidence_text or "").strip() and record.structured_evidence is None:
            raise ValueError(f"evidence {record.record_id} has no supported source text")
        if record.arm_id is not None and record.arm_id not in arms:
            raise ValueError(f"evidence {record.record_id} references unknown arm")
        if record.outcome_id is not None:
            if record.outcome_id not in outcomes:
                raise ValueError(
                    f"evidence {record.record_id} references unknown outcome"
                )
            outcome = next(row for row in bundle.outcomes if row.record_id == record.outcome_id)
            if record.arm_id is not None and record.arm_id != outcome.arm_id:
                raise ValueError(
                    f"evidence {record.record_id} crosses outcome and arm scopes"
                )
            if record.arm_id is None:
                raise ValueError(
                    f"outcome evidence requires arm scope: {record.record_id}"
                )

    entity_ids = {
        "formulation": formulations,
        "component": components,
        "arm": arms,
        "outcome": outcomes,
    }
    linked_fields: set[tuple[str, str, str]] = set()
    links_by_field: dict[
        tuple[str, str, str], list[FieldEvidenceLink]
    ] = {}
    for link in bundle.field_evidence_links:
        if link.entity_id not in entity_ids[link.entity_type]:
            raise ValueError(
                f"field link references unknown {link.entity_type}: {link.entity_id}"
            )
        if not link.evidence_ids:
            raise ValueError("field evidence link must contain evidence")
        for evidence_id in link.evidence_ids:
            if evidence_id not in evidence:
                raise ValueError(f"field link references unknown evidence: {evidence_id}")
            evidence_record = evidence_by_id[evidence_id]
            if link.entity_type == "outcome" and (
                evidence_record.outcome_id is not None
                and evidence_record.outcome_id != link.entity_id
            ):
                raise ValueError("field evidence link crosses outcome scope")
            if link.entity_type == "arm" and (
                evidence_record.arm_id is not None
                and evidence_record.arm_id != link.entity_id
            ):
                raise ValueError("field evidence link crosses arm scope")
        linked_fields.add((link.entity_type, link.entity_id, link.field_name))
        links_by_field.setdefault(
            (link.entity_type, link.entity_id, link.field_name), []
        ).append(link)

    required_fields = {
        "formulation": {
            "formulation_name",
            "composition_raw",
            "composition_basis",
            "np_ratio",
        },
        "component": {
            "component_name_reported",
            "component_name_normalized",
            "component_role",
            "inchikey",
            "molar_percentage",
            "percentage_unit",
        },
        "arm": {
            "cell_type",
            "cell_source",
            "tissue_or_organ",
            "species",
            "disease_model",
            "in_vitro_in_vivo",
            "payload_type",
            "payload_name",
            "payload_encoded_product",
            "payload_molecular_target",
            "reporter",
            "dose",
            "dose_unit",
            "route",
            "timepoint",
            "timepoint_unit",
            "assay",
            "comparator_type",
            "comparator_description",
            "protocol_reference",
        },
        "outcome": {
            "endpoint_family",
            "endpoint_name",
            "outcome_value",
            "outcome_unit",
            "normalization_basis",
            "uncertainty_value",
            "uncertainty_type",
            "qualitative_outcome",
        },
    }
    records_by_type = {
        "formulation": bundle.formulations,
        "component": bundle.components,
        "arm": bundle.arms,
        "outcome": bundle.outcomes,
    }
    for entity_type, records in records_by_type.items():
        for record in records:
            for field_name in required_fields[entity_type]:
                value = getattr(record, field_name)
                populated = value is not None and (
                    not isinstance(value, str) or bool(value.strip())
                )
                if (
                    entity_type == "arm"
                    and field_name == "cell_type"
                    and value == "not_reported"
                ):
                    populated = False
                if populated and (
                    entity_type,
                    record.record_id,
                    field_name,
                ) not in linked_fields:
                    raise ValueError(
                        f"unsupported {entity_type} field: "
                        f"{record.record_id}.{field_name}"
                    )

    arm_by_id = {arm.record_id: arm for arm in bundle.arms}
    outcome_by_id = {outcome.record_id: outcome for outcome in bundle.outcomes}
    formulation_by_id = {
        formulation.record_id: formulation
        for formulation in bundle.formulations
    }
    accepted_link_statuses = {
        "automatically_validated",
        "manually_verified",
    }
    for arm in bundle.arms:
        if not (arm.nearest_neighbor_eligible or arm.comet_eligible):
            continue
        related_records: list[tuple[str, Any]] = [
            ("formulation", formulation_by_id[arm.formulation_id]),
            ("arm", arm),
        ]
        related_records.extend(
            ("component", component)
            for component in bundle.components
            if component.formulation_id == arm.formulation_id
        )
        related_records.extend(
            ("outcome", outcome)
            for outcome in bundle.outcomes
            if outcome.arm_id == arm.record_id
        )
        related_field_links: list[
            tuple[object, str, list[FieldEvidenceLink]]
        ] = []
        for entity_type, record in related_records:
            for field_name in required_fields[entity_type]:
                value = getattr(record, field_name)
                populated = value is not None and (
                    not isinstance(value, str) or bool(value.strip())
                )
                if not populated:
                    continue
                field_links = links_by_field[
                    (entity_type, record.record_id, field_name)
                ]
                related_field_links.append((record, field_name, field_links))
        related_links = [
            link
            for _, _, field_links in related_field_links
            for link in field_links
        ]
        if not any(
            evidence_by_id[evidence_id].verification_status
            == "manually_verified"
            for link in related_links
            for evidence_id in link.evidence_ids
        ):
            if any(
                evidence_by_id[evidence_id].verification_status
                == "automatically_validated"
                for link in related_links
                for evidence_id in link.evidence_ids
            ):
                raise ValueError(
                    "core schema cannot persist accepted automatic "
                    f"evidence for eligible arm {arm.record_id}"
                )
            raise ValueError(
                f"eligible arm requires accepted evidence: {arm.record_id}"
            )
        arm_outcome_ids = {
            outcome.record_id
            for outcome in bundle.outcomes
            if outcome.arm_id == arm.record_id
        }
        if not any(
            link.entity_type == "outcome"
            and link.entity_id in arm_outcome_ids
            and link.verification_status in accepted_link_statuses
            and any(
                evidence_by_id[evidence_id].outcome_id == link.entity_id
                and evidence_by_id[evidence_id].verification_status
                == "manually_verified"
                for evidence_id in link.evidence_ids
            )
            for link in related_links
        ):
            raise ValueError(
                "eligible arm requires accepted outcome evidence: "
                f"{arm.record_id}"
            )
        for record, field_name, field_links in related_field_links:
            if not any(
                link.verification_status in accepted_link_statuses
                and any(
                    evidence_by_id[evidence_id].verification_status
                    == "manually_verified"
                    for evidence_id in link.evidence_ids
                )
                for link in field_links
            ):
                raise ValueError(
                    "eligible arm requires accepted field evidence: "
                    f"{record.record_id}.{field_name}"
                )

    reviewed_arm_ids: set[str] = set()
    for review in bundle.reviews:
        if review.artifact_id not in artifact_ids:
            raise ValueError(f"review {review.record_id} references unknown artifact")
        if review.arm_id is not None and review.arm_id not in arms:
            raise ValueError(f"review {review.record_id} references unknown arm")
        if review.outcome_id is not None and review.outcome_id not in outcomes:
            raise ValueError(f"review {review.record_id} references unknown outcome")
        for evidence_id in review.evidence_ids:
            if evidence_id not in evidence:
                raise ValueError(
                    f"review {review.record_id} references unknown evidence"
                )
        if review.status == "quarantined" and not review.evidence_ids:
            raise ValueError("quarantined review requires exact evidence")
        target_arm_id = review.arm_id
        if review.outcome_id is not None:
            outcome_arm_id = outcome_by_id[review.outcome_id].arm_id
            if target_arm_id is not None and target_arm_id != outcome_arm_id:
                raise ValueError("review crosses arm and outcome scopes")
            target_arm_id = outcome_arm_id
        if review.status == "quarantined" and target_arm_id is None:
            raise ValueError(
                "quarantined review requires arm or outcome scope"
            )
        for evidence_id in review.evidence_ids:
            evidence_record = evidence_by_id[evidence_id]
            if review.outcome_id is not None and (
                evidence_record.outcome_id != review.outcome_id
                or evidence_record.arm_id != target_arm_id
            ):
                raise ValueError("review evidence is outside outcome scope")
            if (
                review.outcome_id is None
                and target_arm_id is not None
                and evidence_record.arm_id != target_arm_id
            ):
                raise ValueError("review evidence is outside arm scope")
        if target_arm_id is not None:
            reviewed_arm_ids.add(target_arm_id)
            target_arm = arm_by_id[target_arm_id]
            if review.status == "blocked" and (
                target_arm.nearest_neighbor_eligible
                or target_arm.comet_eligible
            ):
                raise ValueError(
                    f"blocked review targets eligible arm {target_arm_id}"
                )
            if (
                review.status == "blocked"
                and target_arm.completeness_status != "quarantined"
            ):
                raise ValueError(
                    f"blocked review requires quarantined arm {target_arm_id}"
                )
        if target_arm_id is not None and review.status != "blocked":
            if arm_by_id[target_arm_id].completeness_status != review.status:
                raise ValueError(
                    f"review state contradicts arm {target_arm_id} status"
                )
    for arm in bundle.arms:
        if (
            arm.completeness_status
            in {"incomplete", "conflict", "quarantined"}
            and arm.record_id not in reviewed_arm_ids
        ):
            raise ValueError(
                f"unsafe arm {arm.record_id} requires a review record"
            )


__all__ = [
    "ArmRecord",
    "ComponentRecord",
    "EvidenceRecord",
    "FieldEvidenceLink",
    "FormulationRecord",
    "ImportBundle",
    "OutcomeRecord",
    "PaperRecord",
    "ReviewRecord",
    "SourceArtifactRecord",
]
