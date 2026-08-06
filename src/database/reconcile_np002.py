"""Deterministically reconcile overlapping NP-002 recipient-cell slices."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def reconcile_slices(
    slices: Iterable[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Union slices while retaining incompatible duplicates as explicit conflicts."""

    ordered = sorted(slices, key=lambda item: item[0])
    if not ordered:
        raise ValueError("at least one NP result slice is required")
    paper_ids = {payload.get("paper_id") for _, payload in ordered}
    if len(paper_ids) != 1:
        raise ValueError("NP slices must belong to one paper")

    merged: dict[str, Any] = {
        "paper_id": next(iter(paper_ids)),
        "formulations": [],
        "components": [],
        "experiments": [],
        "outcomes": [],
        "unresolved_items": [],
        "conflicts": [],
        "source_slices": [name for name, _ in ordered],
    }
    formulation_variants: dict[str, list[dict[str, Any]]] = {}

    for slice_name, payload in ordered:
        formulation_map: dict[str, str] = {}
        for raw in payload.get("formulations", []):
            original_id = raw["formulation_id"]
            content = {key: value for key, value in raw.items() if key != "formulation_id"}
            variants = formulation_variants.setdefault(original_id, [])
            match = next((row for row in variants if row["canonical"] == _canonical(content)), None)
            if match is None:
                variant_id = original_id if not variants else f"{original_id}::conflict-{len(variants) + 1}"
                record = copy.deepcopy(raw)
                record["formulation_id"] = variant_id
                record["source_slices"] = [slice_name]
                merged["formulations"].append(record)
                match = {"canonical": _canonical(content), "id": variant_id, "record": record}
                if variants:
                    for field_name in sorted(content):
                        if any(_canonical(row["record"].get(field_name)) != _canonical(raw.get(field_name)) for row in variants):
                            merged["conflicts"].append({
                                "entity_type": "formulation",
                                "source_id": original_id,
                                "field_name": field_name,
                                "source_slices": [slice_name],
                            })
                variants.append(match)
            elif slice_name not in match["record"]["source_slices"]:
                match["record"]["source_slices"].append(slice_name)
            formulation_map[original_id] = match["id"]

        experiment_map: dict[str, str] = {}
        for raw in payload.get("experiments", []):
            record = copy.deepcopy(raw)
            record["experiment_id"] = f"{slice_name}::{raw['experiment_id']}"
            record["formulation_id"] = formulation_map[raw["formulation_id"]]
            record["source_slice"] = slice_name
            experiment_map[raw["experiment_id"]] = record["experiment_id"]
            merged["experiments"].append(record)

        for raw in payload.get("components", []):
            record = copy.deepcopy(raw)
            record["component_id"] = f"{slice_name}::{raw['component_id']}"
            record["formulation_id"] = formulation_map[raw["formulation_id"]]
            record["source_slice"] = slice_name
            merged["components"].append(record)

        for raw in payload.get("outcomes", []):
            record = copy.deepcopy(raw)
            record["outcome_id"] = f"{slice_name}::{raw['outcome_id']}"
            record["experiment_id"] = experiment_map[raw["experiment_id"]]
            record["source_slice"] = slice_name
            merged["outcomes"].append(record)

        merged["unresolved_items"].extend(
            {"source_slice": slice_name, "text": text}
            for text in payload.get("unresolved_items", [])
        )
    return merged


def load_and_reconcile(paths: Iterable[Path]) -> dict[str, Any]:
    slices = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            slices.append((path.parent.name, json.load(handle)))
    return reconcile_slices(slices)


__all__ = ["load_and_reconcile", "reconcile_slices"]
