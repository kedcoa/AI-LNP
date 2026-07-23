"""Reconcile dual-reader experiment maps and prepare paper-level review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .run_abstract_first import ROOT, gold_inputs


RUN = ROOT / "data" / "staging" / "extraction" / "g1_v3_boundaries"
REVIEW = ROOT / "data" / "review" / "day5_g1_v3_boundary_review.jsonl"
FROZEN = ROOT / "data" / "staging" / "extraction" / "g1_v3_frozen_boundaries"
SUMMARY = ROOT / "reports" / "extraction" / "day5_g1_v3_boundary_pre_review.json"


def scopes(mapping: dict[str, Any]) -> list[tuple[str, ...]]:
    return sorted(tuple(sorted(experiment["evidence_sentence_ids"])) for experiment in mapping["experiments"])


def build() -> dict[str, Any]:
    existing: dict[str, dict[str, Any]] = {}
    if REVIEW.exists():
        for line in REVIEW.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                existing[row["paper_id"]] = row
    sources = {item["paper_id"]: item for item in gold_inputs()}
    FROZEN.mkdir(parents=True, exist_ok=True)
    review_rows = []
    consensus = []
    expected_zero = []
    for paper_id, source in sources.items():
        paper_dir = RUN / paper_id
        a = json.loads((paper_dir / "reader_a.validated.json").read_text(encoding="utf-8"))
        b = json.loads((paper_dir / "reader_b.validated.json").read_text(encoding="utf-8"))
        sentences = json.loads((paper_dir / "sentences.json").read_text(encoding="utf-8"))
        if not source["eligible_records_expected"]:
            expected_zero.append(paper_id)
            (FROZEN / f"{paper_id}.json").write_text(json.dumps({"paper_id": paper_id, "status": "expected_zero", "experiments": []}, indent=2) + "\n", encoding="utf-8")
            continue
        if scopes(a) == scopes(b):
            consensus.append(paper_id)
            frozen_experiments = []
            for index, experiment in enumerate(a["experiments"], 1):
                frozen_experiments.append({"experiment_id": f"{paper_id}-E{index:02d}", **experiment})
            (FROZEN / f"{paper_id}.json").write_text(json.dumps({"paper_id": paper_id, "status": "dual_reader_consensus", "experiments": frozen_experiments}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            continue
        previous = existing.get(paper_id, {})
        row = {
            "review_id": f"G1V3-B{len(review_rows)+1:03d}",
            "paper_id": paper_id,
            "title": source["title"],
            "sentences": sentences,
            "reader_a": a["experiments"],
            "reader_b": b["experiments"],
            "reader_a_count": len(a["experiments"]),
            "reader_b_count": len(b["experiments"]),
            "boundary_decision": previous.get("boundary_decision", "pending"),
            "reviewer_reason": previous.get("reviewer_reason", ""),
            "reviewer": previous.get("reviewer", ""),
            "reviewed_at": previous.get("reviewed_at"),
        }
        review_rows.append(row)
    with REVIEW.open("w", encoding="utf-8") as handle:
        for row in review_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"expected_zero_papers": expected_zero, "automatic_consensus_papers": consensus, "human_review_papers": [row["paper_id"] for row in review_rows], "human_review_count": len(review_rows), "status": "pending_boundary_review"}
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
