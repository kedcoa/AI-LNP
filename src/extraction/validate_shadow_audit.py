"""Deterministically validate and copy-merge gold-blind shadow-audit proposals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import re
from typing import Any


_REQUIRED_PROPOSAL_FIELDS = {
    "proposal_id",
    "proposal_type",
    "experiment_id",
    "candidate_id",
    "field_name",
    "raw_values",
    "evidence_ids",
    "quoted_support",
}
_OPTIONAL_PROPOSAL_FIELDS = {"record_id", "fact_id", "entity_ids", "arm_id"}
_PROPOSAL_TYPES = {"add_fact", "replace_fact", "flag_record"}
_DIMENSIONLESS_NUMERIC_FIELDS = {
    "animal_count",
    "count",
    "p_value",
    "replicate_count",
    "sample_size",
}
_MEASUREMENT = re.compile(
    r"(?<![A-Za-z0-9])(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?![A-Za-z0-9])(?:\s*(?P<unit>[A-Za-zµμ%][A-Za-zµμ%0-9/^.-]*))?"
)


def _string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
    )


def _proposal_issues(proposal: Mapping[str, Any]) -> list[str]:
    if not _REQUIRED_PROPOSAL_FIELDS <= set(proposal) or not set(proposal) <= (
        _REQUIRED_PROPOSAL_FIELDS | _OPTIONAL_PROPOSAL_FIELDS
    ):
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
    for name in ("record_id", "fact_id", "arm_id"):
        if proposal.get(name) is not None and (
            not isinstance(proposal[name], str) or not proposal[name]
        ):
            return ["malformed_proposal"]
    if proposal.get("entity_ids") is not None and not _string_list(
        proposal["entity_ids"]
    ):
        return ["malformed_proposal"]
    if proposal["proposal_type"] == "replace_fact" and (
        not isinstance(proposal.get("record_id"), str)
        or not isinstance(proposal.get("fact_id"), str)
    ):
        return ["missing_replacement_target"]
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


def _measurements(value: str) -> list[tuple[str, str | None]]:
    """Extract boundary-aware number/unit pairs, preserving exact numeric text."""

    return [
        (match.group("number"), match.group("unit").rstrip(".") if match.group("unit") else None)
        for match in _MEASUREMENT.finditer(value)
    ]


def _numeric_values_supported(
    raw_values: Sequence[str], quote: str, field_name: str
) -> bool:
    quote_measurements = _measurements(quote)
    for raw_value in raw_values:
        for number, unit in _measurements(raw_value):
            if unit is None:
                if field_name not in _DIMENSIONLESS_NUMERIC_FIELDS:
                    return False
                if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(number)}(?![A-Za-z0-9_-])", quote) is None:
                    return False
                continue
            if not any(
                number == quoted_number
                and unit == quoted_unit
                for quoted_number, quoted_unit in quote_measurements
            ):
                return False
    return True


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
    for field_name, issued_name, reason in (
        ("record_id", "record_ids", "unknown_record_id"),
        ("fact_id", "fact_ids", "unknown_fact_id"),
        ("arm_id", "arm_ids", "unknown_arm_id"),
    ):
        if isinstance(proposal.get(field_name), str) and proposal[
            field_name
        ] not in _issued_strings(packet, issued_name):
            reasons.append(reason)
    if isinstance(proposal.get("entity_ids"), list):
        issued_entities = _issued_strings(packet, "entity_ids")
        if any(entity_id not in issued_entities for entity_id in proposal["entity_ids"]):
            reasons.append("unknown_entity_id")
    if candidate_id is not None and experiment_id is None:
        reasons.append("wrong_arm_link")

    arm_id = proposal.get("arm_id")
    if isinstance(arm_id, str):
        issued = packet.get("issued_ids")
        arm_links = issued.get("arm_links") if isinstance(issued, Mapping) else None
        arm_link = arm_links.get(arm_id) if isinstance(arm_links, Mapping) else None
        if not isinstance(arm_link, Mapping) or not all(
            isinstance(arm_link.get(name), str)
            for name in ("experiment_id", "candidate_id")
        ):
            reasons.append("invalid_arm_link")
        elif (
            arm_link["experiment_id"] != experiment_id
            or arm_link["candidate_id"] != candidate_id
        ):
            reasons.append("wrong_arm_link")

    pairs = _experiment_candidate_pairs(packet.get("current_merged_facts"))
    if experiment_id is not None and experiment_id in pairs:
        expected_candidate = pairs[experiment_id]
        if expected_candidate != candidate_id:
            reasons.append("wrong_arm_link")

    quote = proposal["quoted_support"]
    supporters: list[str] = []
    has_quote_match = False
    for evidence_id in proposal["evidence_ids"]:
        row = evidence_by_id.get(evidence_id)
        if row is None:
            continue
        excerpt = row["excerpt"]
        if quote in excerpt:
            has_quote_match = True
            if _numeric_values_supported(
                proposal["raw_values"], quote, proposal["field_name"]
            ):
                supporters.append(evidence_id)
    if not has_quote_match:
        reasons.append("quote_mismatch")
    elif not supporters:
        reasons.append("unsupported_exact_number")
    else:
        proposed["evidence_ids"] = supporters

    if experiment_id is not None:
        single_experiment_scope = (
            packet.get("packet_type") == "experiment" and len(experiment_ids) == 1
        )
        for evidence_id in supporters:
            row = evidence_by_id.get(evidence_id)
            if row is None:
                continue
            declared_experiments = _declared_evidence_experiments(row)
            if declared_experiments and declared_experiments != {experiment_id}:
                reasons.append("cross_experiment_evidence")
            elif not declared_experiments and not single_experiment_scope:
                reasons.append("cross_experiment_evidence")

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
        **(
            {"record_id": proposal["record_id"]}
            if isinstance(proposal.get("record_id"), str)
            else {}
        ),
        **(
            {"fact_id": proposal["fact_id"]}
            if isinstance(proposal.get("fact_id"), str)
            else {}
        ),
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
        targets = [
            index
            for index, fact in enumerate(facts)
            if isinstance(fact, Mapping)
            and fact.get("fact_id") == proposal["fact_id"]
            and fact.get("record_id") == proposal["record_id"]
        ]
        if len(targets) != 1:
            raise ValueError("accepted replacement must target one unique baseline fact")
        facts[targets[0]] = _fact_from_proposal(proposal)
        return
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
