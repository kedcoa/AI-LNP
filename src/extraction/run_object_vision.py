"""Interpret reconstructed figure/table crops with strict source-aware policies."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .pdf_multimodal_contracts import ObjectVisionExtraction, ReconstructedDocumentObject
from .reconstruct_pdf_objects import OUTPUT
from .run_abstract_first import ROOT


DEFAULT_QUERY = (
    "LNP delivery, recipient cell, macrophage, hepatocyte, LSEC, HSC, "
    "expression, phagocytosis, gene editing, insertion, deletion"
)


def image_data(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def query_terms(query: str) -> set[str]:
    return {
        token.lower() for token in re.findall(r"[A-Za-z0-9+/-]{3,}", query)
        if token.lower() not in {"and", "the", "with", "from"}
    }


def rank_object(row: ReconstructedDocumentObject, terms: set[str]) -> int:
    text = f"{row.label} {row.caption} {row.surrounding_text}".lower()
    return sum(term in text for term in terms)


def prompt(row: ReconstructedDocumentObject, query: str) -> str:
    return json.dumps({
        "task": "Extract only scientifically supported facts from this reconstructed figure/table crop.",
        "scientific_query": query,
        "source": {
            "object_id": row.object_id,
            "file": row.source_file,
            "page": row.page,
            "label": row.label,
            "caption": row.caption,
            "surrounding_text": row.surrounding_text,
            "bbox": row.bbox.model_dump(),
        },
        "rules": [
            "First transcribe every readable printed panel label into raw_panel_labels, including Q1-Q4 for every flow-cytometry plot, even when a quadrant is not the primary endpoint.",
            "Keep raw transcription separate from scientific relevance: printed_facts may select relevant labels, but raw_panel_labels must preserve all readable labels.",
            "A numeric fact is allowed only when the number is visibly printed in the crop, caption, or supplied surrounding text.",
            "For tables, preserve row header, column header, and their intersecting cell in visible_support.",
            "For an unlabeled bar, curve, or point, return a qualitative comparison and do not estimate a number.",
            "Never convert axis position into an exact reported measurement.",
            "If a potential estimate is visible but not printed, put it only in excluded_estimates with estimated_value null.",
            "Do not treat related panels or nearby experiments as the target outcome.",
            "If labels, panels, or group mappings cannot be read, mark human_review_required or unreadable.",
            "Use visible_support as a short transcription of actually visible labels/text, not a synthesized claim.",
        ],
    }, ensure_ascii=False)


def audit(result: ObjectVisionExtraction) -> list[str]:
    issues: list[str] = []
    for fact in result.printed_facts:
        if fact.support_kind == "axis_tick":
            issues.append(f"{fact.fact_id}: axis tick alone cannot support a measured value")
    flow_panels: dict[tuple[str, str], set[str]] = {}
    for label in result.raw_panel_labels:
        if label.label_type != "quadrant":
            continue
        key = (label.panel, label.group or "")
        flow_panels.setdefault(key, set()).add(label.label.upper())
    for (panel, group), labels in flow_panels.items():
        missing = {"Q1", "Q2", "Q3", "Q4"} - labels
        if missing:
            issues.append(
                f"{panel}/{group}: incomplete quadrant transcription; missing {sorted(missing)}"
            )
    if result.excluded_estimates and result.acceptance_status == "machine_readable":
        issues.append("excluded estimates require qualitative_only or human_review_required")
    return issues


def analyze(client: OpenAI, model: str, row: ReconstructedDocumentObject, query: str):
    crop = ROOT / row.crop_path
    response = client.responses.parse(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt(row, query)},
                {"type": "input_image", "image_url": image_data(crop), "detail": "original"},
            ],
        }],
        text_format=ObjectVisionExtraction,
        timeout=300.0,
    )
    if response.output_parsed is None:
        raise ValueError("OpenAI returned no parsed object extraction")
    return response.output_parsed, {
        "id": response.id,
        "model": response.model,
        "usage": response.usage.model_dump() if response.usage else None,
        "output_text": response.output_text,
    }


def run(
    paper_ids: set[str] | None,
    query: str,
    max_objects: int,
    object_ids: set[str] | None = None,
    all_objects: bool = False,
    reuse_existing: bool = False,
    workers: int = 4,
) -> dict:
    load_dotenv(ROOT / ".env")
    model = os.getenv("DAY8_OPENAI_MODEL", "gpt-5.6")
    rows = [
        ReconstructedDocumentObject.model_validate(row)
        for row in json.loads((OUTPUT / "object_inventory.json").read_text())
    ]
    if paper_ids:
        rows = [row for row in rows if row.paper_id in paper_ids]
    if object_ids:
        rows = [row for row in rows if row.object_id in object_ids]
    terms = query_terms(query)
    ranked = sorted(
        ((rank_object(row, terms), row) for row in rows),
        key=lambda item: (item[0], item[1].object_id),
        reverse=True,
    )
    selected = (
        [row for _, row in ranked]
        if all_objects
        else [row for score, row in ranked if object_ids or score > 0][:max_objects]
    )
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=300.0, max_retries=2)
    result_dir = OUTPUT / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "model": model,
        "query": query,
        "selection_mode": "all_objects" if all_objects else "ranked",
        "inventory_objects": len(rows),
        "selected_objects": len(selected),
        "objects": [],
    }
    def process(row: ReconstructedDocumentObject) -> dict:
        validated_path = result_dir / f"{row.object_id}.validated.json"
        corrected_path = result_dir / f"{row.object_id}.human_corrected.json"
        cached_path = corrected_path if corrected_path.exists() else validated_path
        cache_hit = reuse_existing and cached_path.exists()
        if cache_hit:
            result = ObjectVisionExtraction.model_validate_json(cached_path.read_text())
            raw = None
        else:
            result, raw = analyze(client, model, row, query)
        issues = audit(result)
        if raw is not None:
            (result_dir / f"{row.object_id}.response.json").write_text(
                json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
            )
            validated_path.write_text(result.model_dump_json(indent=2) + "\n")
        return {
            "object_id": row.object_id,
            "paper_id": row.paper_id,
            "source_file": row.source_file,
            "page": row.page,
            "label": row.label,
            "crop_path": row.crop_path,
            "printed_facts": len(result.printed_facts),
            "raw_panel_labels": len(result.raw_panel_labels),
            "qualitative_comparisons": len(result.qualitative_comparisons),
            "excluded_estimates": len(result.excluded_estimates),
            "audit_issues": issues,
            "cache_hit": cache_hit,
            "status": (
                "rejected_by_audit"
                if any("axis tick alone" in issue for issue in issues)
                else "human_review_required"
                if issues
                else result.acceptance_status
            ),
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process, row): row for row in selected}
        for future in as_completed(futures):
            manifest["objects"].append(future.result())
            manifest["objects"].sort(key=lambda item: item["object_id"])
        (OUTPUT / "object_vision_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max-objects", type=int, default=12)
    parser.add_argument("--object-id", action="append")
    parser.add_argument("--all-objects", action="store_true")
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(run(
        set(args.paper_id) if args.paper_id else None,
        args.query,
        args.max_objects,
        set(args.object_id) if args.object_id else None,
        args.all_objects,
        args.reuse_existing,
        args.workers,
    ), indent=2, ensure_ascii=False))
