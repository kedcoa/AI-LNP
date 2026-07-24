"""Build a small, readable review packet for the three Day 8 gold outcomes."""

from __future__ import annotations

import json
from pathlib import Path

from .run_abstract_first import ROOT
from .run_day8_pdf import GOLD_TARGETS, OUTPUT, frozen_gold_rows


def record_text(row: dict) -> str:
    location = row.get("location", {})
    return " ".join(str(value or "") for value in (
        row.get("population"), row.get("intervention"), row.get("endpoint"),
        row.get("value"), row.get("unit"), location.get("evidence_quote"),
        row.get("ambiguity"),
    )).lower()


def closest_records(records: list[dict], gold_id: str, limit: int = 5) -> list[dict]:
    groups = GOLD_TARGETS[gold_id]["term_groups"]
    terms = {term for group in groups for term in group}
    ranked = []
    for row in records:
        text = record_text(row)
        score = sum(term in text for term in terms)
        if score:
            ranked.append((score, row))
    return [row for _, row in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]]


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def build() -> dict:
    gold = frozen_gold_rows()
    packet: dict = {"title": "Day 8 PDF/OpenAI focused review", "outcomes": []}
    for gold_id in sorted(gold):
        row = gold[gold_id]
        paper_id = row["gold_paper_id"]
        paper_dir = OUTPUT / paper_id
        source_file = row.get("supplement_identifier") or row.get("xml_file") or ""
        source_page = int(row["page_number"]) if row.get("page_number", "").isdigit() else None
        after_pages = load_json(paper_dir / "targeted_pages.json", {})
        before_pages = load_json(
            paper_dir / "targeted_pages.pre_frozen_fix.json", after_pages
        )
        whole = load_json(paper_dir / "whole_pdf.validated.json", {"records": []})
        targeted = load_json(paper_dir / "targeted.validated.json", {"records": []})
        focused = load_json(paper_dir / "focused_misses.validated.json", {"records": []})
        focused_manifest = load_json(paper_dir / "focused_misses_manifest.json", {})
        focused_records = (
            focused["records"]
            if gold_id in focused_manifest.get("missed_ids_retried", [])
            else []
        )
        comparison_rows = load_json(paper_dir / "frozen_gold_comparison.json", [])
        focused_rows = load_json(paper_dir / "focused_gold_comparison.json", [])
        comparison = {
            item["gold_id"]: item
            for item in comparison_rows + focused_rows
        }.get(gold_id, {})
        packet["outcomes"].append({
            "gold_id": gold_id,
            "paper_id": paper_id,
            "expected_fact": row["evidence_text"],
            "expected_endpoint": row.get("outcome_endpoint_name", ""),
            "expected_value": row.get("outcome_outcome_value", ""),
            "expected_unit": row.get("outcome_outcome_unit", ""),
            "source_file": source_file,
            "source_page": source_page,
            "figure_or_table": row.get("figure_number") or row.get("table_number"),
            "panel_or_cell": row.get("table_row") or row.get("table_column"),
            "page_was_sent_before_fix": (
                source_page in before_pages.get(source_file, []) if source_page else None
            ),
            "page_was_sent_after_fix": (
                source_page in after_pages.get(source_file, []) if source_page else None
            ),
            "whole_pdf_status": comparison.get("whole_pdf_status", "not_run"),
            "targeted_status": comparison.get("targeted_status", "not_run"),
            "closest_whole_pdf_records": closest_records(whole["records"], gold_id),
            "closest_targeted_records": closest_records(targeted["records"], gold_id),
            "closest_focused_retry_records": closest_records(focused_records, gold_id),
            "human_question": (
                "Does the closest extracted record directly support the expected fact at "
                "the cited original source location, without adding an inference?"
            ),
        })
    (OUTPUT / "focused_review_packet.json").write_text(
        json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Day 8 focused PDF/OpenAI review",
        "",
        "This report separates deterministic page-selection misses from OpenAI semantic misses.",
        "",
    ]
    for item in packet["outcomes"]:
        lines.extend([
            f"## {item['gold_id']} — {item['paper_id']}",
            "",
            f"- Expected: {item['expected_fact']}",
            f"- Source: `{item['source_file']}`, page {item['source_page']}, "
            f"{item['figure_or_table'] or 'no figure/table label'}",
            f"- Page sent before fix: **{item['page_was_sent_before_fix']}**",
            f"- Page sent after fix: **{item['page_was_sent_after_fix']}**",
            f"- Whole-PDF OpenAI: **{item['whole_pdf_status']}**",
            f"- Targeted-page OpenAI: **{item['targeted_status']}**",
            "",
            "Closest targeted records:",
            "",
        ])
        records = item["closest_focused_retry_records"] or item["closest_targeted_records"]
        if not records:
            lines.append("- None — OpenAI returned no semantically close record.")
        for record in records:
            location = record["location"]
            lines.append(
                f"- `{record['record_id']}`: {record['population']} | "
                f"{record['endpoint']} | {record['value']} {record.get('unit') or ''} | "
                f"{location['file_name']} p.{location['page']} "
                f"{location.get('figure_or_table') or ''} "
                f"{location.get('panel_or_cell') or ''}"
            )
            lines.append(f"  - Evidence: “{location['evidence_quote']}”")
        lines.extend(["", f"Human check: {item['human_question']}", ""])
    (OUTPUT / "focused_review_packet.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return packet


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
