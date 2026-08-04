"""Deterministically validate and copy-merge gold-blind shadow-audit proposals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import re
from typing import Any


_PROPOSAL_FIELDS = {
    "proposal_id",
    "proposal_type",
    "experiment_id",
    "candidate_id",
    "field_name",
    "raw_values",
    "evidence_ids",
    "quoted_support",
}
_PROPOSAL_TYPES = {"add_fact", "replace_fact", "flag_record"}
_NUMBER = re.compile(r"(?<![A-Za-z0-9])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
    )


def _proposal_issues(proposal: Mapping[str, Any]) -> list[str]:
    if set(proposal) != _PROPOSAL_FIELDS:
        return ["malformed_proposal"]
    if not isinstance(proposal.get("proposal_id"), str) or not proposal["proposal_id"]:
        return ["malformed_proposal"]
    if proposal.get("proposal_type") not in _PROPOSAL_TYPES:
        return ["malformed_proposal"]
    for name in ("experiment_id", "candidate_id"):
        if proposal.get(name) is not None and not isinstance(proposal.get(name), str):
            return ["malformed_proposal"]
    if not isinstance(proposal.get("field_name"), str) or not proposal["field_name"]:
        return ["malformed_proposal"]
    if not _string_list(proposal.get("raw_values")):
        return ["malformed_proposal"]
    if not _string_list(proposal.get("evidence_ids")):
        return ["malformed_proposal"]
    if not isinstance(proposal.get("quoted_support"), str) or not proposal["quoted_support"]:
        return ["malformed_proposal"]
    return []


def _issued_strings(packet: Mapping[str, Any], name: str) -> set[str]:
    issued = packet.get("issued_ids")
    if not isinstance(issued, Mapping):
        return set()
    value = issued.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        return set()
    return set(value)


def _evidence_by_id(packet: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    evidence = packet.get("evidence")
    if not isinstance(evidence, list):
        return {}
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in evidence:
        if not isinstance(row, Mapping):
            return {}
        evidence_id = row.get("evidence_id")
        excerpt = row.get("excerpt")
        if not isinstance(evidence_id, str) or not evidence_id or not isinstance(excerpt, str):
            return {}
        if evidence_id in by_id:
            return {}
        by_id[evidence_id] = row
    return by_id


def _experiment_candidate_pairs(value: Any) -> dict[str, str | None]:
    pairs: dict[str, str | None] = {}
    if isinstance(value, Mapping):
        experiment_id = value.get("experiment_id")
        candidate_id = value.get("candidate_id")
        if isinstance(experiment_id, str):
            pairs[experiment_id] = candidate_id if isinstance(candidate_id, str) else None
        for child in value.values():
            pairs.update(_experiment_candidate_pairs(child))
    elif isinstance(value, list):
        for child in value:
            pairs.update(_experiment_candidate_pairs(child))
    return pairs


def _declared_evidence_experiments(row: Mapping[str, Any]) -> set[str]:
    declared: set[str] = set()
    experiment_id = row.get("experiment_id")
    if isinstance(experiment_id, str) and experiment_id:
        declared.add(experiment_id)
    experiment_ids = row.get("experiment_ids")
    if isinstance(experiment_ids, list):
        declared.update(
            item for item in experiment_ids if isinstance(item, str) and item
        )
    return declared


def _unique_reasons(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reasons))


def validate_proposal(proposal: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any]:
    """Return an acceptance decision without reading reference or gold artifacts.

    The packet is the complete authority for identifiers and textual support.  A
    rejected proposal is retained verbatim for auditability but cannot affect a
    merge.
    """

    if not isinstance(proposal, Mapping) or not isinstance(packet, Mapping):
        return {
            "accepted": False,
            "proposal": deepcopy(dict(proposal)) if isinstance(proposal, Mapping) else {},
            "rejection_reasons": ["malformed_proposal"],
        }
    proposed = deepcopy(dict(proposal))
    reasons = _proposal_issues(proposal)
    if "record_id" in proposal:
        reasons.append("unknown_record_id")
    if reasons:
        return {
            "accepted": False,
            "proposal": proposed,
            "rejection_reasons": _unique_reasons(reasons),
        }

    evidence_ids = _issued_strings(packet, "evidence_ids")
    experiment_ids = _issued_strings(packet, "experiment_ids")
    candidate_ids = _issued_strings(packet, "candidate_ids")
    evidence_by_id = _evidence_by_id(packet)
    if not evidence_ids or not evidence_by_id:
        reasons.append("malformed_packet")
    unknown_evidence = [item for item in proposal["evidence_ids"] if item not in evidence_ids]
    if unknown_evidence or any(item not in evidence_by_id for item in proposal["evidence_ids"]):
        reasons.append("unknown_evidence_id")

    experiment_id = proposal["experiment_id"]
    candidate_id = proposal["candidate_id"]
    if experiment_id is not None and experiment_id not in experiment_ids:
        reasons.append("unknown_experiment_id")
    if candidate_id is not None and candidate_id not in candidate_ids:
        reasons.append("unknown_candidate_id")
    if candidate_id is not None and experiment_id is None:
        reasons.append("wrong_arm_link")

    pairs = _experiment_candidate_pairs(packet.get("current_merged_facts"))
    if experiment_id is not None and experiment_id in pairs:
        expected_candidate = pairs[experiment_id]
        if expected_candidate != candidate_id:
            reasons.append("wrong_arm_link")

    if experiment_id is not None:
        for evidence_id in proposal["evidence_ids"]:
            row = evidence_by_id.get(evidence_id)
            if row is None:
                continue
            declared_experiments = _declared_evidence_experiments(row)
            if declared_experiments and experiment_id not in declared_experiments:
                reasons.append("cross_experiment_evidence")

    quote = proposal["quoted_support"]
    cited_excerpts = [
        evidence_by_id[evidence_id]["excerpt"]
        for evidence_id in proposal["evidence_ids"]
        if evidence_id in evidence_by_id
    ]
    if cited_excerpts and not any(quote in excerpt for excerpt in cited_excerpts):
        reasons.append("quote_mismatch")
    for raw_value in proposal["raw_values"]:
        for number in _NUMBER.findall(raw_value):
            if number not in quote:
                reasons.append("unsupported_exact_number")

    reasons = _unique_reasons(reasons)
    return {
        "accepted": not reasons,
        "proposal": proposed,
        "rejection_reasons": reasons,
    }


def _proposal_provenance(proposal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "proposal_id": proposal["proposal_id"],
        "evidence_ids": list(proposal["evidence_ids"]),
        "quoted_support": proposal["quoted_support"],
    }


def _fact_from_proposal(proposal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "field_name": proposal["field_name"],
        "canonical_value": proposal["raw_values"][0],
        "raw_values": list(proposal["raw_values"]),
        "evidence_ids": list(proposal["evidence_ids"]),
        "audit_provenance": _proposal_provenance(proposal),
    }


def _target_facts(audited: dict[str, Any], proposal: Mapping[str, Any]) -> list[dict[str, Any]]:
    experiment_id = proposal["experiment_id"]
    if experiment_id is None:
        facts = audited.setdefault("shared_facts", [])
        if not isinstance(facts, list):
            raise ValueError("baseline shared_facts must be a list")
        return facts
    experiments = audited.get("experiments")
    if not isinstance(experiments, list):
        raise ValueError("baseline experiments must be a list")
    for experiment in experiments:
        if not isinstance(experiment, dict) or experiment.get("experiment_id") != experiment_id:
            continue
        if experiment.get("candidate_id") != proposal["candidate_id"]:
            raise ValueError("accepted validation has an arm absent from the baseline")
        facts = experiment.setdefault("facts", [])
        if not isinstance(facts, list):
            raise ValueError("baseline experiment facts must be a list")
        return facts
    raise ValueError("accepted validation has an experiment absent from the baseline")


def _apply_fact_proposal(audited: dict[str, Any], proposal: Mapping[str, Any]) -> None:
    facts = _target_facts(audited, proposal)
    if proposal["proposal_type"] == "add_fact":
        facts.append(_fact_from_proposal(proposal))
        return
    if proposal["proposal_type"] == "replace_fact":
        for index, fact in enumerate(facts):
            if isinstance(fact, Mapping) and fact.get("field_name") == proposal["field_name"]:
                facts[index] = _fact_from_proposal(proposal)
                return
        raise ValueError("accepted replacement targets no baseline fact")
    findings = audited.setdefault("validation_findings", [])
    if not isinstance(findings, list):
        raise ValueError("baseline validation_findings must be a list")
    findings.append(
        {
            "finding_id": proposal["proposal_id"],
            "code": "shadow_audit_flag",
            "field_name": proposal["field_name"],
            "raw_values": list(proposal["raw_values"]),
            "evidence_ids": list(proposal["evidence_ids"]),
            "audit_provenance": _proposal_provenance(proposal),
        }
    )


def merge_validated_proposals(
    baseline: Mapping[str, Any], validations: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Copy ``baseline`` and apply only well-formed accepted proposals.

    This intentionally has no filesystem or benchmark-reference parameters: all
    merge authority comes from prior packet-local validation.
    """

    if not isinstance(baseline, Mapping):
        raise ValueError("baseline must be a mapping")
    audited = deepcopy(dict(baseline))
    for validation in validations:
        if not isinstance(validation, Mapping) or validation.get("accepted") is not True:
            continue
        proposal = validation.get("proposal")
        if not isinstance(proposal, Mapping) or _proposal_issues(proposal):
            raise ValueError("accepted validation contains a malformed proposal")
        _apply_fact_proposal(audited, proposal)
    return audited
