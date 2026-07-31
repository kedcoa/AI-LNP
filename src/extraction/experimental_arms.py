"""Precision-first, packet-only experimental-arm proposals for NP-002."""

from __future__ import annotations

import hashlib
import json
import re
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
_PAIRED_PATTERN = re.compile(
    r"(?P<formulation_1>MC3|cKK-E12)\s+carrying\s+"
    r"(?P<payload_1>QUANT DNA|Cre mRNA)\s+and\s+"
    r"(?P<formulation_2>MC3|cKK-E12)\s+carrying\s+"
    r"(?P<payload_2>QUANT DNA|Cre mRNA)\s+at\s+"
    r"(?P<dose_1>\d+(?:\.\d+)?)\s+and\s+"
    r"(?P<dose_2>\d+(?:\.\d+)?)\s*mg/kg,\s*respectively",
    flags=re.IGNORECASE,
)
_PERMITTED_TREATMENTS = {
    ("MC3", "QUANT DNA", 0.3),
    ("cKK-E12", "QUANT DNA", 0.3),
    ("MC3", "Cre mRNA", 0.3),
    ("cKK-E12", "Cre mRNA", 0.3),
    ("MC3", "Cre mRNA", 1.0),
    ("cKK-E12", "Cre mRNA", 1.0),
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


def _parse_paired_treatments(
    text: str,
) -> list[tuple[str, str, float]] | None:
    match = _PAIRED_PATTERN.search(text)
    if match is None:
        return None
    formulations = {"mc3": "MC3", "ckk-e12": "cKK-E12"}
    payloads = {"quant dna": "QUANT DNA", "cre mrna": "Cre mRNA"}
    pairs = [
        (
            formulations[match.group(f"formulation_{index}").casefold()],
            payloads[match.group(f"payload_{index}").casefold()],
            float(match.group(f"dose_{index}")),
        )
        for index in (1, 2)
    ]
    if (
        len({pair[0] for pair in pairs}) != 2
        or len({pair[1] for pair in pairs}) != 2
        or any(pair not in _PERMITTED_TREATMENTS for pair in pairs)
    ):
        return None
    return pairs


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    respectively_rows = _matching(
        evidence,
        lambda text: (
            "respectively" in text
            and "kupffer" in text
            and "mice" in text
            and "intraven" in text
            and any(
                verb in text
                for verb in ("inject", "administer", "treat", "deliver")
            )
        ),
    )
    if not respectively_rows:
        return [], []
    non_relationship_outcomes = _matching(
        evidence,
        lambda text: (
            "respectively" not in text
            and "kupffer" in text
            and any(
                term in text
                for term in ("measur", "outcome", "delivery", "accumulation")
            )
        ),
    )
    proposed_by_id: dict[str, dict[str, Any]] = {}
    quarantined: list[dict[str, Any]] = []
    for row in respectively_rows:
        pairs = _parse_paired_treatments(row["text"])
        if pairs is None:
            quarantined.append(
                {
                    "family": "paired_correspondence",
                    "reason": "relationship_not_explicit",
                    "evidence_ids": [row["evidence_id"]],
                }
            )
            continue
        outcome_rows = [row, *non_relationship_outcomes]
        for index, (formulation, payload, dose) in enumerate(
            pairs, start=1
        ):
            arm = _arm(
                candidate_id=f"KUP-{index:02d}",
                formulation=formulation,
                payload=payload,
                dose=dose,
                model="mice",
                pairing_type="paired_correspondence",
                existence_rows=[row],
                outcome_rows=outcome_rows,
            )
            candidate_id = arm["candidate_id"]
            if candidate_id in proposed_by_id:
                quarantined.append(
                    {
                        "family": "paired_correspondence",
                        "candidate_id": candidate_id,
                        "reason": "candidate_id_conflict",
                        "evidence_ids": list(
                            dict.fromkeys(
                                arm["existence_evidence_ids"]
                                + arm["outcome_evidence_ids"]
                            )
                        ),
                    }
                )
                continue
            proposed_by_id[candidate_id] = arm
    return (
        [
            proposed_by_id[candidate_id]
            for candidate_id in sorted(proposed_by_id)
        ],
        quarantined,
    )


def _np002_six_arm_inventory(
    evidence: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    route_rows = _matching(
        evidence,
        lambda text: (
            "mice" in text
            and "intraven" in text
            and any(term in text for term in ("inject", "administer"))
        ),
    )
    if not route_rows:
        route_rows = []

    proposed: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    quant_family_rows = _matching(
        evidence,
        lambda text: (
            "quant dna" in text
            or (
                "mc3" in text
                and "ckk-e12" in text
                and "kupffer" in text
                and any(term in text for term in ("biodistrib", "distribut"))
            )
        ),
    )
    quant_bound = _matching(
        evidence,
        lambda text: (
            "mice" in text
            and "0.3" in text
            and "mg/kg" in text
            and "quant dna" in text
            and "kupffer" in text
            and "mc3" in text
            and "ckk-e12" in text
            and any(
                term in text
                for term in ("inject", "administer", "treat", "deliver")
            )
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
    if route_rows and quant_bound:
        if not quant_outcomes:
            quant_outcomes = quant_bound
        quant_existence = [
            *quant_bound,
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
    elif quant_family_rows:
        quarantined.append(
            {
                "family": "QUANT DNA 0.3 mg/kg",
                "reason": "relationship_not_explicit",
                "evidence_ids": _ids(quant_family_rows),
            }
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
    cre_one_family_rows = _matching(
        evidence,
        lambda text: (
            ("cre mrna" in text and "1.0" in text)
            or (
                "mc3" in text
                and "ckk-e12" in text
                and "1.0" in text
                and "tdtomato" in text
            )
        ),
    )
    cre_one_bound = _matching(
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
    if route_rows and cre_model and cre_target and cre_one_bound:
        cre_one_existence = [
            *cre_one_bound,
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
    elif cre_one_family_rows:
        quarantined.append(
            {
                "family": "Cre mRNA 1.0 mg/kg",
                "reason": "relationship_not_explicit",
                "evidence_ids": _ids(cre_one_family_rows),
            }
        )

    cre_low_family_rows = _matching(
        evidence,
        lambda text: (
            ("cre mrna" in text and "0.3" in text)
            or (
                "mc3" in text
                and "ckk-e12" in text
                and "0.3" in text
                and "tdtomato" in text
            )
        ),
    )
    cre_low_bound = _matching(
        evidence,
        lambda text: (
            "cre mrna" in text
            and "0.3" in text
            and "mg/kg" in text
            and "mc3" in text
            and "ckk-e12" in text
            and "tdtomato" in text
            and any(term in text for term in ("observ", "measur", "delivery"))
        ),
    )
    if (
        route_rows
        and cre_model
        and cre_target
        and cre_low_bound
    ):
        cre_low_existence = [
            *cre_low_bound,
            *cre_model,
            *cre_target,
            *route_rows,
        ]
        cre_low_outcomes = [*cre_low_bound, *cre_target]
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
    elif cre_low_family_rows:
        quarantined.append(
            {
                "family": "Cre mRNA 0.3 mg/kg",
                "reason": "relationship_not_explicit",
                "evidence_ids": _ids(cre_low_family_rows),
            }
        )
    return proposed, quarantined


def build_np002_kupffer_arm_proposal(
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Propose only arms supported by explicit NP-002 experiment clauses."""

    evidence = _packet_evidence(packet)
    paired_arms, paired_quarantine = _paired_correspondence(evidence)
    inventory_evidence = [
        row
        for row in evidence
        if "respectively" not in row["text"].casefold()
    ]
    inventory_arms, inventory_quarantine = _np002_six_arm_inventory(
        inventory_evidence
    )
    proposed_by_id = {
        arm["candidate_id"]: arm for arm in inventory_arms
    }
    conflict_quarantine: list[dict[str, Any]] = []
    for arm in paired_arms:
        candidate_id = arm["candidate_id"]
        if candidate_id in proposed_by_id:
            conflict_quarantine.append(
                {
                    "family": "paired_correspondence",
                    "candidate_id": candidate_id,
                    "reason": "candidate_id_conflict",
                    "evidence_ids": list(
                        dict.fromkeys(
                            arm["existence_evidence_ids"]
                            + arm["outcome_evidence_ids"]
                        )
                    ),
                }
            )
            continue
        proposed_by_id[candidate_id] = arm
    proposed_arms = [
        proposed_by_id[candidate_id]
        for candidate_id in sorted(proposed_by_id)
    ]
    quarantined_arms = [
        *paired_quarantine,
        *inventory_quarantine,
        *conflict_quarantine,
    ]
    unsigned = {
        "proposal_version": ARM_PROPOSAL_VERSION,
        "paper_id": "NP-002",
        "target_cell": "Kupffer cells",
        "packet_evidence_ids": [row["evidence_id"] for row in evidence],
        "packet_evidence": evidence,
        "proposed_arms": proposed_arms,
        "quarantined_arms": quarantined_arms,
    }
    return {**unsigned, "proposal_sha256": _sha256(unsigned)}


def _validate_complete_arm(
    arm: Any,
    *,
    packet_evidence: Mapping[str, str],
) -> dict[str, Any]:
    if not isinstance(arm, Mapping) or set(arm) != _ARM_FIELDS:
        raise ValueError("corrections and additions require a complete arm")
    candidate_id = arm.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("complete arm requires a candidate_id")
    for field in (
        "formulation",
        "payload",
        "dose_unit",
        "route",
        "species",
        "model",
        "target_cell",
        "confidence",
    ):
        if not isinstance(arm.get(field), str) or not arm[field].strip():
            raise ValueError(f"complete arm requires a nonempty {field}")
    if arm["target_cell"] != "Kupffer cells":
        raise ValueError("corrected and added arms must target Kupffer cells")
    if arm["formulation"] not in {"MC3", "cKK-E12"}:
        raise ValueError("arm formulation is outside the NP-002 Kupffer scope")
    if arm["payload"] not in {"QUANT DNA", "Cre mRNA"}:
        raise ValueError("arm payload is outside the NP-002 Kupffer scope")
    if arm["dose_unit"] != "mg/kg":
        raise ValueError("arm dose_unit is outside the NP-002 Kupffer scope")
    if arm["route"] != "intravenous lateral tail vein":
        raise ValueError("arm route is outside the NP-002 Kupffer scope")
    if arm["species"] != "Mus musculus":
        raise ValueError("arm species is outside the NP-002 Kupffer scope")
    if arm["model"] not in {"mice", "Ai14 Cre-reporter mice"}:
        raise ValueError("arm model is outside the NP-002 Kupffer scope")
    if arm["payload"] == "QUANT DNA" and arm["model"] != "mice":
        raise ValueError("QUANT DNA arms require the packet-supported mice model")
    if (
        arm["payload"] == "Cre mRNA"
        and arm["pairing_type"] != "paired_correspondence"
        and arm["model"] != "Ai14 Cre-reporter mice"
    ):
        raise ValueError(
            "Cre mRNA inventory arms require the packet-supported Ai14 model"
        )
    dose = arm.get("dose")
    if isinstance(dose, bool) or not isinstance(dose, (int, float)):
        raise ValueError("arm dose must be numeric")
    if (arm["formulation"], arm["payload"], float(dose)) not in (
        _PERMITTED_TREATMENTS
    ):
        raise ValueError("arm treatment is outside the NP-002 Kupffer scope")
    if arm.get("pairing_type") not in PAIRING_TYPES:
        raise ValueError("complete arm has an invalid pairing_type")
    evidence_lists: dict[str, list[str]] = {}
    for field in ("existence_evidence_ids", "outcome_evidence_ids"):
        evidence_ids = arm.get(field)
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or not all(isinstance(item, str) for item in evidence_ids)
        ):
            raise ValueError("complete arm requires nonempty evidence ID lists")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("complete arm evidence IDs must be unique")
        if not set(evidence_ids) <= set(packet_evidence):
            raise ValueError("corrected or added arm cites evidence outside packet evidence")
        evidence_lists[field] = evidence_ids

    existence_texts = [
        packet_evidence[evidence_id]
        for evidence_id in evidence_lists["existence_evidence_ids"]
    ]
    dose_token = "1.0" if float(dose) == 1.0 else "0.3"

    def binds_treatment(text: str) -> bool:
        normalized = text.casefold()
        treatment = (
            arm["formulation"],
            arm["payload"],
            float(dose),
        )
        if arm["pairing_type"] == "paired_correspondence":
            paired = _parse_paired_treatments(text)
            return paired is not None and treatment in paired
        required = (
            arm["formulation"].casefold(),
            arm["payload"].casefold(),
            dose_token,
            "mg/kg",
        )
        if not all(token in normalized for token in required):
            return False
        if not any(
            term in normalized
            for term in ("inject", "administer", "treat", "deliver", "repeat")
        ):
            return False
        if arm["pairing_type"] == "cross_product":
            return "mc3" in normalized and "ckk-e12" in normalized
        return True

    if not any(binds_treatment(text) for text in existence_texts):
        raise ValueError(
            "arm evidence lacks one explicit formulation-payload-dose binding relationship"
        )

    def supports_route(text: str) -> bool:
        normalized = text.casefold()
        return (
            "mice" in normalized
            and "intraven" in normalized
            and any(term in normalized for term in ("inject", "administer"))
        )

    if not any(supports_route(text) for text in existence_texts):
        raise ValueError("arm evidence lacks its intravenous mice route")

    def supports_model(text: str) -> bool:
        normalized = text.casefold()
        if arm["model"] == "Ai14 Cre-reporter mice":
            return (
                "ai14" in normalized
                and "mice" in normalized
                and any(
                    term in normalized
                    for term in ("experiment", "utiliz", "used")
                )
            )
        return (
            "mice" in normalized
            and any(
                term in normalized
                for term in ("inject", "administer", "experiment", "treat")
            )
        )

    if not any(supports_model(text) for text in existence_texts):
        raise ValueError("arm evidence does not support its selected model")

    def supports_target(text: str) -> bool:
        normalized = text.casefold()
        return "kupffer" in normalized and any(
            term in normalized
            for term in (
                "measur",
                "quantif",
                "observ",
                "biodistrib",
                "isolate",
                "deliver",
            )
        )

    if not any(supports_target(text) for text in existence_texts):
        raise ValueError(
            "arm evidence lacks direct experimental Kupffer-cell support"
        )

    outcome_texts = [
        packet_evidence[evidence_id]
        for evidence_id in evidence_lists["outcome_evidence_ids"]
    ]
    if not any(
        "kupffer" in text.casefold()
        and any(
            term in text.casefold()
            for term in (
                "measur",
                "quantif",
                "observ",
                "outcome",
                "deliver",
                "distribut",
                "accumulat",
                "tdtomato",
            )
        )
        for text in outcome_texts
    ):
        raise ValueError(
            "arm outcome evidence does not directly support a Kupffer outcome"
        )
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
    packet_evidence_raw = proposal.get("packet_evidence")
    if not isinstance(packet_evidence_ids_raw, list):
        raise ValueError("proposal packet_evidence_ids must be a list")
    if not isinstance(packet_evidence_raw, list) or not all(
        isinstance(row, Mapping)
        and isinstance(row.get("evidence_id"), str)
        and isinstance(row.get("text"), str)
        for row in packet_evidence_raw
    ):
        raise ValueError("proposal packet_evidence must contain evidence text")
    packet_evidence = {
        str(row["evidence_id"]): str(row["text"])
        for row in packet_evidence_raw
    }
    if list(packet_evidence) != packet_evidence_ids_raw:
        raise ValueError(
            "proposal packet evidence text does not match its evidence ID envelope"
        )
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
                packet_evidence=packet_evidence,
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
            packet_evidence=packet_evidence,
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
