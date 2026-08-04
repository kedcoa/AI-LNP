from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CanonicalFact:
    raw_value: str
    canonical_value: str
    normalization_rule: str
    evidence_ids: tuple[str, ...]


_ASSAY_ALIASES = {
    "ddpcr": "droplet digital pcr",
    "digital droplet pcr": "droplet digital pcr",
    "qpcr": "quantitative pcr",
}
_UNIT_ALIASES = {
    "percent": "%",
    "mol percent": "mol%",
    "mg per kg": "mg/kg",
}
_UNIT_FIELDS = {
    "amount_unit",
    "dose_unit",
    "numeric_unit",
    "outcome_unit",
    "timepoint_unit",
    "unit",
}
_RATIO_FIELDS = {"component_ratio", "mass_ratio", "molar_ratio"}


def canonicalize_fact(
    field_name: str,
    raw_value: str,
    evidence_ids: Sequence[str],
) -> CanonicalFact:
    normalized = " ".join(raw_value.strip().casefold().split())
    rule = "casefold_whitespace"

    if field_name in _RATIO_FIELDS:
        normalized = re.sub(r"\s*:\s*", ":", normalized)
        rule = "ratio_spacing"
    elif field_name == "assay" and normalized in _ASSAY_ALIASES:
        normalized = _ASSAY_ALIASES[normalized]
        rule = "closed_alias"
    elif field_name in _UNIT_FIELDS and normalized in _UNIT_ALIASES:
        normalized = _UNIT_ALIASES[normalized]
        rule = "closed_alias"

    return CanonicalFact(raw_value, normalized, rule, tuple(dict.fromkeys(evidence_ids)))
