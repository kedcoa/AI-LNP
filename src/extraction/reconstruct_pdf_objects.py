"""Reconstruct figure/table objects, captions, coordinates, and review crops."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import fitz

from .pdf_multimodal_contracts import BoundingBox, ReconstructedDocumentObject
from .run_abstract_first import ROOT
from .run_day8_pdf import RAW_ROOT, paper_id_by_pmcid


OUTPUT = ROOT / "data/staging/extraction/day8_object_vision"
CAPTION_RE = re.compile(
    r"^\s*(?:\d+\s+)?(?P<kind>fig(?:ure)?|table|appendix\s+fig(?:ure)?|appendix\s+table)"
    r"\s*\.?\s*(?P<label>[A-Za-z0-9][A-Za-z0-9.-]*)",
    re.I,
)


def is_caption_candidate(text: str, match: re.Match[str]) -> bool:
    """Separate real captions from in-text blocks that begin with figure references."""
    remainder = text[match.end():].lstrip()
    explicit_separator = match.group("label").endswith(".") or remainder.startswith(".")
    another_reference_near_start = re.search(
        r"\b(?:fig(?:ure)?|table)\s*\.?\s*[A-Za-z0-9]",
        remainder[:90],
        re.I,
    )
    long_caption_without_separator = len(text) >= 120 and not another_reference_near_start
    return explicit_separator or long_caption_without_separator


def expanded(rect: fitz.Rect, page_rect: fitz.Rect, margin: float = 10) -> fitz.Rect:
    return fitz.Rect(
        max(page_rect.x0, rect.x0 - margin),
        max(page_rect.y0, rect.y0 - margin),
        min(page_rect.x1, rect.x1 + margin),
        min(page_rect.y1, rect.y1 + margin),
    )


def render(page: fitz.Page, rect: fitz.Rect, path: Path, zoom: float = 4.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
    pix.save(path)


def reconstruct_file(
    path: Path, paper_id: str, output_root: Path = OUTPUT
) -> list[ReconstructedDocumentObject]:
    doc = fitz.open(path)
    source_file = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    objects: list[ReconstructedDocumentObject] = []
    crop_dir = output_root / "crops" / paper_id / path.stem
    page_dir = output_root / "pages" / paper_id / path.stem
    for page_index, page in enumerate(doc):
        blocks = sorted(page.get_text("blocks"), key=lambda row: (row[1], row[0]))
        image_boxes = [fitz.Rect(info["bbox"]) for info in page.get_image_info(xrefs=True)]
        captions = []
        for block in blocks:
            text = " ".join(str(block[4]).split())
            match = CAPTION_RE.match(text)
            if match and is_caption_candidate(text, match):
                captions.append((fitz.Rect(block[:4]), text, match))
        if not captions:
            continue
        page_path = page_dir / f"page-{page_index + 1:03d}.png"
        render(page, page.rect, page_path, zoom=2.0)
        for caption_index, (caption_rect, caption, match) in enumerate(captions, 1):
            if (
                caption_rect.y0 > page.rect.height * 0.72
                and page_index + 1 < len(doc)
                and not caption.rstrip().endswith((".", "?", "!"))
            ):
                next_blocks = sorted(
                    doc[page_index + 1].get_text("blocks"),
                    key=lambda row: (row[1], row[0]),
                )
                continuation: list[str] = []
                for next_block in next_blocks:
                    next_text = " ".join(str(next_block[4]).split())
                    if CAPTION_RE.match(next_text):
                        break
                    continuation.append(next_text)
                    if next_block[3] > doc[page_index + 1].rect.height * 0.45:
                        break
                if continuation:
                    caption = f"{caption} {' '.join(continuation)}"
            kind = "table" if "table" in match.group("kind").lower() else "figure"
            label = f"{match.group('kind').title()} {match.group('label')}"
            if kind == "table":
                candidates = [
                    rect for rect in image_boxes
                    if rect.y0 >= caption_rect.y0 - 25 and rect.y0 - caption_rect.y1 < 520
                ]
            else:
                candidates = [
                    rect for rect in image_boxes
                    if rect.y1 <= caption_rect.y1 + 25 and caption_rect.y0 - rect.y1 < 520
                ]
            if candidates:
                if kind == "table":
                    nearest_y = min(rect.y0 for rect in candidates)
                    chosen = [rect for rect in candidates if rect.y0 - nearest_y < 80]
                else:
                    nearest_y = max(rect.y1 for rect in candidates)
                    chosen = [rect for rect in candidates if nearest_y - rect.y1 < 80]
                object_rect = chosen[0]
                for rect in chosen[1:]:
                    object_rect |= rect
                object_rect |= caption_rect
                method = "caption_image_association"
            else:
                prior_bottom = (
                    captions[caption_index - 2][0].y1 + 5 if caption_index > 1 else page.rect.y0
                )
                object_rect = fitz.Rect(
                    page.rect.x0, max(page.rect.y0, prior_bottom),
                    page.rect.x1, min(page.rect.y1, caption_rect.y1 + 8),
                )
                method = "caption_page_region"
            object_rect = expanded(object_rect, page.rect, 12)
            context_rect = expanded(caption_rect, page.rect, 40)
            surrounding = page.get_text("text", clip=context_rect).strip()
            object_id = (
                f"{paper_id}-{path.stem}-p{page_index + 1:03d}-"
                f"{kind}-{caption_index:02d}"
            )
            crop_path = crop_dir / f"{object_id}.png"
            render(page, object_rect, crop_path)
            objects.append(ReconstructedDocumentObject(
                object_id=object_id,
                paper_id=paper_id,
                source_file=source_file,
                page=page_index + 1,
                object_type=kind,
                label=label,
                caption=caption,
                surrounding_text=surrounding,
                bbox=BoundingBox(
                    x0=object_rect.x0, y0=object_rect.y0,
                    x1=object_rect.x1, y1=object_rect.y1,
                ),
                crop_path=str(crop_path.relative_to(ROOT) if crop_path.is_relative_to(ROOT) else crop_path),
                page_image_path=str(page_path.relative_to(ROOT) if page_path.is_relative_to(ROOT) else page_path),
                detection_method=method,
                embedded_image_count=len(image_boxes),
            ))
    return objects


def run(paper_ids: set[str] | None = None) -> dict:
    mapping = paper_id_by_pmcid()
    objects: list[ReconstructedDocumentObject] = []
    files = 0
    for path in sorted(RAW_ROOT.glob("PMC*/*.pdf")):
        paper_id = mapping.get(path.parent.name)
        if not paper_id or (paper_ids and paper_id not in paper_ids):
            continue
        files += 1
        objects.extend(reconstruct_file(path, paper_id))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "object_inventory.json").write_text(
        json.dumps([row.model_dump(mode="json") for row in objects], indent=2, ensure_ascii=False) + "\n"
    )
    manifest = {
        "files_processed": files,
        "objects_detected": len(objects),
        "figures": sum(row.object_type == "figure" for row in objects),
        "tables": sum(row.object_type == "table" for row in objects),
        "paper_ids": sorted({row.paper_id for row in objects}),
    }
    (OUTPUT / "reconstruction_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    args = parser.parse_args()
    print(json.dumps(run(set(args.paper_id) if args.paper_id else None), indent=2))
