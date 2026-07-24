"""Retry genuine Day 8 semantic misses at frozen source coordinates, without gold answers."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from .run_abstract_first import ROOT
from .run_day8_pdf import (
    GOLD_TARGETS,
    OUTPUT,
    PDFExtractionResult,
    RAW_ROOT,
    call_openai,
    compare_with_frozen_gold,
    frozen_gold_rows,
    paper_id_by_pmcid,
)


def run(paper_id: str = "GP-008") -> dict:
    load_dotenv(ROOT / ".env")
    model = os.getenv("DAY8_OPENAI_MODEL", "gpt-5.6")
    mapping = paper_id_by_pmcid()
    pmcid = next(pmcid for pmcid, mapped in mapping.items() if mapped == paper_id)
    paths = sorted((RAW_ROOT / pmcid).glob("*.pdf"))
    paper_dir = OUTPUT / paper_id
    comparison = json.loads((paper_dir / "frozen_gold_comparison.json").read_text())
    missed_ids = [row["gold_id"] for row in comparison if row["targeted_status"] == "missed"]
    gold = frozen_gold_rows()
    selected: dict[str, list[int]] = {}
    focus: list[dict] = []
    for gold_id in missed_ids:
        row = gold[gold_id]
        source_file = row.get("supplement_identifier")
        page = int(row["page_number"]) if row.get("page_number", "").isdigit() else None
        if not source_file or not page:
            continue
        selected.setdefault(source_file, [])
        selected[source_file].extend([max(1, page - 1), page, page + 1])
        focus.append({
            "case_id": gold_id,
            "source_file": source_file,
            "original_pages": [max(1, page - 1), page, page + 1],
            "figure_or_table": row.get("figure_number") or row.get("table_number"),
            "requested_field": row["field_name"],
            "instruction": (
                "Determine the directly supported population/intervention/endpoint/value "
                "from the cited visual panels and marker labels; do not infer beyond them."
            ),
        })
    selected = {name: sorted(set(pages)) for name, pages in selected.items()}
    focused_paths = [path for path in paths if path.name in selected]
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=600.0, max_retries=2)
    result, raw = call_openai(
        client, model, paper_id, focused_paths, "coordinate_focused_miss_retry",
        selected=selected, task_focus=focus,
    )
    (paper_dir / "focused_misses.response.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
    )
    (paper_dir / "focused_misses.validated.json").write_text(result.model_dump_json(indent=2) + "\n")
    whole = PDFExtractionResult.model_validate_json((paper_dir / "whole_pdf.validated.json").read_text())
    focused_comparison = [
        row for row in compare_with_frozen_gold(paper_id, whole, result)
        if row["gold_id"] in missed_ids
    ]
    (paper_dir / "focused_gold_comparison.json").write_text(
        json.dumps(focused_comparison, indent=2, ensure_ascii=False) + "\n"
    )
    summary = {
        "paper_id": paper_id,
        "model": model,
        "missed_ids_retried": missed_ids,
        "selected_pages": selected,
        "focus": focus,
        "record_count": len(result.records),
        "comparison": focused_comparison,
        "status": "human_review_required",
    }
    (paper_dir / "focused_misses_manifest.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
