"""Parse selected reconstructed visual objects with local Docling.

Docling runs on the already reconstructed crop. Original PDF provenance comes
from the immutable Day 8 object inventory; the crop never replaces that source.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path
from typing import Any

from .v12_visual_contracts import (
    DoclingTableCellV12,
    DoclingTableV12,
    DoclingTextItemV12,
    DoclingVisualObjectV12,
    VisualBBoxV12,
)


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = (
    ROOT / "data/staging/extraction/day8_object_vision/object_inventory.json"
)
OUTPUT = ROOT / "data/staging/extraction/v12_docling_visual"


def _bbox(prov: list[dict[str, Any]]) -> VisualBBoxV12 | None:
    if not prov or not prov[0].get("bbox"):
        return None
    raw = prov[0]["bbox"]
    return VisualBBoxV12(
        left=float(raw["l"]),
        top=float(raw["t"]),
        right=float(raw["r"]),
        bottom=float(raw["b"]),
        coord_origin=str(raw.get("coord_origin", "unknown")),
    )


def _normalize_table(table: dict[str, Any], table_index: int) -> DoclingTableV12:
    raw_cells = table.get("data", {}).get("table_cells", [])
    cells: list[DoclingTableCellV12] = []
    row_count = 0
    column_count = 0
    for raw in raw_cells:
        start_row = int(raw.get("start_row_offset_idx", 0))
        end_row = int(raw.get("end_row_offset_idx", start_row + 1))
        start_column = int(raw.get("start_col_offset_idx", 0))
        end_column = int(raw.get("end_col_offset_idx", start_column + 1))
        row_count = max(row_count, end_row)
        column_count = max(column_count, end_column)
        cells.append(DoclingTableCellV12(
            row=start_row,
            column=start_column,
            row_span=max(1, end_row - start_row),
            column_span=max(1, end_column - start_column),
            text=str(raw.get("text", "")).strip(),
            is_row_header=bool(raw.get("row_header")),
            is_column_header=bool(raw.get("column_header")),
        ))
    grid = [["" for _ in range(column_count)] for _ in range(row_count)]
    for cell in cells:
        for row in range(cell.row, min(row_count, cell.row + cell.row_span)):
            for column in range(
                cell.column, min(column_count, cell.column + cell.column_span)
            ):
                grid[row][column] = cell.text
    return DoclingTableV12(
        table_index=table_index,
        rows=row_count,
        columns=column_count,
        grid=grid,
        cells=cells,
    )


def normalize_docling(
    inventory_row: dict[str, Any],
    exported: dict[str, Any],
    *,
    parser_version: str,
    parse_seconds: float,
) -> DoclingVisualObjectV12:
    crop = ROOT / inventory_row["crop_path"]
    text_items: list[DoclingTextItemV12] = []
    for raw in exported.get("texts", []):
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        prov = raw.get("prov") or []
        text_items.append(DoclingTextItemV12(
            label=str(raw.get("label", "text")),
            text=text,
            page_in_crop=int(prov[0].get("page_no", 1)) if prov else 1,
            bbox=_bbox(prov),
        ))
    tables = [
        _normalize_table(table, index)
        for index, table in enumerate(exported.get("tables", []))
    ]
    warnings: list[str] = []
    if inventory_row["object_type"] == "table" and not tables:
        warnings.append("inventory classified table but Docling found no table structure")
    if not text_items and not tables:
        warnings.append("Docling returned no OCR text or table structure")
    return DoclingVisualObjectV12(
        object_id=inventory_row["object_id"],
        paper_id=inventory_row["paper_id"],
        source_file=inventory_row["source_file"],
        original_page=int(inventory_row["page"]),
        figure_or_table=inventory_row["label"],
        inventory_object_type=inventory_row["object_type"],
        caption=inventory_row["caption"],
        source_crop=inventory_row["crop_path"],
        source_crop_sha256=hashlib.sha256(crop.read_bytes()).hexdigest(),
        parser_version=parser_version,
        parser_config={
            "pipeline": "standard",
            "device": "cpu",
            "ocr": True,
            "table_structure": True,
            "table_mode": "accurate",
            "remote_services": False,
        },
        parse_seconds=parse_seconds,
        parse_status="parsed",
        text_items=text_items,
        tables=tables,
        picture_count=len(exported.get("pictures", [])),
        warnings=warnings,
    )


def parse_object(converter: Any, inventory_row: dict[str, Any]) -> DoclingVisualObjectV12:
    crop = ROOT / inventory_row["crop_path"]
    started = time.monotonic()
    result = converter.convert(crop, raises_on_error=True)
    elapsed = time.monotonic() - started
    return normalize_docling(
        inventory_row,
        result.document.export_to_dict(),
        parser_version=importlib.metadata.version("docling"),
        parse_seconds=elapsed,
    )


def build_converter() -> Any:
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption

    options = PdfPipelineOptions(
        accelerator_options=AcceleratorOptions(
            num_threads=4, device=AcceleratorDevice.CPU
        ),
        enable_remote_services=False,
        allow_external_plugins=False,
        do_ocr=True,
        do_table_structure=True,
    )
    return DocumentConverter(format_options={
        InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)
    })


def run(object_ids: set[str]) -> dict[str, Any]:
    rows = json.loads(INVENTORY.read_text(encoding="utf-8"))
    selected = [row for row in rows if row["object_id"] in object_ids]
    found = {row["object_id"] for row in selected}
    missing = sorted(object_ids - found)
    if missing:
        raise ValueError(f"object ids not in inventory: {missing}")
    converter = build_converter()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "contract_version": "1.0.0",
        "parser": "docling",
        "parser_version": importlib.metadata.version("docling"),
        "local_only": True,
        "remote_services_enabled": False,
        "objects": [],
    }
    for row in sorted(selected, key=lambda item: item["object_id"]):
        normalized = parse_object(converter, row)
        object_dir = OUTPUT / normalized.object_id
        object_dir.mkdir(parents=True, exist_ok=True)
        output_path = object_dir / "docling_object.json"
        output_path.write_text(normalized.model_dump_json(indent=2) + "\n")
        manifest["objects"].append({
            "object_id": normalized.object_id,
            "paper_id": normalized.paper_id,
            "source_file": normalized.source_file,
            "original_page": normalized.original_page,
            "figure_or_table": normalized.figure_or_table,
            "output_path": str(output_path.relative_to(ROOT)),
            "tables": len(normalized.tables),
            "text_items": len(normalized.text_items),
            "warnings": normalized.warnings,
            "parse_seconds": normalized.parse_seconds,
        })
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(run(set(args.object_id)), indent=2, ensure_ascii=False))
