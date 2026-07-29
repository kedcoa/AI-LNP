"""Build deterministic atomic candidates from Docling table intersections."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .v12_structure_contracts import (
    AtomicClaimV12,
    AtomicOutcomeCandidateV12,
    EvidenceReferenceV12,
    ProvisionalExperimentInventoryV12,
)
from .v12_visual_contracts import DoclingTableV12, DoclingVisualObjectV12


ROOT = Path(__file__).resolve().parents[2]
DOCLING_ROOT = ROOT / "data/staging/extraction/v12_docling_visual"
EXPERIMENT_ROOT = (
    ROOT / "data/staging/extraction/v12_provisional_experiments"
)
OUTPUT = ROOT / "data/staging/extraction/v12_docling_candidates"


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def _numeric(text: str) -> float | None:
    match = re.search(r"(?<![A-Za-z])(-?\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def _headers(
    table: DoclingTableV12, row: int, column: int
) -> tuple[str | None, str | None]:
    row_headers = [
        cell.text for cell in table.cells
        if cell.is_row_header and cell.row == row and cell.text
    ]
    column_headers = [
        cell.text for cell in table.cells
        if cell.is_column_header and cell.column == column and cell.text
    ]
    return (
        " / ".join(dict.fromkeys(row_headers)) or None,
        " / ".join(dict.fromkeys(column_headers)) or None,
    )


def _experiment(
    parsed: DoclingVisualObjectV12,
) -> tuple[str | None, list[str]]:
    path = EXPERIMENT_ROOT / parsed.paper_id / "inventory.json"
    if not path.exists():
        return None, []
    inventory = ProvisionalExperimentInventoryV12.model_validate_json(
        path.read_text()
    )
    context = f"{parsed.caption} {parsed.figure_or_table}".lower()
    scored: list[tuple[int, str, list[str]]] = []
    for experiment in inventory.experiments:
        values = [anchor.value for anchor in experiment.anchors]
        score = 0
        for value in values:
            tokens = [token for token in re.split(r"[_\W]+", value.lower()) if token]
            if tokens and all(token in context for token in tokens):
                score += 1
        scored.append((score, experiment.provisional_experiment_id, values))
    best = max(scored, default=(0, "", []))
    tied = [row for row in scored if row[0] == best[0] and row[0] > 0]
    if len(tied) != 1:
        return None, []
    intervention = [
        value.replace("_", "/")
        for value in best[2]
        if value in {"cas9_sgrna", "egfp_gfp", "fapcar"}
    ]
    return best[1], intervention


def build_for_object(
    parsed: DoclingVisualObjectV12,
) -> tuple[list[AtomicClaimV12], list[AtomicOutcomeCandidateV12]]:
    experiment_id, intervention = _experiment(parsed)
    claims: list[AtomicClaimV12] = []
    candidates: list[AtomicOutcomeCandidateV12] = []
    for table in parsed.tables:
        for cell in table.cells:
            if cell.is_row_header or cell.is_column_header or not cell.text:
                continue
            numeric_value = _numeric(cell.text)
            if numeric_value is None:
                continue
            row_header, column_header = _headers(table, cell.row, cell.column)
            if not row_header or not column_header:
                continue
            source_id = (
                f"{parsed.object_id}:table-{table.table_index}:"
                f"r{cell.row}:c{cell.column}"
            )
            evidence_id = _stable_id("VIS", source_id)
            claim_id = _stable_id("ACL-VIS", source_id)
            quote = f"{row_header} | {column_header} | {cell.text}"
            evidence = EvidenceReferenceV12(
                evidence_id=evidence_id,
                source_id=source_id,
                quote=quote,
                locator_type="table_cell",
                row_label=row_header,
                column_label=column_header,
                panel_label=parsed.figure_or_table,
            )
            unit = "%" if "%" in cell.text else None
            claim = AtomicClaimV12(
                claim_id=claim_id,
                claim_kind="outcome",
                subject_text=row_header,
                predicate="reached",
                endpoint_text=column_header,
                numeric_value=numeric_value,
                value_text=cell.text,
                unit=unit,
                polarity="neutral",
                intervention_context=intervention,
                provisional_experiment_id=experiment_id,
                evidence=[evidence],
                review_status="supported",
            )
            signature = "|".join([
                parsed.paper_id,
                experiment_id or "unassigned",
                row_header.lower(),
                "reached",
                column_header.lower(),
                cell.text.lower(),
            ])
            candidate = AtomicOutcomeCandidateV12(
                candidate_id=_stable_id("AOC-VIS", signature),
                paper_id=parsed.paper_id,
                claim_ids=[claim_id],
                provisional_experiment_id=experiment_id,
                subject_text=row_header,
                predicate="reached",
                endpoint_text=column_header,
                numeric_value=numeric_value,
                value_text=cell.text,
                unit=unit,
                polarity="neutral",
                evidence_ids=[evidence_id],
                source_ids=[source_id],
                route_hint="vision",
                confidence="high",
                review_reasons=[],
                structural_signature=signature,
            )
            claims.append(claim)
            candidates.append(candidate)
    return claims, candidates


def run(object_ids: set[str] | None = None) -> dict[str, Any]:
    paths = sorted(DOCLING_ROOT.glob("*/docling_object.json"))
    if object_ids:
        paths = [path for path in paths if path.parent.name in object_ids]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "contract_version": "1.0.0",
        "builder": "deterministic_docling_table_intersections",
        "objects": [],
    }
    for path in paths:
        parsed = DoclingVisualObjectV12.model_validate_json(path.read_text())
        claims, candidates = build_for_object(parsed)
        object_dir = OUTPUT / parsed.object_id
        object_dir.mkdir(parents=True, exist_ok=True)
        (object_dir / "claims.json").write_text(json.dumps(
            [claim.model_dump(mode="json") for claim in claims],
            indent=2,
            ensure_ascii=False,
        ) + "\n")
        (object_dir / "candidates.json").write_text(json.dumps(
            [candidate.model_dump(mode="json") for candidate in candidates],
            indent=2,
            ensure_ascii=False,
        ) + "\n")
        manifest["objects"].append({
            "object_id": parsed.object_id,
            "paper_id": parsed.paper_id,
            "claims": len(claims),
            "candidates": len(candidates),
            "candidate_path": str(
                (object_dir / "candidates.json").relative_to(ROOT)
            ),
        })
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", action="append")
    args = parser.parse_args()
    print(json.dumps(run(
        set(args.object_id) if args.object_id else None
    ), indent=2))
