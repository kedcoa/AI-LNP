"""Precision-first, packet-only experimental-arm proposals for NP-002."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


ARM_PROPOSAL_VERSION = "np002-kupffer-arm-proposal-1.0.0"
ARM_REVIEW_VERSION = "np002-kupffer-arm-review-1.0.0"
PAIRING_TYPES = {
    "single_statement",
    "cross_product",
    "paired_correspondence",
}

_ARM_FIELDS = {
    "candidate_id",
    "formulation",
    "payload",
    "dose",
    "dose_unit",
    "route",
    "species",
    "model",
    "target_cell",
    "pairing_type",
    "existence_evidence_ids",
    "outcome_evidence_ids",
    "confidence",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _packet_evidence(packet: Mapping[str, Any]) -> list[dict[str, str]]:
    if packet.get("paper_id") != "NP-002":
        raise ValueError("Kupffer arm proposal accepts only NP-002")
    raw_evidence = packet.get("evidence")
    if not isinstance(raw_evidence, list):
        raise ValueError("NP-002 packet evidence must be a list")
    evidence: list[dict[str, str]] = []
    for raw in raw_evidence:
        if not isinstance(raw, Mapping):
            raise ValueError("each packet evidence record must be an object")
        evidence_id = raw.get("evidence_id")
        text = raw.get("text")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("each packet evidence record requires an evidence_id")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("each packet evidence record requires text")
        evidence.append({"evidence_id": evidence_id, "text": text})
    evidence_ids = [row["evidence_id"] for row in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("packet evidence IDs must be unique")
    return evidence


def _matching(
    evidence: list[dict[str, str]],
    predicate: Any,
) -> list[dict[str, str]]:
    return [
        row
        for row in evidence
        if predicate(row["text"].casefold())
    ]


def _ids(rows: list[dict[str, str]]) -> list[str]:
    return list(dict.fromkeys(row["evidence_id"] for row in rows))


def _arm(
    *,
    candidate_id: str,
    formulation: str,
    payload: str,
    dose: float,
    model: str,
    pairing_type: str,
    existence_rows: list[dict[str, str]],
    outcome_rows: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "formulation": formulation,
        "payload": payload,
        "dose": dose,
        "dose_unit": "mg/kg",
        "route": "intravenous lateral tail vein",
        "species": "Mus musculus",
        "model": model,
        "target_cell": "Kupffer cells",
        "pairing_type": pairing_type,
        "existence_evidence_ids": _ids(existence_rows),
        "outcome_evidence_ids": _ids(outcome_rows),
        "confidence": "high",
    }


def _paired_correspondence(
    evidence: list[dict[str, str]],
) -> list[dict[str, Any]]:
    rows = _matching(
        evidence,
        lambda text: (
            "respectively" in text
            and "mc3" in text
            and "ckk-e12" in text
            and "quant dna" in text
            and "cre mrna" in text
            and "0.3" in text
            and "1.0" in text
            and "kupffer" in text
            and "mice" in text
            and "intraven" in text
            and any(
                verb in text
                for verb in ("inject", "administer", "treat", "deliver")
            )
        ),
    )
    if not rows:
        return []
    outcome_rows = _matching(
        evidence,
        lambda text: (
            "kupffer" in text
            and any(
                term in text
                for term in ("measur", "outcome", "delivery", "accumulation")
            )
        ),
    )
    if not outcome_rows:
        outcome_rows = rows
    return [
        _arm(
            candidate_id="KUP-01",
            formulation="MC3",
            payload="QUANT DNA",
            dose=0.3,
            model="mice",
            pairing_type="paired_correspondence",
            existence_rows=rows,
            outcome_rows=outcome_rows,
        ),
        _arm(
            candidate_id="KUP-02",
            formulation="cKK-E12",
            payload="Cre mRNA",
            dose=1.0,
            model="mice",
            pairing_type="paired_correspondence",
            existence_rows=rows,
            outcome_rows=outcome_rows,
        ),
    ]


def _np002_six_arm_inventory(
    evidence: list[dict[str, str]],
) -> list[dict[str, Any]]:
    route_rows = _matching(
        evidence,
        lambda text: (
            "mice" in text
            and "intraven" in text
            and any(term in text for term in ("inject", "administer"))
        ),
    )
    if not route_rows:
        return []

    proposed: list[dict[str, Any]] = []
    quant_relationship = _matching(
        evidence,
        lambda text: (
            "mc3" in text
            and "ckk-e12" in text
            and "kupffer" in text
            and any(term in text for term in ("biodistribution", "analy"))
        ),
    )
    quant_condition = _matching(
        evidence,
        lambda text: (
            "mice" in text
            and "0.3" in text
            and "mg/kg" in text
            and "quant dna" in text
            and "kupffer" in text
            and any(term in text for term in ("inject", "administer"))
        ),
    )
    quant_outcomes = _matching(
        evidence,
        lambda text: (
            "kupffer" in text
            and "mc3" in text
            and "ckk-e12" in text
            and any(
                term in text
                for term in ("distribut", "accumulat", "measur", "observ")
            )
        ),
    )
    if quant_relationship and quant_condition:
        if not quant_outcomes:
            quant_outcomes = [*quant_relationship, *quant_condition]
        quant_existence = [
            *quant_relationship,
            *quant_condition,
            *route_rows,
        ]
        proposed.extend(
            [
                _arm(
                    candidate_id="KUP-01",
                    formulation="MC3",
                    payload="QUANT DNA",
                    dose=0.3,
                    model="mice",
                    pairing_type="cross_product",
                    existence_rows=quant_existence,
                    outcome_rows=quant_outcomes,
                ),
                _arm(
                    candidate_id="KUP-02",
                    formulation="cKK-E12",
                    payload="QUANT DNA",
                    dose=0.3,
                    model="mice",
                    pairing_type="cross_product",
                    existence_rows=quant_existence,
                    outcome_rows=quant_outcomes,
                ),
            ]
        )

    cre_model = _matching(
        evidence,
        lambda text: (
            "ai14" in text
            and "mice" in text
            and any(term in text for term in ("experiment", "utiliz", "used"))
        ),
    )
    cre_target = _matching(
        evidence,
        lambda text: (
            "kupffer" in text
            and "tdtomato" in text
            and any(term in text for term in ("quantif", "percent", "observ"))
        ),
    )
    cre_one_condition = _matching(
        evidence,
        lambda text: (
            "cre mrna" in text
            and "1.0" in text
            and "mg/kg" in text
            and "mc3" in text
            and "ckk-e12" in text
            and any(term in text for term in ("administer", "inject", "treat"))
        ),
    )
    if cre_model and cre_target and cre_one_condition:
        cre_one_existence = [
            *cre_one_condition,
            *cre_model,
            *cre_target,
            *route_rows,
        ]
        proposed.extend(
            [
                _arm(
                    candidate_id="KUP-03",
                    formulation="MC3",
                    payload="Cre mRNA",
                    dose=1.0,
                    model="Ai14 Cre-reporter mice",
                    pairing_type="cross_product",
                    existence_rows=cre_one_existence,
                    outcome_rows=cre_target,
                ),
                _arm(
                    candidate_id="KUP-04",
                    formulation="cKK-E12",
                    payload="Cre mRNA",
                    dose=1.0,
                    model="Ai14 Cre-reporter mice",
                    pairing_type="cross_product",
                    existence_rows=cre_one_existence,
                    outcome_rows=cre_target,
                ),
            ]
        )

    cre_low_condition = _matching(
        evidence,
        lambda text: (
            "cre mrna" in text
            and "0.3" in text
            and "mg/kg" in text
            and any(term in text for term in ("repeat", "administer", "inject"))
        ),
    )
    cre_low_relationship = _matching(
        evidence,
        lambda text: (
            "0.3" in text
            and "mg/kg" in text
            and "mc3" in text
            and "ckk-e12" in text
            and "tdtomato" in text
            and any(term in text for term in ("observ", "measur", "delivery"))
        ),
    )
    if (
        cre_model
        and cre_target
        and cre_low_condition
        and cre_low_relationship
    ):
        cre_low_existence = [
            *cre_low_condition,
            *cre_low_relationship,
            *cre_model,
            *cre_target,
            *route_rows,
        ]
        cre_low_outcomes = [*cre_low_relationship, *cre_target]
        proposed.extend(
            [
                _arm(
                    candidate_id="KUP-05",
                    formulation="MC3",
                    payload="Cre mRNA",
                    dose=0.3,
                    model="Ai14 Cre-reporter mice",
                    pairing_type="cross_product",
                    existence_rows=cre_low_existence,
                    outcome_rows=cre_low_outcomes,
                ),
                _arm(
                    candidate_id="KUP-06",
                    formulation="cKK-E12",
                    payload="Cre mRNA",
                    dose=0.3,
                    model="Ai14 Cre-reporter mice",
                    pairing_type="cross_product",
                    existence_rows=cre_low_existence,
                    outcome_rows=cre_low_outcomes,
                ),
            ]
        )
    return proposed


def build_np002_kupffer_arm_proposal(
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Propose only arms supported by explicit NP-002 experiment clauses."""

    evidence = _packet_evidence(packet)
    proposed_arms = _paired_correspondence(evidence)
    if not proposed_arms:
        proposed_arms = _np002_six_arm_inventory(evidence)
    quarantined_arms: list[dict[str, Any]] = []
    if not proposed_arms and any(
        term in row["text"].casefold()
        for row in evidence
        for term in ("mc3", "ckk-e12", "quant dna", "cre mrna")
    ):
        quarantined_arms.append(
            {
                "reason": "relationship_not_explicit",
                "evidence_ids": [row["evidence_id"] for row in evidence],
            }
        )
    unsigned = {
        "proposal_version": ARM_PROPOSAL_VERSION,
        "paper_id": "NP-002",
        "target_cell": "Kupffer cells",
        "packet_evidence_ids": [row["evidence_id"] for row in evidence],
        "proposed_arms": proposed_arms,
        "quarantined_arms": quarantined_arms,
    }
    return {**unsigned, "proposal_sha256": _sha256(unsigned)}


