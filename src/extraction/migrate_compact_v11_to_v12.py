"""Losslessly migrate v1.1 results; never invent missing variability."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path

from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.compact_contracts_v12 import CompactExtractionResponseV12


INEQUALITY = re.compile(r"^\s*([<>~])\s*(-?\d+(?:\.\d+)?)\s*$")
VARIABILITY = re.compile(r"±\s*(\d+(?:\.\d+)?)")


def _reported(value, evidence_ids):
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": evidence_ids,
        "missing_reason": None,
    }


def _missing(reason):
    return {
        "value": None,
        "status": "missing",
        "evidence_ids": [],
        "missing_reason": reason,
    }


def migrate(payload: dict) -> CompactExtractionResponseV12:
    source = CompactExtractionResponse.model_validate(payload)
    migrated = deepcopy(source.model_dump(mode="json"))
    migrated["contract_version"] = "compact-1.2.0"
    for outcome in migrated["outcomes"]:
        value = outcome["outcome_value"]
        evidence_ids = value["evidence_ids"]
        qualifier = "exact"
        qualitative = outcome["qualitative_outcome"].get("value") or ""
        match = INEQUALITY.match(str(qualitative))
        if match and value["status"] == "missing":
            symbol, number = match.groups()
            value.update(_reported(float(number), outcome["qualitative_outcome"]["evidence_ids"]))
            evidence_ids = value["evidence_ids"]
            qualifier = {
                ">": "greater_than",
                "<": "less_than",
                "~": "approximate",
            }[symbol]
        outcome["value_qualifier"] = (
            _reported(qualifier, evidence_ids)
            if value["status"] == "reported"
            else _missing("No reported numeric value to qualify.")
        )
        unit_text = outcome["outcome_unit"].get("value") or ""
        variability = VARIABILITY.search(unit_text)
        outcome["variability_value"] = (
            _reported(float(variability.group(1)), outcome["outcome_unit"]["evidence_ids"])
            if variability
            else _missing("Variability was not separated in the v1.1 record.")
        )
        outcome["variability_type"] = _missing(
            "The v1.1 record did not preserve SD/SEM/CI/range type."
        )
    return CompactExtractionResponseV12.model_validate(migrated)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = migrate(json.loads(args.input.read_text(encoding="utf-8")))
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite an existing migrated result")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
