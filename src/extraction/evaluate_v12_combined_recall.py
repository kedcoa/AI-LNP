"""Development-only combined recall report for text and visual tracks."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .v12_structure_contracts import AtomicOutcomeCandidateV12


ROOT = Path(__file__).resolve().parents[2]
TEXT_REPORT = (
    ROOT / "reports/extraction/v12_atomic_inventory_eval/evaluation.json"
)
VISUAL_CANDIDATES = (
    ROOT
    / "data/staging/extraction/v12_docling_candidates"
    / "GP-006-mmc1-p002-table-03/candidates.json"
)
VLM_REPORT = (
    ROOT
    / "reports/extraction/v12_vlm_benchmarks"
    / "qwen3-vl-8b-instruct-thinking-off"
    / "evaluation.json"
)
OUTPUT = ROOT / "reports/extraction/v12_combined_recall/evaluation.json"


def match_go006(
    candidates: list[AtomicOutcomeCandidateV12],
) -> AtomicOutcomeCandidateV12 | None:
    for candidate in candidates:
        endpoint = (candidate.endpoint_text or "").lower()
        if (
            candidate.paper_id == "GP-006"
            and "lsec" in candidate.subject_text.lower()
            and "total" in endpoint
            and "insertion" in endpoint
            and "frequency" in endpoint
            and candidate.numeric_value is not None
            and abs(candidate.numeric_value - 1.01) < 1e-9
            and "0.38" in (candidate.value_text or "")
        ):
            return candidate
    return None


def run() -> dict[str, Any]:
    text = json.loads(TEXT_REPORT.read_text())
    text_recovered = {
        row["gold_outcome_id"] for row in text["results"] if row["recalled"]
    }
    candidates = [
        AtomicOutcomeCandidateV12.model_validate(row)
        for row in json.loads(VISUAL_CANDIDATES.read_text())
    ]
    go006 = match_go006(candidates)
    vlm = json.loads(VLM_REPORT.read_text()) if VLM_REPORT.exists() else {}
    go018_passed = bool(vlm.get("integration_gate_passed")) and any(
        row.get("query_id") == "GO-018-positive" and row.get("passed")
        for row in vlm.get("runs", [])
    )
    recovered = set(text_recovered)
    visual_results = [
        {
            "gold_outcome_id": "GO-006",
            "recalled": go006 is not None,
            "candidate_id": go006.candidate_id if go006 else None,
            "route": "docling_table_intersection",
        },
        {
            "gold_outcome_id": "GO-018",
            "recalled": go018_passed,
            "candidate_id": None,
            "route": "gated_local_vlm",
            "gate": "failed" if not go018_passed else "passed",
        },
    ]
    recovered.update(
        row["gold_outcome_id"] for row in visual_results if row["recalled"]
    )
    outcomes: list[dict[str, str]] = []
    with (ROOT / "data/annotations/gold_v1/outcomes.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        outcomes = list(csv.DictReader(handle))
    by_type: dict[str, dict[str, int]] = defaultdict(
        lambda: {"recalled": 0, "total": 0}
    )
    for row in outcomes:
        family = row["endpoint_family"]
        by_type[family]["total"] += 1
        if row["gold_outcome_id"] in recovered:
            by_type[family]["recalled"] += 1
    missing = sorted({row["gold_outcome_id"] for row in outcomes} - recovered)
    evaluation = {
        "evaluation_version": "v12-combined-development-1.0",
        "scope": "development gold only; held-out set is not yet populated",
        "recovered": len(recovered),
        "total": len(outcomes),
        "rate": len(recovered) / len(outcomes),
        "recovered_gold_outcome_ids": sorted(recovered),
        "missing_gold_outcome_ids": missing,
        "previously_recovered_retained": (
            text["previously_recovered_retained"]
        ),
        "text_track": {
            "recovered": text["text_recalled"],
            "total": text["text_total"],
            "missing": text["missing_text_gold_outcome_ids"],
        },
        "visual_track": visual_results,
        "recall_by_type": dict(sorted(by_type.items())),
        "precision": {
            "status": "not_final_extraction_precision",
            "critical_field_gate": 0.90,
            "docling_candidates": len(candidates),
            "known_gold_matches": int(go006 is not None),
            "candidate_gold_match_yield": (
                int(go006 is not None) / len(candidates) if candidates else 0
            ),
            "explanation": (
                "Candidate yield is not precision. Final precision requires "
                "validated extraction outputs and one-to-one false-positive review."
            ),
        },
        "vlm": {
            "model": vlm.get("model"),
            "model_digest": vlm.get("model_digest"),
            "integration_allowed": bool(vlm.get("integration_gate_passed")),
        },
        "paid_api_requests": 0,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(
        evaluation, indent=2, ensure_ascii=False
    ) + "\n")
    return evaluation


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
