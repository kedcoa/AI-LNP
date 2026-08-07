"""Stable scientific identities for source facts, evidence, and formulations."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping


_NUMBER = re.compile(r"(?<![A-Za-z0-9])[-+]?(?:\d+\.\d+|\d+)(?![A-Za-z0-9])")
_UNIT_ALIASES = {
    "mg per kg": "mg/kg",
    "mg kg-1": "mg/kg",
    "mg kg−1": "mg/kg",
    "μg": "ug",
    "µg": "ug",
    "mole %": "mol%",
    "molar %": "mol%",
}
_ROLE_ALIASES = {
    "ionizable": "ionizable_lipid",
    "ionisable_lipid": "ionizable_lipid",
    "helper": "helper_lipid",
    "phospholipid": "helper_lipid",
    "chol": "cholesterol",
    "peg": "peg_lipid",
    "targeting": "targeting_ligand",
}


@dataclass(frozen=True)
class CompositionPart:
    role: str
    component_name: str | None
    amount_value: float | int | str | None
    amount_unit: str | None


def _text(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    for source, target in _UNIT_ALIASES.items():
        normalized = normalized.replace(source, target)

    def canonical_number(match: re.Match[str]) -> str:
        try:
            number = Decimal(match.group(0))
        except InvalidOperation:
            return match.group(0)
        rendered = format(number.normalize(), "f")
        return "0" if Decimal(rendered) == 0 else rendered

    return _NUMBER.sub(canonical_number, normalized)


def _canonical(value: object) -> object:
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(child) for child in value]
    if isinstance(value, float):
        return _text(str(value))
    return value


def _digest(payload: object) -> str:
    encoded = json.dumps(
        _canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fact_identity(
    paper_id: str,
    subject_type: str,
    context_key: str,
    field_name: str,
    normalized_value: object,
) -> str:
    """Identify one scientific assertion without discarding its context."""

    return _digest(
        {
            "paper_id": paper_id,
            "subject_type": subject_type,
            "context_key": context_key,
            "field_name": field_name,
            "value": normalized_value,
        }
    )


def evidence_identity(
    paper_id: str,
    artifact_sha256: str,
    locator: Mapping[str, object],
    excerpt: str | None,
    structured_evidence: object,
) -> str:
    """Identify one evidence occurrence while preserving source and location."""

    return _digest(
        {
            "paper_id": paper_id,
            "artifact_sha256": artifact_sha256,
            "locator": locator,
            "excerpt": excerpt,
            "structured_evidence": structured_evidence,
        }
    )


def composition_fingerprint(
    components: Iterable[CompositionPart],
) -> str | None:
    """Return an order-independent fingerprint without inventing missing identity."""

    canonical_parts: list[dict[str, object]] = []
    for part in components:
        if part.component_name is None or not part.component_name.strip():
            return None
        role = _ROLE_ALIASES.get(_text(part.role), _text(part.role))
        canonical_parts.append(
            {
                **asdict(part),
                "role": role,
                "component_name": _text(part.component_name),
                "amount_value": (
                    None
                    if part.amount_value is None
                    else _text(str(part.amount_value))
                ),
                "amount_unit": (
                    None if part.amount_unit is None else _text(part.amount_unit)
                ),
            }
        )
    if not canonical_parts:
        return None
    canonical_parts.sort(
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"))
    )
    return _digest(canonical_parts)
