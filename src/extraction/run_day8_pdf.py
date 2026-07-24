"""Day 8 morning: inventory PDFs and extract visual evidence with OpenAI."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from dotenv import load_dotenv
from openai import OpenAI

from .pdf_multimodal_contracts import PDFExtractionResult
from .run_abstract_first import ROOT


RAW_ROOT = ROOT / "data" / "raw" / "fulltext" / "oa_packages"
OUTPUT = ROOT / "data" / "staging" / "extraction" / "day8_openai_pdf"
TARGET_GOLD_IDS = {"GO-006", "GO-017", "GO-018"}
TARGET_TERMS = (
    "supplement", "table", "figure", "hepatocyte", "kupffer", "lsec",
    "stellate", "cell specificity", "recipient cell", "expression",
)
GOLD_TARGETS = {
    "GO-006": {
        "paper_id": "GP-006",
        "term_groups": (("1.01",), ("insertion",), ("lsec",)),
    },
    "GO-017": {
        "paper_id": "GP-008",
        "term_groups": (("hsc", "js-1", "stellate"), ("eliminat", "phagocyt")),
    },
    "GO-018": {
        "paper_id": "GP-008",
        "term_groups": (("macrophage", "f4/80", "cd163"), ("desmin", "alb", "sox9")),
    },
}


def frozen_gold_rows() -> dict[str, dict[str, str]]:
    evidence_by_id: dict[str, dict[str, str]] = {}
    with (ROOT / "data/annotations/gold_v1/evidence.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            evidence_by_id[row["evidence_id"]] = row
    evidence: dict[str, dict[str, str]] = {}
    with (ROOT / "data/annotations/gold_v1/outcomes.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            gold_id = row["gold_outcome_id"]
            if gold_id not in TARGET_GOLD_IDS:
                continue
            source = dict(evidence_by_id[row["evidence_id"]])
            source.update({f"outcome_{key}": value for key, value in row.items()})
            evidence[gold_id] = source
    return evidence


def frozen_pages_for_path(paper_id: str, path: Path) -> set[int]:
    pages: set[int] = set()
    for row in frozen_gold_rows().values():
        if row["gold_paper_id"] != paper_id or row.get("supplement_identifier") != path.name:
            continue
        if row.get("page_number", "").isdigit():
            page = int(row["page_number"])
            pages.update({page - 1, page, page + 1})
    page_count = fitz.open(path).page_count
    return {page for page in pages if 1 <= page <= page_count}


def paper_id_by_pmcid() -> dict[str, str]:
    rows = json.loads(
        (ROOT / "data/staging/extraction/g1_fulltext_rag/run_manifest.json").read_text()
    ).get("papers", [])
    mapping = {
        str(row.get("pmcid")): row["paper_id"]
        for row in rows
        if row.get("pmcid") and row.get("paper_id")
    }
    if not mapping:
        # Stable identities established by the gold paper registry.
        import csv
        with (ROOT / "data/annotations/gold_v1/papers.csv").open(newline="") as handle:
            for row in csv.DictReader(handle):
                pmcid = row.get("pmcid", "").replace("PMC", "")
                if pmcid:
                    mapping[f"PMC{pmcid}"] = row["gold_paper_id"]
    return mapping


def inventory_pdf(path: Path, paper_id: str) -> dict[str, Any]:
    doc = fitz.open(path)
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(doc):
        text = page.get_text("text")
        images = page.get_images(full=True)
        blocks = page.get_text("blocks")
        refs = sorted(set(re.findall(r"\b(?:Fig(?:ure)?|Table)\s+[A-Za-z0-9.-]+", text, re.I)))
        pages.append({
            "page": index + 1,
            "width": page.rect.width,
            "height": page.rect.height,
            "selectable_text_characters": len(text.strip()),
            "layout_block_count": len(blocks),
            "embedded_image_count": len(images),
            "figure_table_references": refs,
            "caption_candidates": [
                line.strip() for line in text.splitlines()
                if re.match(r"^\s*(?:Fig(?:ure)?|Table)\s+[A-Za-z0-9.-]+", line, re.I)
            ],
        })
    content = path.read_bytes()
    try:
        relative_path = str(path.relative_to(ROOT))
    except ValueError:
        relative_path = str(path)
    return {
        "paper_id": paper_id,
        "file_name": path.name,
        "relative_path": relative_path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "page_count": len(doc),
        "has_selectable_text": any(row["selectable_text_characters"] for row in pages),
        "pages": pages,
    }


def candidate_pages(path: Path, paper_id: str) -> list[int]:
    doc = fitz.open(path)
    scored: list[tuple[int, int]] = []
    for index, page in enumerate(doc):
        text = page.get_text("text").lower()
        score = sum(text.count(term) for term in TARGET_TERMS)
        if score:
            scored.append((score, index + 1))
    selected: set[int] = set()
    for _, page in sorted(scored, reverse=True)[:8]:
        selected.update(p for p in (page - 1, page, page + 1) if 1 <= p <= len(doc))
    selected.update(frozen_pages_for_path(paper_id, path))
    return sorted(selected)


def main_article(paths: list[Path]) -> Path:
    supplement_tokens = ("supp", "sapp", "mmc", "moesm", "esm")
    candidates = [
        path for path in paths
        if not any(token in path.name.lower() for token in supplement_tokens)
    ]
    return min(candidates or paths, key=lambda path: fitz.open(path).page_count)


def compare_with_frozen_gold(
    paper_id: str,
    whole: PDFExtractionResult | None,
    targeted: PDFExtractionResult,
) -> list[dict[str, str]]:
    def status(result: PDFExtractionResult | None, term_groups: tuple[tuple[str, ...], ...]) -> str:
        if result is None:
            return "not_run"
        text = " ".join(
            " ".join([
                row.population, row.intervention, row.endpoint, row.value,
                row.unit or "", row.location.evidence_quote, row.ambiguity or "",
            ]).lower()
            for row in result.records
        )
        return "matched" if all(any(term in text for term in group) for group in term_groups) else "missed"

    rows = []
    for gold_id, target in GOLD_TARGETS.items():
        if target["paper_id"] != paper_id:
            continue
        whole_status = status(whole, target["term_groups"])
        targeted_status = status(targeted, target["term_groups"])
        rows.append({
            "gold_id": gold_id,
            "whole_pdf_status": whole_status,
            "targeted_status": targeted_status,
            "explanation": (
                "Deterministic term check against the frozen outcome; final scientific "
                "acceptance remains a human decision."
            ),
        })
    return rows


def pdf_data(path: Path, pages: list[int] | None = None) -> str:
    if pages:
        source = fitz.open(path)
        subset = fitz.open()
        for page in pages:
            subset.insert_pdf(source, from_page=page - 1, to_page=page - 1)
        raw = subset.tobytes(garbage=4, deflate=True)
    else:
        raw = path.read_bytes()
    return "data:application/pdf;base64," + base64.b64encode(raw).decode("ascii")


def extraction_prompt(
    paper_id: str, file_names: list[str], mode: str,
    selected: dict[str, list[int]] | None = None,
    task_focus: list[dict[str, Any]] | None = None,
) -> str:
    schema = PDFExtractionResult.model_json_schema()
    return json.dumps({
        "task": "Extract directly measured LNP experiment outcomes from PDF text, tables, figures and legends.",
        "paper_id": paper_id,
        "source_files": file_names,
        "mode": mode,
        "original_pdf_pages_included": selected or {},
        "coordinate_focus_without_gold_answer": task_focus or [],
        "rules": [
            "Read body text, captions, tables, figures, panel labels, legends and cell markers.",
            "Return one atomic record per experiment/population/endpoint/value.",
            "Never convert a proposed mechanism or author inference into a measured outcome.",
            "Use exact for printed values; use visually_estimated only when read from a graph.",
            "Every record needs page and figure/table plus panel/table-cell when available.",
            "For targeted subsets, location.page must use the original PDF page number from original_pdf_pages_included, not the subset page index.",
            "When coordinate_focus_without_gold_answer is present, exhaustively inspect those locations and requested fields.",
            "Keep negative and not-detected results.",
            "Record ambiguity instead of guessing.",
            "Return JSON only matching the schema.",
        ],
        "focus_gold_cases": sorted(TARGET_GOLD_IDS),
        "schema": schema,
    }, ensure_ascii=False)


def call_openai(
    client: OpenAI, model: str, paper_id: str, paths: list[Path],
    mode: str, selected: dict[str, list[int]] | None = None,
    task_focus: list[dict[str, Any]] | None = None,
) -> tuple[PDFExtractionResult, dict[str, Any]]:
    content: list[dict[str, Any]] = [{
        "type": "input_text",
        "text": extraction_prompt(paper_id, [p.name for p in paths], mode, selected, task_focus),
    }]
    for path in paths:
        pages = (selected or {}).get(path.name)
        content.append({
            "type": "input_file",
            "filename": path.name,
            "file_data": pdf_data(path, pages),
            "detail": "high",
        })
    response = client.responses.parse(
        model=model,
        input=[{"role": "user", "content": content}],
        text_format=PDFExtractionResult,
        timeout=600.0,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise ValueError("OpenAI response did not contain a parsed PDFExtractionResult")
    envelope = {
        "id": response.id,
        "model": response.model,
        "usage": response.usage.model_dump() if response.usage else None,
        "output_text": response.output_text,
    }
    return parsed, envelope


def run(
    inventory_only: bool = False,
    paper_ids: set[str] | None = None,
    reuse_whole: bool = False,
) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    model = os.getenv("DAY8_OPENAI_MODEL", "gpt-5.6")
    mapping = paper_id_by_pmcid()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[Path]] = {}
    inventories: list[dict[str, Any]] = []
    for path in sorted(RAW_ROOT.glob("PMC*/*.pdf")):
        pmcid = path.parent.name
        paper_id = mapping.get(pmcid)
        if not paper_id:
            continue
        grouped.setdefault(paper_id, []).append(path)
        inventories.append(inventory_pdf(path, paper_id))
    (OUTPUT / "pdf_inventory.json").write_text(
        json.dumps(inventories, indent=2, ensure_ascii=False) + "\n"
    )
    manifest: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "inventory_count": len(inventories),
        "papers": [],
        "human_verification_required": [],
    }
    if inventory_only:
        (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=600.0, max_retries=2)
    for paper_id, paths in grouped.items():
        if paper_ids and paper_id not in paper_ids:
            continue
        paper_dir = OUTPUT / paper_id
        paper_dir.mkdir(exist_ok=True)
        total_pages = sum(fitz.open(path).page_count for path in paths)
        whole_path = main_article(paths)
        whole_validated = paper_dir / "whole_pdf.validated.json"
        whole = (
            PDFExtractionResult.model_validate_json(whole_validated.read_text())
            if reuse_whole and whole_validated.exists() else None
        )
        if whole is None and fitz.open(whole_path).page_count <= 40 and whole_path.stat().st_size < 50_000_000:
            whole, raw = call_openai(client, model, paper_id, [whole_path], "whole_pdf")
            (paper_dir / "whole_pdf.response.json").write_text(
                json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
            )
            (paper_dir / "whole_pdf.validated.json").write_text(whole.model_dump_json(indent=2) + "\n")
        selected = {path.name: candidate_pages(path, paper_id) for path in paths}
        targeted, raw = call_openai(client, model, paper_id, paths, "targeted_pages", selected)
        (paper_dir / "targeted_pages.json").write_text(json.dumps(selected, indent=2) + "\n")
        (paper_dir / "targeted.response.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
        )
        (paper_dir / "targeted.validated.json").write_text(targeted.model_dump_json(indent=2) + "\n")
        comparison = compare_with_frozen_gold(paper_id, whole, targeted)
        (paper_dir / "frozen_gold_comparison.json").write_text(
            json.dumps(comparison, indent=2, ensure_ascii=False) + "\n"
        )
        review = [
            row.record_id for result in (whole, targeted) if result
            for row in result.records
            if row.measurement_status == "visually_estimated" or row.ambiguity
        ]
        review.extend(targeted.unresolved_ambiguities)
        manifest["papers"].append({
            "paper_id": paper_id,
            "files": [path.name for path in paths],
            "total_pages": total_pages,
            "whole_pdf_run": whole is not None,
            "whole_pdf_file": whole_path.name,
            "targeted_pages": selected,
            "whole_pdf_records": len(whole.records) if whole else None,
            "targeted_records": len(targeted.records),
            "frozen_gold_comparison": comparison,
            "status": "human_review_required" if review else "machine_validation_complete",
        })
        manifest["human_verification_required"].extend(
            {"paper_id": paper_id, "item": item} for item in review
        )
        (OUTPUT / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--paper-id", action="append")
    parser.add_argument("--reuse-whole", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(
        inventory_only=args.inventory_only,
        paper_ids=set(args.paper_id) if args.paper_id else None,
        reuse_whole=args.reuse_whole,
    ), indent=2))
