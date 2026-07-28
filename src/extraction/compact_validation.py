"""Normalize compact-extraction validation failures into repairable findings."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.extraction.compact_contracts import (
    CompactExtractionResponse,
    ReportedField,
)


COLLECTIONS = {"formulations", "components", "experiments", "outcomes"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValidationFinding(StrictModel):
    """One deterministic validation failure, with a field-level repair boundary."""

    finding_id: str
    code: str
    message: str
    location: list[str | int]
    record_collection: str | None = None
    record_index: int | None = Field(default=None, ge=0)
    field_name: str | None = None
    cited_evidence_ids: list[str] = Field(default_factory=list)
    repairable: bool


class ValidationReport(StrictModel):
    report_version: str = "compact-validation-1.0.0"
    paper_id: str
    status: Literal["valid", "invalid"]
    findings: list[ValidationFinding]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _finding_id(
    paper_id: str, code: str, location: list[str | int], message: str
) -> str:
    digest = hashlib.sha256(
        _canonical_json([paper_id, code, location, message]).encode("utf-8")
    ).hexdigest()[:16]
    return f"VF-{digest}"


def _evidence_ids(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence_ids" and isinstance(child, list):
                found.extend(item for item in child if isinstance(item, str))
            else:
                found.extend(_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_evidence_ids(child))
    return list(dict.fromkeys(found))


def _record_at(candidate: dict[str, Any], location: list[str | int]) -> Any:
    if len(location) < 2:
        return {}
    collection, index = location[0], location[1]
    if collection not in COLLECTIONS or not isinstance(index, int):
        return {}
    rows = candidate.get(collection)
    if not isinstance(rows, list) or index >= len(rows):
        return {}
    return rows[index]


def _finding(
    *,
    paper_id: str,
    code: str,
    message: str,
    location: list[str | int],
    candidate: dict[str, Any],
) -> ValidationFinding:
    collection = location[0] if location and location[0] in COLLECTIONS else None
    index = (
        location[1]
        if collection and len(location) > 1 and isinstance(location[1], int)
        else None
    )
    field_name = (
        location[2]
        if index is not None and len(location) > 2 and isinstance(location[2], str)
        else None
    )
    repairable = collection is not None and index is not None and field_name is not None
    record = _record_at(candidate, location)
    evidence_scope = (
        record.get(field_name)
        if field_name is not None and isinstance(record, dict)
        else record
    )
    return ValidationFinding(
        finding_id=_finding_id(paper_id, code, location, message),
        code=code,
        message=message,
        location=location,
        record_collection=collection,
        record_index=index,
        field_name=field_name,
        cited_evidence_ids=_evidence_ids(evidence_scope),
        repairable=repairable,
    )


def validate_candidate(
    candidate_text: str,
    *,
    paper_id: str,
    allowed_evidence_ids: set[str],
) -> tuple[CompactExtractionResponse | None, ValidationReport]:
    """Validate one first-call candidate and return machine-readable findings."""
    try:
        candidate = json.loads(candidate_text)
    except json.JSONDecodeError as error:
        finding = _finding(
            paper_id=paper_id,
            code="invalid_json",
            message=str(error),
            location=[],
            candidate={},
        )
        return None, ValidationReport(
            paper_id=paper_id, status="invalid", findings=[finding]
        )

    try:
        parsed = CompactExtractionResponse.model_validate(candidate)
    except ValidationError as error:
        findings = [
            _finding(
                paper_id=paper_id,
                code=f"pydantic.{item['type']}",
                message=item["msg"],
                location=list(item["loc"]),
                candidate=candidate,
            )
            for item in error.errors(include_url=False)
        ]
        return None, ValidationReport(
            paper_id=paper_id, status="invalid", findings=findings
        )

    findings: list[ValidationFinding] = []
    if parsed.paper_id != paper_id:
        findings.append(
            _finding(
                paper_id=paper_id,
                code="paper_id_mismatch",
                message=(
                    f"Response paper_id {parsed.paper_id!r} does not match "
                    f"requested {paper_id!r}"
                ),
                location=["paper_id"],
                candidate=candidate,
            )
        )

    unknown_eligibility = sorted(
        set(parsed.eligibility.evidence_ids) - allowed_evidence_ids
    )
    if unknown_eligibility:
        findings.append(
            _finding(
                paper_id=paper_id,
                code="unknown_evidence_id",
                message=f"Unknown evidence IDs: {unknown_eligibility}",
                location=["eligibility", "evidence_ids"],
                candidate=candidate,
            )
        )

    for collection in COLLECTIONS:
        for index, record in enumerate(getattr(parsed, collection)):
            for field_name in record.__class__.model_fields:
                value = getattr(record, field_name)
                if not isinstance(value, ReportedField):
                    continue
                unknown = sorted(set(value.evidence_ids) - allowed_evidence_ids)
                if unknown:
                    findings.append(
                        _finding(
                            paper_id=paper_id,
                            code="unknown_evidence_id",
                            message=f"Unknown evidence IDs: {unknown}",
                            location=[collection, index, field_name],
                            candidate=candidate,
                        )
                    )

    report = ValidationReport(
        paper_id=paper_id,
        status="valid" if not findings else "invalid",
        findings=findings,
    )
    return (parsed if not findings else None), report
