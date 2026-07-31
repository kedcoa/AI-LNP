"""Precision-first, packet-only experimental-arm proposals for NP-002."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from .compact_contracts import CompactExtractionResponse


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
_CANONICAL_CROSS_PRODUCT_ARMS = {
    "KUP-01": ("MC3", "QUANT DNA", 0.3),
    "KUP-02": ("cKK-E12", "QUANT DNA", 0.3),
    "KUP-03": ("MC3", "Cre mRNA", 1.0),
    "KUP-04": ("cKK-E12", "Cre mRNA", 1.0),
    "KUP-05": ("MC3", "Cre mRNA", 0.3),
    "KUP-06": ("cKK-E12", "Cre mRNA", 0.3),
}
_ACCOUNTING_ENTRY_FIELDS = {
    "disposition",
    "linked_experiment_ids",
    "linked_outcome_ids",
    "evidence_ids",
    "reason_code",
    "explanation",
}
_AMBIGUOUS_REASON_CODES = (
    "conflicting_evidence",
    "candidate_not_grounded",
)
_CANONICAL_KUPFFER_ARM_IDS = tuple(f"KUP-{index:02d}" for index in range(1, 7))


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _packet_evidence(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    if packet.get("paper_id") != "NP-002":
        raise ValueError("Kupffer arm proposal accepts only NP-002")
    raw_evidence = packet.get("evidence")
    if not isinstance(raw_evidence, list):
        raise ValueError("NP-002 packet evidence must be a list")
    evidence: list[dict[str, Any]] = []
    for raw in raw_evidence:
        if not isinstance(raw, Mapping):
            raise ValueError("each packet evidence record must be an object")
        evidence_id = raw.get("evidence_id")
        text = raw.get("text")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("each packet evidence record requires an evidence_id")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("each packet evidence record requires text")
        row = {"evidence_id": evidence_id, "text": text}
        source_ids = raw.get("source_ids", [])
        if isinstance(source_ids, list) and all(
            isinstance(source_id, str) and source_id
            for source_id in source_ids
        ):
            row["source_ids"] = source_ids
        experiment_candidate_ids = raw.get("experiment_candidate_ids", [])
        if isinstance(experiment_candidate_ids, list) and all(
            isinstance(candidate_id, str) and candidate_id
            for candidate_id in experiment_candidate_ids
        ):
            row["experiment_candidate_ids"] = experiment_candidate_ids
        for field in (
            "context_before_evidence_id",
            "context_after_evidence_id",
        ):
            context_id = raw.get(field)
            if isinstance(context_id, str) and context_id:
                row[field] = context_id
        evidence.append(row)
    evidence_ids = [row["evidence_id"] for row in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("packet evidence IDs must be unique")
    return evidence


def _matching(
    evidence: list[dict[str, Any]],
    predicate: Any,
) -> list[dict[str, Any]]:
    return [
        row
        for row in evidence
        if predicate(row["text"].casefold())
    ]


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(row["evidence_id"] for row in rows))


def _shares_experiment_context(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    if left["evidence_id"] == right["evidence_id"]:
        return True
    for field in ("source_ids", "experiment_candidate_ids"):
        if set(left.get(field, [])) & set(right.get(field, [])):
            return True
    return right["evidence_id"] in {
        left.get("context_before_evidence_id"),
        left.get("context_after_evidence_id"),
    } or left["evidence_id"] in {
        right.get("context_before_evidence_id"),
        right.get("context_after_evidence_id"),
    }


def _contextually_connected(
    anchors: Sequence[Mapping[str, Any]],
    support: Sequence[Mapping[str, Any]],
) -> bool:
    return any(
        _shares_experiment_context(anchor, row)
        for anchor in anchors
        for row in support
    )


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
    if (
        route_rows
        and quant_bound
        and _contextually_connected(quant_bound, quant_outcomes or quant_bound)
    ):
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
    if (
        route_rows
        and cre_model
        and cre_target
        and cre_one_bound
        and _contextually_connected(cre_one_bound, cre_target)
    ):
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
        and _contextually_connected(cre_low_bound, cre_target)
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
    packet_evidence_context: Mapping[str, Mapping[str, Any]],
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
        treatment = (
            arm["formulation"],
            arm["payload"],
            float(dose),
        )
        canonical_treatment = _CANONICAL_CROSS_PRODUCT_ARMS.get(
            arm["candidate_id"]
        )
        if (
            arm["confidence"] == "human_confirmed"
            and arm["pairing_type"] == "cross_product"
            and canonical_treatment != treatment
        ):
            raise ValueError(
                "complementary-clause binding is restricted to canonical "
                "NP-002 cross-product arms"
            )

        def has_experimental_action(text: str) -> bool:
            normalized = text.casefold()
            return any(
                term in normalized
                for term in (
                    "inject",
                    "administer",
                    "treat",
                    "deliver",
                    "repeat",
                    "analyz",
                    "measur",
                    "observ",
                    "isolate",
                )
            )

        def has_formulation_experiment_context(text: str) -> bool:
            normalized = text.casefold()
            return (
                "mc3" in normalized
                and "ckk-e12" in normalized
                and has_experimental_action(text)
            )

        def has_payload_dose_experiment_context(text: str) -> bool:
            normalized = text.casefold()
            return (
                arm["payload"].casefold() in normalized
                and dose_token in normalized
                and "mg/kg" in normalized
                and has_experimental_action(text)
            )

        def has_shared_or_neighboring_context(
            formulation_evidence_id: str,
            condition_evidence_id: str,
        ) -> bool:
            formulation_context = packet_evidence_context[
                formulation_evidence_id
            ]
            condition_context = packet_evidence_context[
                condition_evidence_id
            ]
            formulation_sources = set(formulation_context.get("source_ids", []))
            condition_sources = set(condition_context.get("source_ids", []))
            formulation_experiments = set(
                formulation_context.get("experiment_candidate_ids", [])
            )
            condition_experiments = set(
                condition_context.get("experiment_candidate_ids", [])
            )
            return (
                bool(formulation_sources & condition_sources)
                or bool(formulation_experiments & condition_experiments)
                or condition_evidence_id
                in {
                    formulation_context.get("context_before_evidence_id"),
                    formulation_context.get("context_after_evidence_id"),
                }
                or formulation_evidence_id
                in {
                    condition_context.get("context_before_evidence_id"),
                    condition_context.get("context_after_evidence_id"),
                }
            )

        formulation_evidence_ids = [
            evidence_id
            for evidence_id in evidence_lists["existence_evidence_ids"]
            if has_formulation_experiment_context(
                packet_evidence[evidence_id]
            )
        ]
        condition_evidence_ids = [
            evidence_id
            for evidence_id in evidence_lists["existence_evidence_ids"]
            if has_payload_dose_experiment_context(packet_evidence[evidence_id])
        ]
        complementary_binding = (
            arm["confidence"] == "human_confirmed"
            and arm["pairing_type"] == "cross_product"
            and canonical_treatment == treatment
            and any(
                has_shared_or_neighboring_context(
                    formulation_evidence_id,
                    condition_evidence_id,
                )
                for formulation_evidence_id in formulation_evidence_ids
                for condition_evidence_id in condition_evidence_ids
            )
        )
        if not complementary_binding:
            raise ValueError(
                "arm evidence lacks a shared or neighboring formulation-payload-dose relationship"
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
        and (
            "source_ids" not in row
            or (
                isinstance(row["source_ids"], list)
                and all(
                    isinstance(source_id, str) and source_id
                    for source_id in row["source_ids"]
                )
            )
        )
        and (
            "experiment_candidate_ids" not in row
            or (
                isinstance(row["experiment_candidate_ids"], list)
                and all(
                    isinstance(candidate_id, str) and candidate_id
                    for candidate_id in row["experiment_candidate_ids"]
                )
            )
        )
        and all(
            field not in row
            or (
                isinstance(row[field], str)
                and row[field]
            )
            for field in (
                "context_before_evidence_id",
                "context_after_evidence_id",
            )
        )
        for row in packet_evidence_raw
    ):
        raise ValueError("proposal packet_evidence contains invalid context metadata")
    packet_evidence = {
        str(row["evidence_id"]): str(row["text"])
        for row in packet_evidence_raw
    }
    if list(packet_evidence) != packet_evidence_ids_raw:
        raise ValueError(
            "proposal packet evidence text does not match its evidence ID envelope"
        )
    packet_evidence_context = {
        str(row["evidence_id"]): {
            "source_ids": row.get("source_ids", []),
            "experiment_candidate_ids": row.get(
                "experiment_candidate_ids", []
            ),
            "context_before_evidence_id": row.get(
                "context_before_evidence_id"
            ),
            "context_after_evidence_id": row.get(
                "context_after_evidence_id"
            ),
        }
        for row in packet_evidence_raw
    }
    for context in packet_evidence_context.values():
        for field in (
            "context_before_evidence_id",
            "context_after_evidence_id",
        ):
            context_id = context[field]
            if context_id is not None and context_id not in packet_evidence:
                raise ValueError(
                    "proposal packet evidence context points outside its envelope"
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
                packet_evidence_context=packet_evidence_context,
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
            packet_evidence_context=packet_evidence_context,
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
    if {arm["candidate_id"] for arm in approved_arms} == set(
        _CANONICAL_KUPFFER_ARM_IDS
    ):
        order = {
            candidate_id: index
            for index, candidate_id in enumerate(_CANONICAL_KUPFFER_ARM_IDS)
        }
        approved_arms.sort(key=lambda arm: order[arm["candidate_id"]])
        _approved_arm_rows(approved_arms)
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


def _approved_arm_rows(
    approved_arms: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Copy approved arms and return their IDs in request order."""

    rows: list[dict[str, Any]] = []
    candidate_ids: list[str] = []
    for arm in approved_arms:
        if not isinstance(arm, Mapping):
            raise ValueError("approved arms must be objects")
        candidate_id = arm.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("approved arms require nonempty candidate_id values")
        rows.append(deepcopy(dict(arm)))
        candidate_ids.append(candidate_id)
    if tuple(candidate_ids) != _CANONICAL_KUPFFER_ARM_IDS:
        raise ValueError(
            "approved arms must be the canonical ordered KUP-01 through KUP-06 set"
        )
    for arm in rows:
        expected = _CANONICAL_CROSS_PRODUCT_ARMS[arm["candidate_id"]]
        actual = (
            arm.get("formulation"),
            arm.get("payload"),
            float(arm["dose"])
            if isinstance(arm.get("dose"), (int, float))
            and not isinstance(arm.get("dose"), bool)
            else arm.get("dose"),
        )
        if actual != expected:
            raise ValueError(
                "approved canonical candidate identity does not match its "
                "KUP arm mapping"
            )
    return rows, candidate_ids


