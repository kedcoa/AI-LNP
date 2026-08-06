"""Deterministically reconcile overlapping NP-002 recipient-cell slices."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterable


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _reported(field: Any) -> Any:
    return field.get("value") if isinstance(field, dict) else field


def _normalized_name(raw: dict[str, Any]) -> str:
    name = str(_reported(raw.get("formulation_name")) or "").lower()
    return re.sub(r"\blnp\b|[^a-z0-9]+", "", name)


def _scientific_identity(raw: dict[str, Any]) -> tuple[Any, ...]:
    composition = str(_reported(raw.get("composition")) or "").lower()
    supported_components = tuple(
        component for component in ("mc3", "ckke12", "cholesterol", "c14peg2000", "dspc")
        if component in re.sub(r"[^a-z0-9]+", "", composition)
    )
    ratios = tuple(re.findall(r"\d+(?:\.\d+)?", composition))
    return (
        _normalized_name(raw), supported_components, ratios,
        _reported(raw.get("np_ratio")),
    )


def _merge_supported_field(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    target_value = _reported(target)
    incoming_value = _reported(incoming)
    if incoming_value is not None and (
        target_value is None or len(str(incoming_value)) > len(str(target_value))
    ):
        target["value"] = incoming_value
        target["status"] = incoming.get("status", target.get("status"))
        target["missing_reason"] = incoming.get("missing_reason")
    target["evidence_ids"] = list(dict.fromkeys(
        [*target.get("evidence_ids", []), *incoming.get("evidence_ids", [])]
    ))


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
    formulations_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    formulations_by_name: dict[str, list[dict[str, Any]]] = {}

    for slice_name, payload in ordered:
        formulation_map: dict[str, str] = {}
        for raw in payload.get("formulations", []):
            original_id = raw["formulation_id"]
            identity = _scientific_identity(raw)
            name = _normalized_name(raw)
            variants = formulations_by_name.setdefault(name, [])
            match = formulations_by_identity.get(identity)
            if match is None:
                variant_id = original_id if not variants else f"{original_id}::conflict-{len(variants) + 1}"
                record = copy.deepcopy(raw)
                record["formulation_id"] = variant_id
                record["source_slices"] = [slice_name]
                merged["formulations"].append(record)
                match = {"identity": identity, "id": variant_id, "record": record}
                if variants:
                    for field_name in ("formulation_name", "composition", "composition_basis", "np_ratio"):
                        if any(_canonical(row["record"].get(field_name)) != _canonical(raw.get(field_name)) for row in variants):
                            merged["conflicts"].append({
                                "entity_type": "formulation",
                                "source_id": original_id,
                                "field_name": field_name,
                                "source_slices": [slice_name],
                            })
                variants.append(match)
                formulations_by_identity[identity] = match
            elif slice_name not in match["record"]["source_slices"]:
                match["record"]["source_slices"].append(slice_name)
                for field_name in (
                    "formulation_name", "composition", "composition_basis", "np_ratio"
                ):
                    _merge_supported_field(
                        match["record"][field_name], raw[field_name]
                    )
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
