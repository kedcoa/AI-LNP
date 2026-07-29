"""Build query/panel-focused crops from Docling OCR coordinates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .benchmark_v12_gemma_visual import required_query_anchors
from .v12_visual_contracts import DoclingVisualObjectV12


ROOT = Path(__file__).resolve().parents[2]
DOCLING_ROOT = ROOT / "data/staging/extraction/v12_docling_visual"


def compute_focus_bbox(
    parsed: DoclingVisualObjectV12,
    query: str,
    panel_labels: set[str],
    width: int,
    height: int,
    padding: int = 60,
) -> tuple[int, int, int, int]:
    anchors = required_query_anchors(query)
    variants = {
        variant
        for group in anchors.values()
        for variant in group
    }
    candidates: list[tuple[tuple[float, float, float, float], bool]] = []
    for item in parsed.text_items:
        if item.bbox is None or item.label == "caption" or len(item.text) > 120:
            continue
        lowered = item.text.lower()
        is_panel = item.text.strip().upper() in panel_labels
        is_anchor = any(variant in lowered for variant in variants)
        if not (is_panel or is_anchor):
            continue
        box = item.bbox
        if box.coord_origin.upper() == "BOTTOMLEFT":
            top = height - box.top
            bottom = height - box.bottom
        else:
            top = box.top
            bottom = box.bottom
        candidates.append(((box.left, top, box.right, bottom), is_panel))
    panel_boxes = [box for box, is_panel in candidates if is_panel]
    if panel_boxes:
        panel_left = min(box[0] for box in panel_boxes)
        panel_top = min(box[1] for box in panel_boxes)
        panel_bottom = max(box[3] for box in panel_boxes)
        boxes = [
            box
            for box, is_panel in candidates
            if is_panel or (
                (box[0] + box[2]) / 2 >= panel_left - 150
                and (box[1] + box[3]) / 2 >= panel_top - 150
                and (box[1] + box[3]) / 2 <= panel_bottom + 550
            )
        ]
    else:
        boxes = [box for box, _ in candidates]
    if not boxes:
        raise ValueError("no Docling OCR boxes matched the query or panel labels")
    left = max(0, int(min(box[0] for box in boxes) - padding))
    top = max(0, int(min(box[1] for box in boxes) - padding))
    right = min(width, int(max(box[2] for box in boxes) + padding))
    bottom = min(height, int(max(box[3] for box in boxes) + padding))
    if right <= left or bottom <= top:
        raise ValueError("computed focus crop is empty")
    return left, top, right, bottom


def run(
    object_id: str,
    output_name: str,
    query: str,
    panel_labels: set[str],
    padding: int,
) -> dict[str, Any]:
    from PIL import Image

    object_dir = DOCLING_ROOT / object_id
    parsed = DoclingVisualObjectV12.model_validate_json(
        (object_dir / "docling_object.json").read_text()
    )
    source = ROOT / parsed.source_crop
    with Image.open(source) as image:
        bbox = compute_focus_bbox(
            parsed, query, panel_labels, image.width, image.height, padding
        )
        focused = image.crop(bbox)
        focus_dir = object_dir / "focus"
        focus_dir.mkdir(parents=True, exist_ok=True)
        output_path = focus_dir / f"{output_name}.png"
        focused.save(output_path)
        width, height = focused.size
    metadata = {
        "contract_version": "1.0.0",
        "object_id": object_id,
        "paper_id": parsed.paper_id,
        "source_file": parsed.source_file,
        "original_page": parsed.original_page,
        "parent_crop": parsed.source_crop,
        "parent_crop_sha256": parsed.source_crop_sha256,
        "focus_crop": str(output_path.relative_to(ROOT)),
        "focus_crop_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "focus_bbox_parent_pixels": {
            "left": bbox[0],
            "top": bbox[1],
            "right": bbox[2],
            "bottom": bbox[3],
        },
        "focus_width": width,
        "focus_height": height,
        "query": query,
        "panel_labels": sorted(panel_labels),
        "selection_method": "docling_ocr_anchor_union_with_padding",
        "padding_pixels": padding,
    }
    metadata_path = output_path.with_suffix(".json")
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    )
    return metadata


def stack_regions(
    source_path: Path,
    output_path: Path,
    regions: list[tuple[int, int, int, int]],
) -> dict[str, Any]:
    """Stack disjoint panel regions without rescaling or interpreting pixels."""

    from PIL import Image

    if not regions:
        raise ValueError("at least one stack region is required")
    source = ROOT / source_path
    with Image.open(source) as image:
        crops = []
        for left, top, right, bottom in regions:
            if not (0 <= left < right <= image.width):
                raise ValueError(f"invalid horizontal region: {(left, right)}")
            if not (0 <= top < bottom <= image.height):
                raise ValueError(f"invalid vertical region: {(top, bottom)}")
            crops.append(image.crop((left, top, right, bottom)))
        width = max(crop.width for crop in crops)
        height = sum(crop.height for crop in crops)
        stacked = Image.new("RGB", (width, height), "white")
        offset = 0
        for crop in crops:
            stacked.paste(crop, (0, offset))
            offset += crop.height
        output = ROOT / output_path
        output.parent.mkdir(parents=True, exist_ok=True)
        stacked.save(output)
    metadata = {
        "contract_version": "1.0.0",
        "source_image": str(source_path),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "focus_crop": str(output_path),
        "focus_crop_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "regions_source_pixels": [
            {"left": l, "top": t, "right": r, "bottom": b}
            for l, t, r, b in regions
        ],
        "focus_width": width,
        "focus_height": height,
        "selection_method": "manual_panel_bounds_stacked_without_rescaling",
    }
    output.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    )
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", required=True)
    parser.add_argument("--output-name", required=True)
    parser.add_argument("--query")
    parser.add_argument("--panel-label", action="append", default=[])
    parser.add_argument("--padding", type=int, default=60)
    parser.add_argument(
        "--stack-region",
        action="append",
        help="Optional left,top,right,bottom box; repeat to stack focused regions.",
    )
    parser.add_argument(
        "--source-image",
        type=Path,
        help="Repo-relative source image used with --stack-region.",
    )
    args = parser.parse_args()
    if args.stack_region:
        if args.source_image is None:
            parser.error("--source-image is required with --stack-region")
        regions = [
            tuple(int(value) for value in row.split(","))
            for row in args.stack_region
        ]
        if any(len(row) != 4 for row in regions):
            parser.error("--stack-region requires left,top,right,bottom")
        output_path = (
            DOCLING_ROOT
            / args.object_id
            / "focus"
            / f"{args.output_name}.png"
        ).relative_to(ROOT)
        print(json.dumps(
            stack_regions(args.source_image, output_path, regions),
            indent=2,
            ensure_ascii=False,
        ))
        raise SystemExit(0)
    if not args.query:
        parser.error("--query is required unless --stack-region is used")
    print(json.dumps(run(
        args.object_id,
        args.output_name,
        args.query,
        {label.upper() for label in args.panel_label},
        args.padding,
    ), indent=2, ensure_ascii=False))
