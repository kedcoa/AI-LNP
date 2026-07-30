"""Strict, local accounting for the isolated primary-candidate trial.

This module deliberately has no provider or filesystem side effects.  The
trial request builder supplies the compact response schema and its ordered
candidate records; this module adds the dynamic accounting wrapper and later
grades a returned response against the same inputs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from .compact_contracts import CompactExtractionResponse


ACCOUNTING_CONTRACT_VERSION = "compact-accounting-trial-1.0.0"
TRIAL_ROUTE = "primary-candidate-accounting-trial"
TRIAL_ROUTE_VERSION = "compact-route-1.3.0-trial"

DISPOSITIONS = (
    "extracted",
    "duplicate",
    "not_outcome",
    "insufficient_evidence",
    "requires_visual",
    "ambiguous",
)
REASON_CODES = (
    "directly_reported",
    "same_fact_as_linked_outcome",
    "context_or_method_only",
    "malformed_candidate",
    "evidence_does_not_support_outcome",
    "visual_value_not_available_as_text",
    "conflicting_or_incomplete_evidence",
    "experiment_assignment_uncertain",
)


def _candidate_value(candidate: Any, name: str, default: Any = None) -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _candidate_ids(candidates: Iterable[Any]) -> list[str]:
    identifiers = [str(_candidate_value(candidate, "candidate_id")) for candidate in candidates]
    if any(identifier == "None" or not identifier for identifier in identifiers):
        raise ValueError("each accounting candidate requires a candidate_id")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("candidate IDs must be unique")
    return identifiers


def build_candidate_accounting_schema(
    compact_schema: Mapping[str, Any],
    candidates: Iterable[Any],
) -> dict[str, Any]:
    """Wrap a strict compact schema with exact-key candidate accounting."""

    schema = deepcopy(dict(compact_schema))
    candidate_ids = _candidate_ids(candidates)
    properties = schema.setdefault("properties", {})
    required = list(schema.setdefault("required", []))
    definitions = schema.setdefault("$defs", {})

    definitions["CandidateAccountingEntry"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
            "linked_outcome_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "evidence_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
            "reason_code": {"type": "string", "enum": list(REASON_CODES)},
        },
        "required": [
            "disposition",
            "linked_outcome_ids",
            "evidence_ids",
            "reason_code",
        ],
    }
    properties["accounting_contract_version"] = {
        "type": "string",
        "const": ACCOUNTING_CONTRACT_VERSION,
    }
    properties["candidate_accounting"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            candidate_id: {"$ref": "#/$defs/CandidateAccountingEntry"}
            for candidate_id in candidate_ids
        },
        "required": candidate_ids,
    }
    for field in ("accounting_contract_version", "candidate_accounting"):
        if field not in required:
            required.append(field)
    schema["required"] = required
    schema["additionalProperties"] = False
    return schema


def candidate_outcome_matches(candidate: Any, outcome: dict[str, Any]) -> bool:
    """Use the existing deterministic candidate/outcome comparison boundary."""

    from .check_atomic_coverage_v12 import _matches
    from .v12_structure_contracts import AtomicOutcomeCandidateV12

    parsed_candidate = (
        candidate
        if isinstance(candidate, AtomicOutcomeCandidateV12)
        else AtomicOutcomeCandidateV12.model_validate(candidate)
    )
    return bool(_matches([parsed_candidate], [outcome]))


def _request_evidence_ids(evidence_envelope: Any) -> set[str]:
    if isinstance(evidence_envelope, set):
        return set(evidence_envelope)
    if isinstance(evidence_envelope, Mapping):
        if "evidence_id" in evidence_envelope:
            return {str(evidence_envelope["evidence_id"])}
        return {str(key) for key in evidence_envelope}
    return {
        str(row["evidence_id"])
        for row in evidence_envelope
        if isinstance(row, Mapping) and row.get("evidence_id")
    }


def _has_visual_provenance(candidate: Any, evidence_envelope: Any) -> bool:
    if _candidate_value(candidate, "route_hint") == "vision":
        return True
    sources = " ".join(str(value) for value in _candidate_value(candidate, "source_ids", []))
    if any(token in sources.casefold() for token in ("figure", "fig-", "table")):
        return True
    allowed = set(_candidate_value(candidate, "evidence_ids", []))
    rows = (
        evidence_envelope.values()
        if isinstance(evidence_envelope, Mapping)
        else evidence_envelope
    )
    for row in rows:
        if not isinstance(row, Mapping) or row.get("evidence_id") not in allowed:
            continue
        source_kind = str(row.get("source_kind", "")).casefold()
        locator_type = str(row.get("locator_type", "")).casefold()
        if any(value in {"figure_region", "table_cell"} for value in (source_kind, locator_type)):
            return True
    return False


def _candidate_supports_not_outcome_reason(candidate: Any, reason_code: str) -> bool:
    diagnostics = [
        str(reason).casefold()
        for field in ("review_reasons", "diagnostic_reasons")
        for reason in _candidate_value(candidate, field, [])
    ]
    if reason_code == "malformed_candidate":
        return any("malformed" in reason for reason in diagnostics)
    return any("context" in reason or "method" in reason for reason in diagnostics)


def _error(report: dict[str, Any], code: str, message: str, **details: Any) -> None:
    report["errors"].append({"code": code, "message": message, **details})


def parse_accounting_response(
    response: Mapping[str, Any],
    candidates: Iterable[Any],
    request_evidence_envelope: Any,
) -> tuple[CompactExtractionResponse, dict[str, Any]]:
    """Parse a trial response and return its core response plus local report.

    Contract syntax errors are recorded in the report so callers can persist a
    review artifact.  Core compact-response validation deliberately remains
    delegated to :class:`CompactExtractionResponse` after removing the two
    trial-only fields.
    """

    candidate_rows = list(candidates)
    candidate_by_id = {
        str(_candidate_value(candidate, "candidate_id")): candidate
        for candidate in candidate_rows
    }
    expected_ids = set(_candidate_ids(candidate_rows))
    body = dict(response)
    accounting_version = body.pop("accounting_contract_version", None)
    accounting = body.pop("candidate_accounting", {})
    compact_response = CompactExtractionResponse.model_validate(body)
    outcome_ids = [outcome.outcome_id for outcome in compact_response.outcomes]
    unique_outcome_ids = set(outcome_ids)
    request_evidence_ids = _request_evidence_ids(request_evidence_envelope)
    unresolved_dispositions = DISPOSITIONS[2:]
    report: dict[str, Any] = {
        "accounting_contract_version": accounting_version,
        "candidates_sent": len(expected_ids),
        "candidates_accounted_for": 0,
        "accounting_completeness": 0.0,
        "valid_extracted": 0,
        "valid_duplicates": 0,
        "rejected_links": [],
        "unresolved_disposition_counts": {
            disposition: 0 for disposition in unresolved_dispositions
        },
        "unique_returned_outcomes": len(unique_outcome_ids),
        "structurally_confirmed_candidates": 0,
        "structurally_confirmed_candidate_ids": [],
        "errors": [],
    }

    if accounting_version != ACCOUNTING_CONTRACT_VERSION:
        _error(
            report,
            "accounting_contract_version_mismatch",
            "accounting_contract_version must match the trial contract",
        )
    if not isinstance(accounting, Mapping):
        _error(report, "candidate_accounting_not_object", "candidate_accounting must be an object")
        accounting = {}

    returned_ids = set(accounting)
    missing_ids = sorted(expected_ids - returned_ids)
    unknown_ids = sorted(returned_ids - expected_ids)
    if missing_ids:
        _error(
            report,
            "missing_candidate_keys",
            "candidate_accounting omitted sent candidate IDs",
            candidate_ids=missing_ids,
        )
    if unknown_ids:
        _error(
            report,
            "unknown_candidate_keys",
            "candidate_accounting included unknown candidate IDs",
            candidate_ids=unknown_ids,
        )
    accounted_ids = expected_ids & returned_ids
    report["candidates_accounted_for"] = len(accounted_ids)
    report["accounting_completeness"] = (
        len(accounted_ids) / len(expected_ids) if expected_ids else 1.0
    )
    if len(outcome_ids) != len(unique_outcome_ids):
        _error(
            report,
            "duplicate_returned_outcome_ids",
            "returned outcome_id values must be unique",
            outcome_ids=sorted(
                outcome_id
                for outcome_id in unique_outcome_ids
                if outcome_ids.count(outcome_id) > 1
            ),
        )

    outcomes_by_id = {
        outcome.outcome_id: outcome.model_dump(mode="json")
        for outcome in compact_response.outcomes
    }
    valid_structural_links: dict[str, set[str]] = {
        candidate_id: set() for candidate_id in expected_ids
    }
    malformed_entries: set[str] = set()
    invalid_candidates: set[str] = set()

    for candidate_id in sorted(accounted_ids):
        entry = accounting[candidate_id]
        if not isinstance(entry, Mapping):
            _error(
                report,
                "candidate_accounting_entry_not_object",
                "each candidate accounting entry must be an object",
                candidate_id=candidate_id,
            )
            malformed_entries.add(candidate_id)
            invalid_candidates.add(candidate_id)
            continue
        allowed_fields = {
            "disposition",
            "linked_outcome_ids",
            "evidence_ids",
            "reason_code",
        }
        unexpected_fields = sorted(set(entry) - allowed_fields)
        missing_fields = sorted(allowed_fields - set(entry))
        if unexpected_fields:
            _error(report, "unknown_entry_fields", "accounting entry contains unknown fields", candidate_id=candidate_id, fields=unexpected_fields)
            invalid_candidates.add(candidate_id)
        if missing_fields:
            _error(report, "missing_entry_fields", "accounting entry omitted required fields", candidate_id=candidate_id, fields=missing_fields)
            malformed_entries.add(candidate_id)
            invalid_candidates.add(candidate_id)
            continue
        disposition = entry["disposition"]
        reason_code = entry["reason_code"]
        linked_outcome_ids = entry["linked_outcome_ids"]
        accounting_evidence_ids = entry["evidence_ids"]
        if disposition not in DISPOSITIONS:
            _error(report, "invalid_disposition", "accounting disposition is not approved", candidate_id=candidate_id)
            invalid_candidates.add(candidate_id)
        if reason_code not in REASON_CODES:
            _error(report, "invalid_reason_code", "accounting reason_code is not approved", candidate_id=candidate_id)
            invalid_candidates.add(candidate_id)
        if not isinstance(linked_outcome_ids, list) or not all(isinstance(item, str) for item in linked_outcome_ids):
            _error(report, "invalid_linked_outcome_ids", "linked_outcome_ids must be a string list", candidate_id=candidate_id)
            linked_outcome_ids = []
            invalid_candidates.add(candidate_id)
        if not isinstance(accounting_evidence_ids, list) or not accounting_evidence_ids or not all(isinstance(item, str) for item in accounting_evidence_ids):
            _error(report, "invalid_accounting_evidence_ids", "evidence_ids must be a nonempty string list", candidate_id=candidate_id)
            accounting_evidence_ids = []
            invalid_candidates.add(candidate_id)
        if len(linked_outcome_ids) != len(set(linked_outcome_ids)):
            _error(report, "duplicate_linked_outcome_ids", "linked_outcome_ids must be unique", candidate_id=candidate_id)
            invalid_candidates.add(candidate_id)
        candidate_evidence_ids = set(_candidate_value(candidate_by_id[candidate_id], "evidence_ids", []))
        for evidence_id in accounting_evidence_ids:
            if evidence_id not in candidate_evidence_ids:
                _error(report, "evidence_outside_candidate_allowance", "accounting evidence is not supplied by this candidate", candidate_id=candidate_id, evidence_id=evidence_id)
                invalid_candidates.add(candidate_id)
            if evidence_id not in request_evidence_ids:
                _error(report, "evidence_outside_request_envelope", "accounting evidence is absent from the request envelope", candidate_id=candidate_id, evidence_id=evidence_id)
                invalid_candidates.add(candidate_id)
        if disposition in unresolved_dispositions:
            report["unresolved_disposition_counts"][disposition] += 1
            if linked_outcome_ids:
                _error(report, "unresolved_disposition_has_links", "unresolved dispositions cannot link an outcome", candidate_id=candidate_id)
                invalid_candidates.add(candidate_id)
        elif disposition in {"extracted", "duplicate"} and not linked_outcome_ids:
            _error(report, "resolved_disposition_missing_link", "extracted and duplicate dispositions require a linked outcome", candidate_id=candidate_id)
            invalid_candidates.add(candidate_id)
        if disposition == "requires_visual" and not _has_visual_provenance(candidate_by_id[candidate_id], request_evidence_envelope):
            _error(report, "requires_visual_without_visual_provenance", "requires_visual needs visual candidate provenance", candidate_id=candidate_id)
            invalid_candidates.add(candidate_id)
        if disposition == "not_outcome" and reason_code in {"context_or_method_only", "malformed_candidate"} and not _candidate_supports_not_outcome_reason(candidate_by_id[candidate_id], reason_code):
            _error(report, "not_outcome_diagnostic_mismatch", "not_outcome reason must agree with candidate diagnostics", candidate_id=candidate_id)
            invalid_candidates.add(candidate_id)
        for outcome_id in linked_outcome_ids:
            if outcome_id not in outcomes_by_id:
                _error(report, "unknown_linked_outcome_id", "linked outcome does not exist in the compact response", candidate_id=candidate_id, outcome_id=outcome_id)
                report["rejected_links"].append(
                    {
                        "candidate_id": candidate_id,
                        "outcome_id": outcome_id,
                        "reason": "unknown_outcome_id",
                    }
                )
                invalid_candidates.add(candidate_id)
                continue
            if disposition in {"extracted", "duplicate"}:
                if candidate_outcome_matches(candidate_by_id[candidate_id], outcomes_by_id[outcome_id]):
                    valid_structural_links[candidate_id].add(outcome_id)
                else:
                    report["rejected_links"].append({"candidate_id": candidate_id, "outcome_id": outcome_id, "reason": "structural_match_failed"})
                    invalid_candidates.add(candidate_id)

    linked_by_outcome: dict[str, set[str]] = {}
    for candidate_id in sorted(accounted_ids - invalid_candidates):
        entry = accounting[candidate_id]
        if entry.get("disposition") not in {"extracted", "duplicate"}:
            continue
        for outcome_id in valid_structural_links[candidate_id]:
            linked_by_outcome.setdefault(outcome_id, set()).add(candidate_id)

    for candidate_id in sorted(accounted_ids - malformed_entries):
        entry = accounting[candidate_id]
        if not isinstance(entry, Mapping):
            continue
        disposition = entry.get("disposition")
        linked_outcome_ids = entry.get("linked_outcome_ids", [])
        all_links_valid = bool(linked_outcome_ids) and set(linked_outcome_ids) <= valid_structural_links[candidate_id]
        if disposition == "extracted" and all_links_valid and candidate_id not in invalid_candidates:
            report["valid_extracted"] += 1
            report["structurally_confirmed_candidate_ids"].append(candidate_id)
        if disposition == "duplicate" and all_links_valid and candidate_id not in invalid_candidates:
            if any(len(linked_by_outcome.get(outcome_id, set()) - {candidate_id}) for outcome_id in linked_outcome_ids):
                report["valid_duplicates"] += 1
                report["structurally_confirmed_candidate_ids"].append(candidate_id)
            else:
                _error(report, "duplicate_link_not_shared", "duplicate must share a linked outcome with another candidate", candidate_id=candidate_id)
    report["structurally_confirmed_candidates"] = len(report["structurally_confirmed_candidate_ids"])
    return compact_response, report
