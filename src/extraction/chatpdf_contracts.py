"""Strict extraction contract for auditable ChatPDF candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


ARM_FIELDS = {
    "arm_id", "lnp_name", "chemical_formulation_total", "lnp_molar_ratio",
    "ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid", "others",
    "species", "biological_model", "target_or_recipient_organ",
    "intended_target_cell", "observed_transfected_cell", "payload",
    "encoded_product", "molecular_target", "dose", "route", "timepoint",
    "assay", "outcomes", "evidence",
}
OUTCOME_FIELDS = {
    "outcome_id", "endpoint", "quantitative_value", "unit",
    "normalization_basis", "qualitative_outcome", "evidence",
}


@dataclass(frozen=True)
class ChatPdfPaperExtraction:
    paper_id: str
    arms: tuple[dict[str, Any], ...]
    raw: dict[str, Any]


def _validate_evidence(evidence: Any, label: str) -> None:
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"{label} requires evidence")
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError(f"{label} evidence must be objects")
        page = item.get("page")
        quote = item.get("quote")
        if not isinstance(page, int) or page < 1 or not isinstance(quote, str) or not quote.strip():
            raise ValueError(f"{label} evidence requires page and quote")


def parse_extraction_response(content: str) -> ChatPdfPaperExtraction:
    if not content.lstrip().startswith("{") or not content.rstrip().endswith("}"):
        raise ValueError("ChatPDF response must contain a JSON object only")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("ChatPDF response must contain a JSON object only") from error
    if not isinstance(payload, dict) or set(payload) != {"paper_id", "arms"}:
        raise ValueError("response must contain exactly paper_id and arms")
    if not isinstance(payload["paper_id"], str) or not isinstance(payload["arms"], list):
        raise ValueError("paper_id and arms have invalid types")
    for arm in payload["arms"]:
        if not isinstance(arm, dict) or set(arm) - ARM_FIELDS:
            raise ValueError("arm contains unknown fields")
        if not isinstance(arm.get("arm_id"), str) or not arm["arm_id"].strip():
            raise ValueError("arm_id is required")
        evidence_map = arm.get("evidence")
        if not isinstance(evidence_map, dict):
            raise ValueError(f"{arm['arm_id']}.evidence must be an object")
        for field_name, value in arm.items():
            if field_name in {"arm_id", "evidence", "outcomes"} or value is None:
                continue
            _validate_evidence(evidence_map.get(field_name), f"{arm['arm_id']}.{field_name}")
        outcomes = arm.get("outcomes")
        if not isinstance(outcomes, list):
            raise ValueError(f"{arm['arm_id']}.outcomes must be a list")
        for outcome in outcomes:
            if not isinstance(outcome, dict) or set(outcome) - OUTCOME_FIELDS:
                raise ValueError("outcome contains unknown fields")
            if not isinstance(outcome.get("outcome_id"), str):
                raise ValueError("outcome_id is required")
            evidence = outcome.get("evidence")
            if not isinstance(evidence, dict):
                raise ValueError("outcome evidence must be an object")
            for field_name, value in outcome.items():
                if field_name in {"outcome_id", "evidence"} or value is None:
                    continue
                _validate_evidence(
                    evidence.get(field_name),
                    f"{arm['arm_id']}.{outcome['outcome_id']}.{field_name}",
                )
    return ChatPdfPaperExtraction(
        paper_id=payload["paper_id"],
        arms=tuple(payload["arms"]),
        raw=payload,
    )


__all__ = ["ChatPdfPaperExtraction", "parse_extraction_response"]
