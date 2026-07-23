from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "rag" / "gold_v1_retrieval_sentence-transformers.json"
CSV_OUT = ROOT / "reports" / "rag" / "gold_v1_retrieval_table.csv"
MD_OUT = ROOT / "reports" / "rag" / "gold_v1_retrieval_table.md"


def build() -> tuple[Path, Path]:
    report = json.loads(REPORT.read_text())
    rows = []
    for item in report["results"]:
        location = item["gold_xml_element_id"] or (
            f"page {item['gold_page']}" if item["gold_page"] else Path(item["gold_source"]).name
        )
        rows.append({
            "evidence_id": item["evidence_id"],
            "paper_id": item["paper_id"],
            "field": item["field_name"],
            "correct_source_retrieved": "YES" if item["hit"] else "NO",
            "gold_rank": item["first_gold_rank"] or "",
            "human_verified_location": location,
            "top_retrieved_block": item["retrieved_block_ids"][0] if item["retrieved_block_ids"] else "",
        })
    with CSV_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Full-text retrieval results",
        "",
        f"Correct source retrieved in top {report['k']}: **{report['hits']}/{report['queries']} "
        f"({report['recall_at_k']:.1%})**",
        "",
        "| Evidence | Paper | Field | Correct source in top 8? | Rank | Human-verified location |",
        "|---|---|---|---:|---:|---|",
    ]
    lines.extend(
        f"| {row['evidence_id']} | {row['paper_id']} | {row['field']} | "
        f"{row['correct_source_retrieved']} | {row['gold_rank'] or '—'} | "
        f"{row['human_verified_location']} |"
        for row in rows
    )
    lines += [
        "",
        "> This table measures retrieval of the correct evidence location, not whether an LLM "
        "extracted every structured field correctly. Extraction precision requires a separate "
        "human comparison of generated field values against these source blocks.",
    ]
    MD_OUT.write_text("\n".join(lines) + "\n")
    return CSV_OUT, MD_OUT


if __name__ == "__main__":
    print("\n".join(map(str, build())))
