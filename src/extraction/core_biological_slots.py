"""Pure-local qualification and validation for the closed NP-001 core slots."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from .compact_contracts import CompactExtractionResponse


QUALIFICATION_VERSION = "np001-core-slot-qualification-1.0.0"
CORE_SLOT_CONTRACT_VERSION = "compact-core-slot-trial-1.0.0"

FORMULATION_KEYWORDS = (
    "lnp",
    "lipid nanoparticle",
    "lipid nanoparticles",
    "formulation",
    "ionizable lipid",
    "helper lipid",
    "peg-lipid",
    "peg lipid",
    "cholesterol",
)
PAYLOAD_KEYWORDS = (
    "payload",
    "active co-component",
    "mrna",
    "sirna",
    "rna",
    "dna",
    "egfp",
    "luciferase",
)
FORMULATION_COMPOSITION_TERMS = (
    "alc-0315",
    "dspc",
    "dope",
    "ionizable lipid",
    "helper lipid",
    "cholesterol",
    "dx",
    "dexamethasone",
    "alc-0159",
    "peg-lipid",
    "peg lipid",
)
FORMULATION_ALTERNATIVE_COMPONENTS = (("dspc", "dope"),)
PAYLOAD_TYPE_TERMS = ("mrna", "sirna", "rna", "dna")
PAYLOAD_CARGO_TERMS = ("egfp", "gfp", "luciferase")
IMMUNE_OUTCOME_TERMS = (
    "cytokine",
    "immune",
    "il-6",
    "il6",
    "tnf",
    "interferon",
    "ifn",
)
BIODISTRIBUTION_OUTCOME_TERMS = (
    "biodistribution",
    "organ distribution",
    "tissue distribution",
    "liver accumulation",
    "organ accumulation",
)
REPORTER_RESULT_PATTERNS = (
    r"(?:e?gfp|luciferase|reporter).{0,30}"
    r"(?:expression|positive|signal|activity)",
    r"(?:expression|positive|signal|activity).{0,30}"
    r"(?:e?gfp|luciferase|reporter)",
    r"transfection\s+(?:efficiency|rate)",
)
BACKGROUND_SIGNALS = (
    "background",
    "introduction",
    "discussion",
    "review",
)


@dataclass(frozen=True)
class CoreSlotSpec:
    slot_id: str
    model_family: str
    outcome_family: str
    model_aliases: tuple[str, ...]
    outcome_keywords: tuple[str, ...]


CORE_SLOT_SPECS = (
    CoreSlotSpec(
        slot_id="CORE-HEPG2-TRANSFECTION",
        model_family="hepg2",
        outcome_family="transfection_expression",
        model_aliases=("hepg2", "hep g2"),
        outcome_keywords=(
            "transfect",
            "expression",
            "reporter expression",
            "egfp expression",
            "gfp expression",
            "luciferase expression",
        ),
    ),
    CoreSlotSpec(
        slot_id="CORE-DC24-TRANSFECTION",
        model_family="dc2.4",
        outcome_family="transfection_expression",
        model_aliases=(
            "dc2.4",
            "dc 2.4",
            "dendritic cell",
            "dendritic cells",
        ),
        outcome_keywords=(
            "transfect",
            "expression",
            "reporter expression",
            "egfp expression",
            "gfp expression",
            "luciferase expression",
        ),
    ),
    CoreSlotSpec(
        slot_id="CORE-DC24-IMMUNE",
        model_family="dc2.4",
        outcome_family="cytokine_immune",
        model_aliases=(
            "dc2.4",
            "dc 2.4",
            "dendritic cell",
            "dendritic cells",
        ),
        outcome_keywords=(
            "cytokine",
            "immune response",
            "il-6",
            "il6",
            "tnf",
            "interferon",
        ),
    ),
    CoreSlotSpec(
        slot_id="CORE-HPBMC-TRANSFECTION",
        model_family="hpbmc",
        outcome_family="transfection_expression",
        model_aliases=(
            "hpbmc",
            "hpbmcs",
            "human pbmc",
            "human pbmcs",
            "human peripheral blood mononuclear cell",
            "human peripheral blood mononuclear cells",
        ),
        outcome_keywords=(
            "transfect",
            "expression",
            "reporter expression",
            "egfp expression",
            "gfp expression",
            "luciferase expression",
        ),
    ),
    CoreSlotSpec(
        slot_id="CORE-HPBMC-IMMUNE",
        model_family="hpbmc",
        outcome_family="cytokine_immune",
        model_aliases=(
            "hpbmc",
            "hpbmcs",
            "human pbmc",
            "human pbmcs",
            "human peripheral blood mononuclear cell",
            "human peripheral blood mononuclear cells",
        ),
        outcome_keywords=(
            "cytokine",
            "immune response",
            "il-6",
            "il6",
            "tnf",
            "interferon",
        ),
    ),
    CoreSlotSpec(
        slot_id="CORE-MOUSE-BIODISTRIBUTION",
        model_family="mouse_in_vivo",
        outcome_family="biodistribution_expression",
        model_aliases=("mouse", "mice", "murine"),
        outcome_keywords=(
            "biodistribution",
            "expression",
            "organ distribution",
            "tissue distribution",
            "liver accumulation",
            "organ accumulation",
            "in vivo expression",
        ),
    ),
)


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(value in folded for value in values)


def _contains_term(text: str, term: str) -> bool:
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
            text,
            flags=re.IGNORECASE,
        )
    )


def _matched_terms(
    text: str,
    terms: tuple[str, ...],
) -> list[str]:
    return [term for term in terms if _contains_term(text, term)]


def _has_dx_lnp_group(text: str) -> bool:
    has_dx = _contains_term(text, "dx") or _contains_term(
        text, "dexamethasone"
    )
    has_lnp = (
        _contains_term(text, "lnp")
        or _contains_term(text, "lnps")
        or _contains_term(text, "lipid nanoparticle")
        or _contains_term(text, "lipid nanoparticles")
    )
    return has_dx and has_lnp


def _payload_terms(text: str) -> list[str]:
    if _contains_any(text, BACKGROUND_SIGNALS):
        return []
    return _matched_terms(text, PAYLOAD_KEYWORDS)


def _outcome_matches_family(text: str, family: str) -> bool:
    immune = bool(_matched_terms(text, IMMUNE_OUTCOME_TERMS))
    biodistribution = bool(
        _matched_terms(text, BIODISTRIBUTION_OUTCOME_TERMS)
    )
    explicit_transfection = "transfect" in text.casefold()
    expression = _contains_term(text, "expression")
    reporter_result = any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in REPORTER_RESULT_PATTERNS
    )
    if family == "cytokine_immune":
        return immune
    if family == "transfection_expression":
        if immune:
            return reporter_result
        return explicit_transfection or (
            expression and not immune and not biodistribution
        )
    if family == "biodistribution_expression":
        return biodistribution or (expression and not immune)
    return False


def _evidence_rows(packet: Mapping[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for row in packet.get("evidence", []):
        if not isinstance(row, Mapping):
            continue
        evidence_id = row.get("evidence_id")
        text = row.get("text")
        if isinstance(evidence_id, str) and isinstance(text, str):
            rows.append((evidence_id, text))
    return rows


def _ordered_union(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for evidence_id in group:
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            ordered.append(evidence_id)
    return ordered


def build_np001_core_slots(
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate the six closed NP-001 biological slots deterministically."""

    if packet.get("paper_id") != "NP-001":
        raise ValueError(
            "The closed core biological slot builder only accepts NP-001"
        )
    rows = _evidence_rows(packet)
    formulation_evidence_ids = [
        evidence_id
        for evidence_id, text in rows
        if _contains_any(text, FORMULATION_KEYWORDS)
    ]
    payload_evidence_ids = [
        evidence_id
        for evidence_id, text in rows
        if _payload_terms(text)
    ]

    evaluated_slots: list[dict[str, Any]] = []
    for spec in CORE_SLOT_SPECS:
        model_evidence_ids = [
            evidence_id
            for evidence_id, text in rows
            if _contains_any(text, spec.model_aliases)
        ]
        outcome_evidence_ids = [
            evidence_id
            for evidence_id, text in rows
            if _contains_any(text, spec.model_aliases)
            and _outcome_matches_family(text, spec.outcome_family)
        ]
        categories = {
            "formulation": formulation_evidence_ids,
            "payload": payload_evidence_ids,
            "model": model_evidence_ids,
            "outcome": outcome_evidence_ids,
        }
        formulation_texts = [
            text
            for evidence_id, text in rows
            if evidence_id in formulation_evidence_ids
        ]
        composition_terms = _ordered_union(
            *[
                _matched_terms(text, FORMULATION_COMPOSITION_TERMS)
                for text in formulation_texts
            ]
        )
        slot_payload_terms = _ordered_union(
            *[
                _payload_terms(text)
                for evidence_id, text in rows
                if evidence_id in payload_evidence_ids
            ]
        )
        missing_categories = [
            category
            for category, evidence_ids in categories.items()
            if not evidence_ids
        ]
        qualified = not missing_categories
        evaluated_slots.append(
            {
                "slot_id": spec.slot_id,
                "model_family": spec.model_family,
                "outcome_family": spec.outcome_family,
                "qualified": qualified,
                "evidence_ids": _ordered_union(*categories.values()),
                "formulation_evidence_ids": list(
                    formulation_evidence_ids
                ),
                "payload_evidence_ids": list(payload_evidence_ids),
                "model_evidence_ids": model_evidence_ids,
                "outcome_evidence_ids": outcome_evidence_ids,
                "formulation_signature": {
                    "group_markers": (
                        ["dx_lnp"]
                        if any(
                            _has_dx_lnp_group(text)
                            for text in formulation_texts
                        )
                        else []
                    ),
                    "composition_terms": composition_terms,
                },
                "payload_signature": {
                    "type_terms": [
                        term
                        for term in slot_payload_terms
                        if term in PAYLOAD_TYPE_TERMS
                    ],
                    "cargo_terms": [
                        term
                        for term in slot_payload_terms
                        if term in PAYLOAD_CARGO_TERMS
                    ],
                },
                "exclusion_reason": (
                    None
                    if qualified
                    else "missing_required_evidence:"
                    + ",".join(missing_categories)
                ),
            }
        )

    return {
        "qualification_version": QUALIFICATION_VERSION,
        "paper_id": "NP-001",
        "evaluated_slots": evaluated_slots,
        "qualified_slots": [
            row for row in evaluated_slots if row["qualified"]
        ],
    }