def _validate_complete_arm(
    arm: Any,
    *,
    packet_evidence_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(arm, Mapping) or set(arm) != _ARM_FIELDS:
        raise ValueError("corrections and additions require a complete arm")
    candidate_id = arm.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("complete arm requires a candidate_id")
    if arm.get("pairing_type") not in PAIRING_TYPES:
        raise ValueError("complete arm has an invalid pairing_type")
    for field in ("existence_evidence_ids", "outcome_evidence_ids"):
        evidence_ids = arm.get(field)
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or not all(isinstance(item, str) for item in evidence_ids)
        ):
            raise ValueError("complete arm requires nonempty evidence ID lists")
        if not set(evidence_ids) <= packet_evidence_ids:
            raise ValueError("corrected or added arm cites evidence outside packet evidence")
    return deepcopy(dict(arm))


def validate_arm_review(
    proposal: Mapping[str, Any],
    review: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a SHA-bound, exhaustive human decision over proposed arms."""

    if not isinstance(proposal, Mapping):
        raise ValueError("proposal must be an object")
    supplied_proposal_sha = proposal.get("proposal_sha256")
    unsigned_proposal = {
        key: value
        for key, value in proposal.items()
        if key != "proposal_sha256"
    }
    if (
        not isinstance(supplied_proposal_sha, str)
        or _sha256(unsigned_proposal) != supplied_proposal_sha
    ):
        raise ValueError("proposal was modified after its proposal SHA-256 was calculated")
    if not isinstance(review, Mapping):
        raise ValueError("review must be an object")
    if review.get("review_version") != ARM_REVIEW_VERSION:
        raise ValueError(f"review_version must be {ARM_REVIEW_VERSION}")
    if review.get("proposal_sha256") != supplied_proposal_sha:
        raise ValueError("review proposal_sha256 does not match proposal")

    proposed_arms = proposal.get("proposed_arms")
    if not isinstance(proposed_arms, list):
        raise ValueError("proposal proposed_arms must be a list")
    proposed_by_id = {
        arm.get("candidate_id"): arm
        for arm in proposed_arms
        if isinstance(arm, Mapping)
    }
    if len(proposed_by_id) != len(proposed_arms) or any(
        not isinstance(candidate_id, str) or not candidate_id
        for candidate_id in proposed_by_id
    ):
        raise ValueError("proposal candidate IDs must be nonempty and unique")
    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("review decisions must be a list")
    decision_ids = [
        decision.get("candidate_id")
        for decision in decisions
        if isinstance(decision, Mapping)
    ]
    if len(decision_ids) != len(decisions):
        raise ValueError("each review decision must be an object")
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError("review contains a duplicate candidate decision")
    if set(decision_ids) != set(proposed_by_id):
        raise ValueError("review requires exactly one known decision per proposed candidate")

    packet_evidence_ids_raw = proposal.get("packet_evidence_ids")
    if not isinstance(packet_evidence_ids_raw, list):
        raise ValueError("proposal packet_evidence_ids must be a list")
    packet_evidence_ids = set(packet_evidence_ids_raw)
    decisions_by_id = {
        str(decision["candidate_id"]): decision for decision in decisions
    }
    approved_arms: list[dict[str, Any]] = []
    accepted: list[str] = []
    corrected: list[str] = []
    removed: list[str] = []
    for candidate_id, proposed_arm in proposed_by_id.items():
        decision = decisions_by_id[candidate_id]
        action = decision.get("decision")
        reason = decision.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("every review decision requires a reason")
        if action == "accept":
            approved_arms.append(deepcopy(dict(proposed_arm)))
            accepted.append(candidate_id)
        elif action == "correct":
            corrected_arm = _validate_complete_arm(
                decision.get("arm"),
                packet_evidence_ids=packet_evidence_ids,
            )
            if corrected_arm["candidate_id"] != candidate_id:
                raise ValueError("corrected arm candidate_id must match its decision")
            approved_arms.append(corrected_arm)
            corrected.append(candidate_id)
        elif action == "remove":
            removed.append(candidate_id)
        else:
            raise ValueError("decision must be accept, correct, or remove")

    additions_raw = review.get("additions", [])
    if not isinstance(additions_raw, list):
        raise ValueError("review additions must be a list")
    additions = [
        _validate_complete_arm(
            arm,
            packet_evidence_ids=packet_evidence_ids,
        )
        for arm in additions_raw
    ]
    approved_ids = [arm["candidate_id"] for arm in approved_arms]
    addition_ids = [arm["candidate_id"] for arm in additions]
    if set(addition_ids) & set(proposed_by_id):
        raise ValueError("added arm candidate_id must not match a proposed arm")
    if len(addition_ids) != len(set(addition_ids)):
        raise ValueError("added arm candidate IDs must be unique")
    if set(addition_ids) & set(approved_ids):
        raise ValueError("added arm candidate_id duplicates an approved arm")
    approved_arms.extend(additions)
    return {
        "status": "valid",
        "review_version": ARM_REVIEW_VERSION,
        "proposal_sha256": supplied_proposal_sha,
        "approved_arms": approved_arms,
        "accepted_candidate_ids": accepted,
        "corrected_candidate_ids": corrected,
        "removed_candidate_ids": removed,
        "added_candidate_ids": addition_ids,
    }