def _entry_variant(
    *,
    disposition: str,
    experiment_constraints: dict[str, Any],
    outcome_constraints: dict[str, Any],
    reason_schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "disposition": {"const": disposition},
            "linked_experiment_ids": {
                "type": "array",
                "items": {"type": "string"},
                **experiment_constraints,
            },
            "linked_outcome_ids": {
                "type": "array",
                "items": {"type": "string"},
                **outcome_constraints,
            },
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "reason_code": reason_schema,
            "explanation": {"type": "string", "minLength": 1},
        },
        "required": [
            "disposition",
            "linked_experiment_ids",
            "linked_outcome_ids",
            "evidence_ids",
            "reason_code",
            "explanation",
        ],
        "additionalProperties": False,
    }


def build_experimental_arm_schema(
    core_schema: Mapping[str, Any],
    approved_arms: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Add exhaustive, closed approved-arm accounting to a compact schema."""

    _, candidate_ids = _approved_arm_rows(approved_arms)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("approved arm candidate IDs must be unique")
    schema = deepcopy(dict(core_schema))
    properties = dict(schema.get("properties", {}))
    definitions = dict(schema.get("$defs", {}))
    definitions["ExperimentalArmAccountingEntry"] = {
        "type": "object",
        "properties": {
            "disposition": {"enum": ["extracted", "ambiguous"]},
            "linked_experiment_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "linked_outcome_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "reason_code": {
                "enum": ["extracted", *_AMBIGUOUS_REASON_CODES],
            },
            "explanation": {"type": "string", "minLength": 1},
        },
        "required": [
            "disposition",
            "linked_experiment_ids",
            "linked_outcome_ids",
            "evidence_ids",
            "reason_code",
            "explanation",
        ],
        "additionalProperties": False,
        "anyOf": [
            _entry_variant(
                disposition="extracted",
                experiment_constraints={"minItems": 1},
                outcome_constraints={"minItems": 1},
                reason_schema={"const": "extracted"},
            ),
            _entry_variant(
                disposition="ambiguous",
                experiment_constraints={"maxItems": 0},
                outcome_constraints={"maxItems": 0},
                reason_schema={"enum": list(_AMBIGUOUS_REASON_CODES)},
            ),
        ]
    }
    properties["experimental_arm_accounting"] = {
        "type": "object",
        "properties": {
            candidate_id: {"$ref": "#/$defs/ExperimentalArmAccountingEntry"}
            for candidate_id in candidate_ids
        },
        "required": candidate_ids,
        "additionalProperties": False,
    }
    required = list(schema.get("required", []))
    if "experimental_arm_accounting" not in required:
        required.append("experimental_arm_accounting")
    schema["properties"] = properties
    schema["required"] = required
    schema["additionalProperties"] = False
    schema["$defs"] = definitions
    return schema


def _field_value(record: Mapping[str, Any], field_name: str) -> Any:
    field = record.get(field_name)
    if isinstance(field, Mapping):
        return field.get("value")
    return None


def _canonical_arm_value(value: Any, *, field_name: str) -> str:
    text = " ".join(str(value).casefold().replace("-", " ").split())
    aliases = {
        "mice": "mouse",
        "mus musculus": "mouse",
        "iv": "intravenous",
        "intravenous lateral tail vein": "intravenous",
        "ckk e12 lnp": "ckk e12",
    }
    if field_name in {"species", "model"}:
        return aliases.get(text, text)
    if field_name == "route":
        return aliases.get(text, text)
    if field_name == "formulation":
        return aliases.get(text, text)
    return text


def _same_arm_value(actual: Any, expected: Any, *, field_name: str) -> bool:
    return _canonical_arm_value(actual, field_name=field_name) == _canonical_arm_value(
        expected, field_name=field_name
    )


def _append_error(
    report: dict[str, Any], code: str, message: str, **details: Any
) -> None:
    report["errors"].append({"code": code, "message": message, **details})


def _string_id_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        return None
    if len(value) != len(set(value)):
        return None
    return value


def _arm_identity(arm: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _canonical_arm_value(arm.get("formulation"), field_name="formulation"),
        _canonical_arm_value(arm.get("payload"), field_name="payload"),
        arm.get("dose"),
        _canonical_arm_value(arm.get("target_cell"), field_name="target_cell"),
    )


def _reported_evidence_groups(
    record: Mapping[str, Any], field_names: Sequence[str]
) -> list[set[str]]:
    groups: list[set[str]] = []
    for field_name in field_names:
        field = record.get(field_name)
        if not isinstance(field, Mapping):
            continue
        evidence_ids = field.get("evidence_ids")
        if isinstance(evidence_ids, list) and evidence_ids:
            groups.append(set(evidence_ids))
    return groups


def _scientific_evidence_groups(
    *,
    linked_experiments: Sequence[Mapping[str, Any]],
    linked_outcomes: Sequence[Mapping[str, Any]],
    formulation_records: Mapping[str, Mapping[str, Any]],
) -> list[set[str]]:
    groups: list[set[str]] = []
    for experiment in linked_experiments:
        formulation = formulation_records.get(experiment.get("formulation_id"))
        if formulation is not None:
            groups.extend(
                _reported_evidence_groups(formulation, ("formulation_name",))
            )
        groups.extend(
            _reported_evidence_groups(
                experiment,
                (
                    "payload_type",
                    "payload_name",
                    "dose",
                    "dose_unit",
                    "route",
                    "species",
                    "disease_model",
                    "delivery_recipient_cell",
                    "timepoint",
                    "timepoint_unit",
                ),
            )
        )
    for outcome in linked_outcomes:
        groups.extend(
            _reported_evidence_groups(
                outcome,
                ("assay", "endpoint", "qualitative_outcome"),
            )
        )
    return groups


def _matches_scientific_arm(
    *,
    arm: Mapping[str, Any],
    experiment: Mapping[str, Any],
    formulation_names: Mapping[str, Any],
    outcomes: Sequence[Mapping[str, Any]],
) -> set[str]:
    """Return the science checks that fail for one linked arm/record group."""

    errors: set[str] = set()
    formulation = formulation_names.get(experiment.get("formulation_id"))
    checks = {
        "formulation": formulation,
        "payload": _field_value(experiment, "payload_name"),
        "dose_unit": _field_value(experiment, "dose_unit"),
        "route": _field_value(experiment, "route"),
        "species": _field_value(experiment, "species"),
        "model": _field_value(experiment, "disease_model"),
        "target_cell": _field_value(experiment, "delivery_recipient_cell"),
    }
    for field_name, actual in checks.items():
        if not _same_arm_value(actual, arm.get(field_name), field_name=field_name):
            errors.add("scientific_identity_mismatch")
    expected_payload_type = (
        "DNA" if arm.get("payload") == "QUANT DNA" else "mRNA"
    )
    if not _same_arm_value(
        _field_value(experiment, "payload_type"),
        expected_payload_type,
        field_name="payload_type",
    ):
        errors.add("scientific_identity_mismatch")
    actual_dose = _field_value(experiment, "dose")
    if (
        isinstance(actual_dose, bool)
        or not isinstance(actual_dose, (int, float))
        or float(actual_dose) != float(arm.get("dose"))
    ):
        errors.add("scientific_identity_mismatch")

    payload = _canonical_arm_value(arm.get("payload"), field_name="payload")
    timepoint = _field_value(experiment, "timepoint")
    timepoint_unit = _canonical_arm_value(
        _field_value(experiment, "timepoint_unit"), field_name="timepoint_unit"
    )
    if payload == "quant dna":
        if timepoint != 6 and not (isinstance(timepoint, float) and timepoint == 6.0) or timepoint_unit not in {"hour", "hours", "h"}:
            errors.add("quant_timepoint_required")
        if not any(
            "ddpcr"
            in str(_field_value(outcome, "assay") or "").casefold().replace("-", "")
            for outcome in outcomes
        ):
            errors.add("quant_ddpcr_required")
    elif payload == "cre mrna":
        if timepoint != 3 and not (isinstance(timepoint, float) and timepoint == 3.0) or timepoint_unit not in {"day", "days", "d"}:
            errors.add("cre_timepoint_required")
        if not any(
            "flow cytometry" in str(_field_value(outcome, "assay") or "").casefold()
            and "tdtomato"
            in " ".join(
                str(_field_value(outcome, field_name) or "").casefold()
                for field_name in ("endpoint", "qualitative_outcome")
            )
            for outcome in outcomes
        ):
            errors.add("cre_tdtomato_flow_required")
    return errors


def validate_experimental_arm_response(
    response: Mapping[str, Any],
    approved_arms: Sequence[Mapping[str, Any]],
    evidence_envelope: set[str],
) -> dict[str, Any]:
    """Validate exhaustive approved-arm accounting against returned records."""

    if not isinstance(response, Mapping):
        raise ValueError("experimental arm response must be an object")
    arms, candidate_ids = _approved_arm_rows(approved_arms)
    arm_by_id = {arm["candidate_id"]: arm for arm in arms}
    expected_ids = set(candidate_ids)
    report: dict[str, Any] = {
        "sent": len(candidate_ids),
        "accounted": 0,
        "structurally_valid_extracted": 0,
        "scientifically_confirmed": 0,
        "ambiguous": 0,
        "confirmed_candidate_ids": [],
        "errors": [],
    }
    duplicate_ids = sorted(
        candidate_id
        for candidate_id in set(candidate_ids)
        if candidate_ids.count(candidate_id) > 1
    )
    if duplicate_ids:
        _append_error(
            report,
            "repeated_candidate_ids",
            "approved arm candidate IDs must be unique",
            candidate_ids=duplicate_ids,
        )

    body = dict(response)
    accounting = body.pop("experimental_arm_accounting", None)
    compact_response = CompactExtractionResponse.model_validate(body)
    core_evidence_valid = True
    try:
        compact_response.validate_evidence_ids(set(evidence_envelope))
    except ValueError as exc:
        core_evidence_valid = False
        _append_error(
            report,
            "core_evidence_outside_envelope",
            str(exc),
        )
    if not isinstance(accounting, Mapping):
        _append_error(
            report,
            "experimental_arm_accounting_not_object",
            "experimental_arm_accounting must be an object",
        )
        return report

    returned_ids = set(accounting)
    missing_ids = sorted(expected_ids - returned_ids)
    invented_ids = sorted(returned_ids - expected_ids)
    if missing_ids:
        _append_error(
            report,
            "missing_candidate_ids",
            "experimental_arm_accounting omitted approved candidate IDs",
            candidate_ids=missing_ids,
        )
    if invented_ids:
        _append_error(
            report,
            "invented_candidate_ids",
            "experimental_arm_accounting included unknown candidate IDs",
            candidate_ids=invented_ids,
        )
    accounted_ids = expected_ids & returned_ids
    report["accounted"] = len(accounted_ids)

    formulation_records = {
        row.formulation_id: row.model_dump(mode="json")
        for row in compact_response.formulations
    }
    formulations = {
        formulation_id: _field_value(record, "formulation_name")
        for formulation_id, record in formulation_records.items()
    }
    experiments = {
        row.experiment_id: row.model_dump(mode="json")
        for row in compact_response.experiments
    }
    outcome_rows = [row.model_dump(mode="json") for row in compact_response.outcomes]
    outcome_ids = [str(row["outcome_id"]) for row in outcome_rows]
    duplicate_outcomes = sorted(
        outcome_id for outcome_id in set(outcome_ids) if outcome_ids.count(outcome_id) > 1
    )
    if duplicate_outcomes:
        _append_error(
            report,
            "duplicate_returned_outcome_ids",
            "returned outcome IDs must be unique",
            outcome_ids=duplicate_outcomes,
        )
    outcomes = {row["outcome_id"]: row for row in outcome_rows}

    structurally_valid: set[str] = set()
    candidate_outcomes: dict[str, set[str]] = {}
    for candidate_id in candidate_ids:
        if candidate_id not in accounted_ids:
            continue
        entry = accounting[candidate_id]
        if not isinstance(entry, Mapping):
            _append_error(
                report,
                "invalid_accounting_entry",
                "each experimental arm accounting entry must be an object",
                candidate_id=candidate_id,
            )
            continue
        unexpected_fields = sorted(set(entry) - _ACCOUNTING_ENTRY_FIELDS)
        missing_fields = sorted(_ACCOUNTING_ENTRY_FIELDS - set(entry))
        if unexpected_fields or missing_fields:
            _append_error(
                report,
                "invalid_accounting_entry",
                "accounting entries require exactly the closed entry fields",
                candidate_id=candidate_id,
                unexpected_fields=unexpected_fields,
                missing_fields=missing_fields,
            )
            continue
        disposition = entry["disposition"]
        linked_experiment_ids = _string_id_list(entry["linked_experiment_ids"])
        linked_outcome_ids = _string_id_list(entry["linked_outcome_ids"])
        evidence_ids = _string_id_list(entry["evidence_ids"])
        reason_code = entry["reason_code"]
        explanation = entry["explanation"]
        if disposition not in {"extracted", "ambiguous"}:
            _append_error(
                report,
                "invalid_disposition",
                "accounting disposition must be extracted or ambiguous",
                candidate_id=candidate_id,
            )
            continue
        if (
            linked_experiment_ids is None
            or linked_outcome_ids is None
            or evidence_ids is None
            or not isinstance(reason_code, str)
            or not isinstance(explanation, str)
            or not explanation.strip()
        ):
            _append_error(
                report,
                "invalid_accounting_entry",
                "accounting entry values must be complete and unique string lists",
                candidate_id=candidate_id,
            )
            continue
        if not evidence_ids:
            _append_error(
                report,
                "accounting_evidence_required",
                "accounting entries require at least one evidence ID",
                candidate_id=candidate_id,
            )
            continue
        if set(evidence_ids) - set(evidence_envelope):
            _append_error(
                report,
                "evidence_outside_envelope",
                "accounting entry cites evidence outside the permitted envelope",
                candidate_id=candidate_id,
            )
            continue
        if disposition == "ambiguous":
            if linked_experiment_ids or linked_outcome_ids or reason_code not in _AMBIGUOUS_REASON_CODES:
                _append_error(
                    report,
                    "invalid_ambiguous_entry",
                    "ambiguous entries require empty record links and a non-extracted reason",
                    candidate_id=candidate_id,
                )
                continue
            report["ambiguous"] += 1
            continue
        if reason_code != "extracted" or not linked_experiment_ids or not linked_outcome_ids:
            _append_error(
                report,
                "extracted_requires_record_links",
                "extracted entries require linked experiments, outcomes, and extracted reason",
                candidate_id=candidate_id,
            )
            continue
        unknown_experiments = sorted(set(linked_experiment_ids) - set(experiments))
        unknown_outcomes = sorted(set(linked_outcome_ids) - set(outcomes))
        if unknown_experiments or unknown_outcomes:
            _append_error(
                report,
                "unknown_linked_record_ids",
                "extracted entry links must reference returned records",
                candidate_id=candidate_id,
                experiment_ids=unknown_experiments,
                outcome_ids=unknown_outcomes,
            )
            continue
        if any(
            outcomes[outcome_id]["experiment_id"] not in linked_experiment_ids
            for outcome_id in linked_outcome_ids
        ):
            _append_error(
                report,
                "outcome_experiment_link_mismatch",
                "linked outcomes must belong to a linked experiment",
                candidate_id=candidate_id,
            )
            continue
        structurally_valid.add(candidate_id)
        candidate_outcomes[candidate_id] = set(linked_outcome_ids)

    reused_candidates: set[str] = set()
    for outcome_id in sorted(set().union(*candidate_outcomes.values()) if candidate_outcomes else set()):
        users = [
            candidate_id
            for candidate_id, outcome_ids_for_candidate in candidate_outcomes.items()
            if outcome_id in outcome_ids_for_candidate
        ]
        if len({_arm_identity(arm_by_id[candidate_id]) for candidate_id in users}) > 1:
            reused_candidates.update(users)
            _append_error(
                report,
                "outcome_reused_across_incompatible_arms",
                "one returned outcome cannot confirm incompatible approved arms",
                outcome_id=outcome_id,
                candidate_ids=sorted(users),
            )

    invalid_structural = set(reused_candidates)
    if duplicate_outcomes:
        for candidate_id, linked_outcome_ids in candidate_outcomes.items():
            if set(duplicate_outcomes) & linked_outcome_ids:
                invalid_structural.add(candidate_id)
    if not core_evidence_valid:
        invalid_structural.update(structurally_valid)

    for candidate_id in candidate_ids:
        if (
            not core_evidence_valid
            or candidate_id not in structurally_valid
            or candidate_id in reused_candidates
        ):
            continue
        entry = accounting[candidate_id]
        linked_experiments = [experiments[item] for item in entry["linked_experiment_ids"]]
        linked_outcomes = [outcomes[item] for item in entry["linked_outcome_ids"]]
        accounting_evidence_ids = set(entry["evidence_ids"])
        if any(
            not accounting_evidence_ids & evidence_ids
            for evidence_ids in _scientific_evidence_groups(
                linked_experiments=linked_experiments,
                linked_outcomes=linked_outcomes,
                formulation_records=formulation_records,
            )
        ):
            _append_error(
                report,
                "accounting_evidence_does_not_cover_scientific_fields",
                "accounting evidence must cover every linked scientific field used for confirmation",
                candidate_id=candidate_id,
            )
            invalid_structural.add(candidate_id)
            continue
        science_errors: set[str] = set()
        for experiment in linked_experiments:
            experiment_outcomes = [
                outcome
                for outcome in linked_outcomes
                if outcome["experiment_id"] == experiment["experiment_id"]
            ]
            science_errors |= _matches_scientific_arm(
                arm=arm_by_id[candidate_id],
                experiment=experiment,
                formulation_names=formulations,
                outcomes=experiment_outcomes,
            )
        if science_errors:
            for code in sorted(science_errors):
                _append_error(
                    report,
                    code,
                    "linked records do not satisfy the approved arm's scientific constraints",
                    candidate_id=candidate_id,
                )
            invalid_structural.add(candidate_id)
            continue
        report["confirmed_candidate_ids"].append(candidate_id)
    report["structurally_valid_extracted"] = len(
        structurally_valid - invalid_structural
    )
    report["scientifically_confirmed"] = len(report["confirmed_candidate_ids"])
    return report