def build_core_slot_schema(
    core_schema: Mapping[str, Any],
    qualified_slots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Add a closed exact-key core-slot accounting object to compact schema."""

    slot_ids = [str(row.get("slot_id", "")) for row in qualified_slots]
    if any(not slot_id for slot_id in slot_ids):
        raise ValueError("each qualified core slot requires a slot_id")
    if len(slot_ids) != len(set(slot_ids)):
        raise ValueError("qualified core slot IDs must be unique")

    schema = deepcopy(dict(core_schema))
    properties = schema.setdefault("properties", {})
    required = list(schema.setdefault("required", []))
    definitions = schema.setdefault("$defs", {})
    definitions["CoreSlotAccountingEntry"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "disposition": {
                "type": "string",
                "enum": ["extracted", "duplicate"],
            },
            "linked_experiment_id": {
                "type": "string",
                "minLength": 1,
            },
            "linked_outcome_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
            "evidence_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
        },
        "required": [
            "disposition",
            "linked_experiment_id",
            "linked_outcome_ids",
            "evidence_ids",
        ],
    }
    properties["core_slot_contract_version"] = {
        "type": "string",
        "const": CORE_SLOT_CONTRACT_VERSION,
    }
    properties["core_slot_accounting"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            slot_id: {"$ref": "#/$defs/CoreSlotAccountingEntry"}
            for slot_id in slot_ids
        },
        "required": slot_ids,
    }
    for field in (
        "core_slot_contract_version",
        "core_slot_accounting",
    ):
        if field not in required:
            required.append(field)
    schema["required"] = required
    schema["additionalProperties"] = False
    return schema


def _error(
    report: dict[str, Any],
    code: str,
    message: str,
    **details: Any,
) -> None:
    report["errors"].append(
        {"code": code, "message": message, **details}
    )


def _reject(
    report: dict[str, Any],
    slot_id: str,
    reason: str,
    **details: Any,
) -> None:
    report["rejected_links"].append(
        {"slot_id": slot_id, "reason": reason, **details}
    )


def _reported_evidence_ids(
    record: Any,
    field_names: Sequence[str],
) -> set[str]:
    evidence_ids: set[str] = set()
    for field_name in field_names:
        value = getattr(record, field_name)
        evidence_ids.update(getattr(value, "evidence_ids", []))
    return evidence_ids


def _reported_text(
    record: Any,
    field_names: Sequence[str],
) -> str:
    values = []
    for field_name in field_names:
        field = getattr(record, field_name)
        value = getattr(field, "value", None)
        if value is not None:
            values.append(str(value))
    return " ".join(values)


def _slot_spec(slot_id: str) -> CoreSlotSpec | None:
    return next(
        (spec for spec in CORE_SLOT_SPECS if spec.slot_id == slot_id),
        None,
    )


def _claim_evidence_is_allowed(
    *,
    report: dict[str, Any],
    slot_id: str,
    evidence_ids: set[str],
    slot_allowed_evidence: set[str],
    evidence_envelope: set[str],
    record_kind: str,
) -> bool:
    valid = True
    for evidence_id in sorted(evidence_ids):
        if evidence_id not in slot_allowed_evidence:
            _error(
                report,
                "evidence_outside_slot",
                "linked record evidence is not allowed for this slot",
                slot_id=slot_id,
                evidence_id=evidence_id,
                record_kind=record_kind,
            )
            valid = False
        if evidence_id not in evidence_envelope:
            _error(
                report,
                "evidence_outside_request_envelope",
                "linked record evidence is absent from the request envelope",
                slot_id=slot_id,
                evidence_id=evidence_id,
                record_kind=record_kind,
            )
            valid = False
    return valid


def validate_core_slot_response(
    response: Mapping[str, Any],
    qualified_slots: Sequence[Mapping[str, Any]],
    evidence_envelope: set[str],
) -> dict[str, Any]:
    """Validate exact slot accounting and scientific record compatibility."""

    slot_rows = list(qualified_slots)
    slot_ids = [str(row.get("slot_id", "")) for row in slot_rows]
    if any(not slot_id for slot_id in slot_ids):
        raise ValueError("each qualified core slot requires a slot_id")
    if len(slot_ids) != len(set(slot_ids)):
        raise ValueError("qualified core slot IDs must be unique")
    slot_by_id = {
        slot_id: row for slot_id, row in zip(slot_ids, slot_rows)
    }
    body = dict(response)
    contract_version = body.pop("core_slot_contract_version", None)
    accounting = body.pop("core_slot_accounting", {})
    report: dict[str, Any] = {
        "core_slot_contract_version": contract_version,
        "slots_sent": len(slot_ids),
        "slots_accounted_for": 0,
        "scientifically_confirmed": 0,
        "valid_duplicates": 0,
        "rejected_links": [],
        "confirmed_slot_ids": [],
        "errors": [],
    }
    if contract_version != CORE_SLOT_CONTRACT_VERSION:
        _error(
            report,
            "core_slot_contract_version_mismatch",
            "core_slot_contract_version must match the trial contract",
        )
    if not isinstance(accounting, Mapping):
        _error(
            report,
            "core_slot_accounting_not_object",
            "core_slot_accounting must be an object",
        )
        accounting = {}

    returned_ids = set(accounting)
    expected_ids = set(slot_ids)
    missing_ids = sorted(expected_ids - returned_ids)
    unknown_ids = sorted(returned_ids - expected_ids)
    if missing_ids:
        _error(
            report,
            "missing_slot_keys",
            "core_slot_accounting omitted qualified slot IDs",
            slot_ids=missing_ids,
        )
    if unknown_ids:
        _error(
            report,
            "unknown_slot_keys",
            "core_slot_accounting included unqualified slot IDs",
            slot_ids=unknown_ids,
        )
    accounted_ids = expected_ids & returned_ids
    report["slots_accounted_for"] = len(accounted_ids)

    try:
        compact_response = CompactExtractionResponse.model_validate(body)
    except ValidationError as exc:
        _error(
            report,
            "compact_response_invalid",
            "core compact response failed validation",
            details=str(exc),
        )
        return report

    experiment_by_id = {
        row.experiment_id: row for row in compact_response.experiments
    }
    outcome_ids = [
        row.outcome_id for row in compact_response.outcomes
    ]
    duplicate_outcome_ids = sorted(
        {
            outcome_id
            for outcome_id in outcome_ids
            if outcome_ids.count(outcome_id) > 1
        }
    )
    fatal_outcome_identity_error = bool(duplicate_outcome_ids)
    if duplicate_outcome_ids:
        _error(
            report,
            "duplicate_outcome_ids",
            "compact response outcome IDs must be unique",
            outcome_ids=duplicate_outcome_ids,
        )
    outcome_by_id = {
        row.outcome_id: row for row in compact_response.outcomes
    }
    formulation_by_id = {
        row.formulation_id: row
        for row in compact_response.formulations
    }
    allowed_entry_fields = {
        "disposition",
        "linked_experiment_id",
        "linked_outcome_ids",
        "evidence_ids",
    }
    valid_claims: dict[str, dict[str, Any]] = {}

    for slot_id in slot_ids:
        if slot_id not in accounted_ids:
            continue
        slot = slot_by_id[slot_id]
        spec = _slot_spec(slot_id)
        entry = accounting[slot_id]
        invalid = fatal_outcome_identity_error
        if spec is None:
            _error(
                report,
                "unknown_closed_slot",
                "qualified slot is outside the closed NP-001 matrix",
                slot_id=slot_id,
            )
            continue
        if not isinstance(entry, Mapping):
            _error(
                report,
                "slot_entry_not_object",
                "each core slot entry must be an object",
                slot_id=slot_id,
            )
            continue
        missing_fields = sorted(allowed_entry_fields - set(entry))
        unknown_fields = sorted(set(entry) - allowed_entry_fields)
        if missing_fields:
            _error(
                report,
                "missing_slot_entry_fields",
                "core slot entry omitted required fields",
                slot_id=slot_id,
                fields=missing_fields,
            )
            continue
        if unknown_fields:
            _error(
                report,
                "unknown_slot_entry_fields",
                "core slot entry contains unknown fields",
                slot_id=slot_id,
                fields=unknown_fields,
            )
            invalid = True

        disposition = entry["disposition"]
        experiment_id = entry["linked_experiment_id"]
        linked_outcome_ids = entry["linked_outcome_ids"]
        cited_evidence_ids = entry["evidence_ids"]
        if disposition not in {"extracted", "duplicate"}:
            _error(
                report,
                "invalid_slot_disposition",
                "core slot disposition must be extracted or duplicate",
                slot_id=slot_id,
            )
            invalid = True
        if not isinstance(experiment_id, str) or not experiment_id:
            _error(
                report,
                "invalid_linked_experiment_id",
                "linked_experiment_id must be a nonempty string",
                slot_id=slot_id,
            )
            invalid = True
        if (
            not isinstance(linked_outcome_ids, list)
            or not linked_outcome_ids
            or not all(
                isinstance(outcome_id, str)
                for outcome_id in linked_outcome_ids
            )
        ):
            _error(
                report,
                "invalid_linked_outcome_ids",
                "linked_outcome_ids must be a nonempty string list",
                slot_id=slot_id,
            )
            linked_outcome_ids = []
            invalid = True
        elif len(linked_outcome_ids) != len(set(linked_outcome_ids)):
            _error(
                report,
                "duplicate_linked_outcome_ids",
                "linked_outcome_ids must be unique",
                slot_id=slot_id,
            )
            invalid = True
        if (
            not isinstance(cited_evidence_ids, list)
            or not cited_evidence_ids
            or not all(
                isinstance(evidence_id, str)
                for evidence_id in cited_evidence_ids
            )
        ):
            _error(
                report,
                "invalid_slot_evidence_ids",
                "slot evidence_ids must be a nonempty string list",
                slot_id=slot_id,
            )
            cited_evidence_ids = []
            invalid = True
        elif len(cited_evidence_ids) != len(
            set(cited_evidence_ids)
        ):
            _error(
                report,
                "duplicate_slot_evidence_ids",
                "slot evidence_ids must be unique",
                slot_id=slot_id,
            )
            invalid = True

        slot_allowed_evidence = set(slot.get("evidence_ids", []))
        for evidence_id in cited_evidence_ids:
            if evidence_id not in slot_allowed_evidence:
                _error(
                    report,
                    "evidence_outside_slot",
                    "cited evidence is not allowed for this slot",
                    slot_id=slot_id,
                    evidence_id=evidence_id,
                )
                invalid = True
            if evidence_id not in evidence_envelope:
                _error(
                    report,
                    "evidence_outside_request_envelope",
                    "cited evidence is absent from the request envelope",
                    slot_id=slot_id,
                    evidence_id=evidence_id,
                )
                invalid = True

        experiment_row = experiment_by_id.get(experiment_id)
        if experiment_row is None:
            _reject(
                report,
                slot_id,
                "unknown_experiment_id",
                experiment_id=experiment_id,
            )
            continue
        model_text = _reported_text(
            experiment_row,
            (
                "delivery_recipient_cell",
                "therapeutic_target_cell",
                "tissue_or_organ",
                "species",
                "disease_model",
                "experimental_context",
            ),
        )
        model_family_matches = _contains_any(
            model_text,
            spec.model_aliases,
        )
        if spec.model_family == "mouse_in_vivo":
            model_family_matches = (
                model_family_matches
                and experiment_row.experimental_context.value == "in_vivo"
            )
        if not model_family_matches:
            _reject(
                report,
                slot_id,
                "model_family_mismatch",
                experiment_id=experiment_id,
            )
            invalid = True

        formulation_row = formulation_by_id.get(
            experiment_row.formulation_id
        )
        if formulation_row is None:
            _reject(
                report,
                slot_id,
                "unknown_formulation_id",
                formulation_id=experiment_row.formulation_id,
            )
            invalid = True
        else:
            formulation_evidence = _reported_evidence_ids(
                formulation_row,
                (
                    "formulation_name",
                    "composition",
                    "composition_basis",
                    "np_ratio",
                ),
            )
            if not formulation_evidence & set(
                slot.get("formulation_evidence_ids", [])
            ):
                _reject(
                    report,
                    slot_id,
                    "formulation_evidence_mismatch",
                    formulation_id=experiment_row.formulation_id,
                )
                invalid = True
            if not _claim_evidence_is_allowed(
                report=report,
                slot_id=slot_id,
                evidence_ids=formulation_evidence,
                slot_allowed_evidence=slot_allowed_evidence,
                evidence_envelope=evidence_envelope,
                record_kind="formulation",
            ):
                invalid = True
            formulation_name_text = _reported_text(
                formulation_row,
                ("formulation_name",),
            )
            formulation_signature = slot.get(
                "formulation_signature", {}
            )
            expected_group_markers = tuple(
                formulation_signature.get("group_markers", [])
            )
            composition_text = _reported_text(
                formulation_row,
                ("composition",),
            )
            expected_composition_terms = tuple(
                formulation_signature.get("composition_terms", [])
            )
            group_matches = (
                "dx_lnp" not in expected_group_markers
                or _has_dx_lnp_group(formulation_name_text)
            )
            alternative_terms = {
                term
                for group in FORMULATION_ALTERNATIVE_COMPONENTS
                for term in group
            }
            required_composition_terms = tuple(
                term
                for term in expected_composition_terms
                if term not in alternative_terms
                and term not in {"ionizable lipid", "helper lipid"}
            )
            composition_matches = (
                not required_composition_terms
                or all(
                    _contains_term(composition_text, term)
                    for term in required_composition_terms
                )
            )
            alternatives_match = all(
                not any(
                    term in expected_composition_terms for term in group
                )
                or any(_contains_term(composition_text, term) for term in group)
                for group in FORMULATION_ALTERNATIVE_COMPONENTS
            )
            if (
                not group_matches
                or not composition_matches
                or not alternatives_match
            ):
                _reject(
                    report,
                    slot_id,
                    "formulation_semantic_mismatch",
                    formulation_id=experiment_row.formulation_id,
                )
                invalid = True

        payload_evidence = _reported_evidence_ids(
            experiment_row,
            (
                "payload_type",
                "payload_name",
                "encoded_product",
                "molecular_target",
            ),
        )
        if not payload_evidence & set(
            slot.get("payload_evidence_ids", [])
        ):
            _reject(
                report,
                slot_id,
                "payload_evidence_mismatch",
                experiment_id=experiment_id,
            )
            invalid = True
        if not _claim_evidence_is_allowed(
            report=report,
            slot_id=slot_id,
            evidence_ids=payload_evidence,
            slot_allowed_evidence=slot_allowed_evidence,
            evidence_envelope=evidence_envelope,
            record_kind="payload",
        ):
            invalid = True
        payload_text = _reported_text(
            experiment_row,
            (
                "payload_type",
                "payload_name",
                "encoded_product",
                "molecular_target",
            ),
        )
        payload_signature = slot.get("payload_signature", {})
        returned_payload_terms = set(_payload_terms(payload_text))
        expected_payload_types = set(
            payload_signature.get("type_terms", [])
        )
        expected_payload_cargo = set(
            payload_signature.get("cargo_terms", [])
        )
        if (
            expected_payload_types
            and not expected_payload_types & returned_payload_terms
        ) or (
            expected_payload_cargo
            and not expected_payload_cargo & returned_payload_terms
        ):
            _reject(
                report,
                slot_id,
                "payload_semantic_mismatch",
                experiment_id=experiment_id,
            )
            invalid = True
        model_evidence = _reported_evidence_ids(
            experiment_row,
            (
                "delivery_recipient_cell",
                "therapeutic_target_cell",
                "tissue_or_organ",
                "species",
                "disease_model",
                "experimental_context",
            ),
        )
        if not model_evidence & set(
            slot.get("model_evidence_ids", [])
        ):
            _reject(
                report,
                slot_id,
                "model_evidence_mismatch",
                experiment_id=experiment_id,
            )
            invalid = True
        if not _claim_evidence_is_allowed(
            report=report,
            slot_id=slot_id,
            evidence_ids=model_evidence,
            slot_allowed_evidence=slot_allowed_evidence,
            evidence_envelope=evidence_envelope,
            record_kind="model",
        ):
            invalid = True

        for outcome_id in linked_outcome_ids:
            outcome_row = outcome_by_id.get(outcome_id)
            if outcome_row is None:
                _reject(
                    report,
                    slot_id,
                    "unknown_outcome_id",
                    outcome_id=outcome_id,
                )
                invalid = True
                continue
            if outcome_row.experiment_id != experiment_id:
                _reject(
                    report,
                    slot_id,
                    "outcome_experiment_mismatch",
                    experiment_id=experiment_id,
                    outcome_id=outcome_id,
                    outcome_experiment_id=outcome_row.experiment_id,
                )
                invalid = True
            outcome_text = _reported_text(
                outcome_row,
                (
                    "endpoint",
                    "outcome_value",
                    "qualitative_outcome",
                ),
            )
            if not _outcome_matches_family(
                outcome_text,
                spec.outcome_family,
            ):
                _reject(
                    report,
                    slot_id,
                    "outcome_family_mismatch",
                    outcome_id=outcome_id,
                )
                invalid = True
            outcome_evidence = _reported_evidence_ids(
                outcome_row,
                (
                    "assay",
                    "endpoint",
                    "comparator",
                    "outcome_value",
                    "outcome_unit",
                    "qualitative_outcome",
                ),
            )
            if not outcome_evidence & set(
                slot.get("outcome_evidence_ids", [])
            ):
                _reject(
                    report,
                    slot_id,
                    "outcome_evidence_mismatch",
                    outcome_id=outcome_id,
                )
                invalid = True
            if not _claim_evidence_is_allowed(
                report=report,
                slot_id=slot_id,
                evidence_ids=outcome_evidence,
                slot_allowed_evidence=slot_allowed_evidence,
                evidence_envelope=evidence_envelope,
                record_kind="outcome",
            ):
                invalid = True

        if not invalid:
            valid_claims[slot_id] = {
                "disposition": disposition,
                "experiment_id": experiment_id,
                "outcome_ids": tuple(sorted(linked_outcome_ids)),
            }

    extracted_signatures = {
        (
            claim["experiment_id"],
            claim["outcome_ids"],
        )
        for claim in valid_claims.values()
        if claim["disposition"] == "extracted"
    }
    for slot_id in slot_ids:
        claim = valid_claims.get(slot_id)
        if claim is None:
            continue
        signature = (
            claim["experiment_id"],
            claim["outcome_ids"],
        )
        if claim["disposition"] == "duplicate":
            if signature not in extracted_signatures:
                _error(
                    report,
                    "duplicate_not_shared",
                    "duplicate slot must share a valid extracted record",
                    slot_id=slot_id,
                )
                continue
            report["valid_duplicates"] += 1
        report["confirmed_slot_ids"].append(slot_id)

    report["scientifically_confirmed"] = len(
        report["confirmed_slot_ids"]
    )
    return report
