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
    ratios = []
    for match in re.finditer(
        r"(\d+(?:\.\d+)?(?:\s*:\s*\d+(?:\.\d+)?)+)", composition
    ):
        values = tuple(re.findall(r"\d+(?:\.\d+)?", match.group(1)))
        context = composition[max(0, match.start() - 24):match.end() + 24]
        mentioned_types = tuple(
            ratio_type for ratio_type in ("mass", "molar")
            if ratio_type in context
        )
        ratio_type = mentioned_types[0] if len(mentioned_types) == 1 else (
            "unspecified" if not mentioned_types else "ambiguous"
        )
        ratios.append((ratio_type, values))
    return (
        _normalized_name(raw), supported_components, tuple(ratios),
        _reported(raw.get("np_ratio")),
    )


def _canonical_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _merge_supported_field(
    field_name: str, target: dict[str, Any], incoming: dict[str, Any]
) -> None:
    target_value = _reported(target)
    incoming_value = _reported(incoming)
    if target_value is None and incoming_value is not None:
        target["value"] = incoming_value
        target["status"] = incoming.get("status", target.get("status"))
        target["missing_reason"] = incoming.get("missing_reason")
    elif (
        target_value is not None
        and incoming_value is not None
        and _canonical_text(target_value) != _canonical_text(incoming_value)
        and field_name in {"composition", "composition_basis"}
    ):
        target["supported_values"] = list(dict.fromkeys([
            *target.get("supported_values", [target_value]), incoming_value
        ]))
        if field_name == "composition_basis":
            target_ratio = _mass_ratio(target_value)
            incoming_ratio = _mass_ratio(incoming_value)
            if target_ratio is None and incoming_ratio is not None:
                target["value"] = incoming_value
    target["evidence_ids"] = list(dict.fromkeys(
        [*target.get("evidence_ids", []), *incoming.get("evidence_ids", [])]
    ))


def _mass_ratio(value: Any) -> tuple[str, str] | None:
    text = str(value or "").lower()
    match = re.search(
        r"(?:lipid\s*[:/]?\s*nucleic[- ]acid\s+)?mass ratio\s+(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)",
        text,
    )
    return match.groups() if match else None


def _incompatible_fields(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> list[str]:
    incompatible = []
    for field_name in (
        "formulation_name", "composition", "composition_basis", "np_ratio"
    ):
        left = _reported(existing.get(field_name))
        right = _reported(incoming.get(field_name))
        if left is None or right is None:
            continue
        if field_name == "formulation_name":
            conflict = _normalized_name(existing) != _normalized_name(incoming)
        elif field_name == "composition_basis":
            left_ratio, right_ratio = _mass_ratio(left), _mass_ratio(right)
            exclusive_terms = ("measured", "theoretical", "nominal")
            left_terms = {
                term for term in exclusive_terms
                if term in _canonical_text(left).split()
            }
            right_terms = {
                term for term in exclusive_terms
                if term in _canonical_text(right).split()
            }
            conflict = (
                left_ratio is not None
                and right_ratio is not None
                and left_ratio != right_ratio
            ) or bool(left_terms and right_terms and left_terms != right_terms)
            if not conflict and left_ratio is None and right_ratio is None:
                left_canonical = _canonical_text(left)
                right_canonical = _canonical_text(right)
                conflict = not (
                    left_canonical == right_canonical
                    or left_canonical == "molar ratio"
                    or right_canonical == "molar ratio"
                )
        elif field_name == "composition":
            conflict = _scientific_identity(existing)[:3] != _scientific_identity(incoming)[:3]
        else:
            conflict = left != right
        if conflict:
            incompatible.append(field_name)
    return incompatible


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
    formulations_by_identity: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    formulations_by_name: dict[str, list[dict[str, Any]]] = {}

    for slice_name, payload in ordered:
        formulation_map: dict[str, str] = {}
        for raw in payload.get("formulations", []):
            original_id = raw["formulation_id"]
            identity = _scientific_identity(raw)
            name = _normalized_name(raw)
            variants = formulations_by_name.setdefault(name, [])
            identity_candidates = formulations_by_identity.get(identity, [])
            match = next(
                (
                    candidate for candidate in identity_candidates
                    if not _incompatible_fields(candidate["record"], raw)
                ),
                None,
            )
            if match is None:
                variant_id = original_id if not variants else f"{original_id}::conflict-{len(variants) + 1}"
                record = copy.deepcopy(raw)
                record["formulation_id"] = variant_id
                record["source_slices"] = [slice_name]
                merged["formulations"].append(record)
                match = {"identity": identity, "id": variant_id, "record": record}
                if variants:
                    for field_name in ("formulation_name", "composition", "composition_basis", "np_ratio"):
                        conflicting_rows = [
                            row for row in variants
                            if field_name in _incompatible_fields(row["record"], raw)
                        ]
                        if conflicting_rows:
                            merged["conflicts"].append({
                                "entity_type": "formulation",
                                "source_id": original_id,
                                "field_name": field_name,
                                "source_slices": [slice_name],
                                "left_formulation_ids": [row["id"] for row in conflicting_rows],
                                "right_formulation_id": variant_id,
                                "left_evidence_ids": list(dict.fromkeys([
                                    evidence_id for row in conflicting_rows
                                    for evidence_id in row["record"][field_name].get("evidence_ids", [])
                                ])),
                                "right_evidence_ids": list(dict.fromkeys(
                                    raw[field_name].get("evidence_ids", [])
                                )),
                            })
                variants.append(match)
                formulations_by_identity.setdefault(identity, []).append(match)
            elif slice_name not in match["record"]["source_slices"]:
                match["record"]["source_slices"].append(slice_name)
                for field_name in (
                    "formulation_name", "composition", "composition_basis", "np_ratio"
                ):
                    _merge_supported_field(
                        field_name, match["record"][field_name], raw[field_name]
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

    # Components are formulation properties, not recipient-cell properties.
    # Merge identical component rows repeated by the isolated cell slices while
    # retaining the union of their evidence and source-slice provenance.
    unique_components: dict[tuple[Any, ...], dict[str, Any]] = {}
    for component in merged["components"]:
        normalized_unit = _canonical_text(_reported(component.get("amount_unit")))
        if normalized_unit in {"mol", "molar ratio parts"}:
            normalized_unit = "mol percent"
        identity = (
            component["formulation_id"],
            _canonical_text(_reported(component.get("identity"))),
            _canonical_text(_reported(component.get("role"))),
            _reported(component.get("amount")),
            normalized_unit,
        )
        existing = unique_components.get(identity)
        if existing is None:
            existing = component
            existing["source_slices"] = [component["source_slice"]]
            unique_components[identity] = existing
            continue
        existing["source_slices"].append(component["source_slice"])
        for field_name in ("identity", "role", "amount", "amount_unit"):
            _merge_supported_field(
                field_name, existing[field_name], component[field_name]
            )
    merged["components"] = list(unique_components.values())
    return merged


def load_and_reconcile(paths: Iterable[Path]) -> dict[str, Any]:
    slices = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            slices.append((path.parent.name, json.load(handle)))
    return reconcile_slices(slices)


__all__ = ["load_and_reconcile", "reconcile_slices"]
