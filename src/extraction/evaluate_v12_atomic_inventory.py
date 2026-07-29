"""Evaluate atomic text candidates one-to-one against frozen gold outcomes."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from src.extraction.build_provisional_experiments import load_full_view
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12
from src.rag.compact_api_packet import _same_gold_location


ROOT = Path(__file__).resolve().parents[2]
GOLD_ROOT = ROOT / "data/annotations/gold_v1"
ATOMIC_ROOT = ROOT / "data/staging/extraction/v12_atomic_inventory"
BASELINE_PATH = (
    ROOT / "reports/extraction/v12_baseline/baseline_manifest.json"
)
OUTPUT_ROOT = ROOT / "reports/extraction/v12_atomic_inventory_eval"
MATCH_THRESHOLD = 8
STOP = {
    "the",
    "and",
    "of",
    "in",
    "to",
    "a",
    "an",
    "was",
    "were",
    "with",
    "from",
    "for",
    "after",
    "outcome",
    "cells",
    "cell",
    "reported",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _tokens(text: str) -> set[str]:
    return {
        value
        for value in re.findall(r"[a-z0-9]+", text.casefold().replace("_", " "))
        if len(value) >= 2 and value not in STOP
    }


def _number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_text(
    candidate: AtomicOutcomeCandidateV12,
    evidence_text: dict[str, str],
) -> str:
    return " ".join(
        str(value)
        for value in (
            candidate.subject_text,
            candidate.predicate,
            candidate.object_text,
            candidate.endpoint_text,
            candidate.qualitative_result,
            candidate.numeric_value,
            candidate.unit,
            *(evidence_text.get(identifier, "") for identifier in candidate.evidence_ids),
        )
        if value is not None
    )


def _allowed_predicates(gold: dict[str, str]) -> set[str]:
    text = " ".join(
        (gold["endpoint_name"], gold["qualitative_outcome"])
    ).casefold()
    if re.search(r"\b(?:eliminat|phagocyt|recogniz|eradica)", text):
        return {"eliminated", "phagocytosed", "recognized"}
    if re.search(r"\b(?:deletion|insertion|indel|gene editing)", text):
        return {"edited"}
    if "uptake" in text:
        return {"uptake_by"}
    if re.search(r"\b(?:colocali[sz]|locali[sz]|marker)", text):
        return {"colocalized_with", "localized_to", "expressed"}
    if re.search(r"\b(?:expression|positive|transfect|deliver)", text):
        return {
            "expressed",
            "delivered_to",
            "colocalized_with",
            "localized_to",
            "increased",
            "decreased",
        }
    if re.search(r"\b(?:activity|sustain|maintain)", text):
        return {"reached", "maintained", "increased"}
    if re.search(r"\b(?:reduc|damage|defenestration|fibrosis)", text):
        return {"reduced", "decreased", "increased"}
    return {
        "expressed",
        "delivered_to",
        "uptake_by",
        "edited",
        "increased",
        "decreased",
        "reduced",
        "reached",
        "maintained",
        "colocalized_with",
        "localized_to",
        "recognized",
        "phagocytosed",
        "eliminated",
    }


def _score(
    gold: dict[str, str],
    gold_evidence: dict[str, str],
    candidate: AtomicOutcomeCandidateV12,
    *,
    candidate_text: str,
    candidate_locations: list[dict],
) -> tuple[int, list[str]]:
    reasons = []
    score = 0
    if candidate.predicate not in _allowed_predicates(gold):
        return -100, ["incompatible_predicate"]
    overlap = _tokens(
        " ".join(
            (
                gold["endpoint_name"],
                gold["qualitative_outcome"],
                gold_evidence["evidence_text"],
            )
        )
    ) & _tokens(candidate_text)
    score += min(6, len(overlap))
    if overlap:
        reasons.append(f"token_overlap:{len(overlap)}")

    if any(
        _same_gold_location(gold_evidence, location)
        for location in candidate_locations
    ):
        score += 5
        reasons.append("gold_source_location")

    expected_number = _number(gold["outcome_value"])
    if expected_number is not None:
        if (
            candidate.numeric_value is not None
            and abs(candidate.numeric_value - expected_number) < 0.011
        ):
            score += 8
            reasons.append("exact_numeric_value")
        elif candidate.numeric_value is not None:
            score -= 5
            reasons.append("different_numeric_value")

    expected_qualitative = _tokens(gold["qualitative_outcome"])
    candidate_qualitative = _tokens(candidate.qualitative_result or "")
    if expected_qualitative & candidate_qualitative:
        score += 2
        reasons.append("qualitative_result")
    if (
        re.search(r"\b(?:no|not|absent|solely)\b", gold["qualitative_outcome"], re.I)
        and candidate.polarity == "negative"
    ):
        score += 2
        reasons.append("negative_polarity")
    return score, reasons


def _best_assignment(options: list[list[tuple[int, int, list[str]]]]):
    best = []

    def visit(gold_index: int, used: set[int], current: list[tuple]):
        nonlocal best
        if gold_index == len(options):
            key = (len(current), sum(row[2] for row in current))
            best_key = (len(best), sum(row[2] for row in best))
            if key > best_key:
                best = list(current)
            return
        visit(gold_index + 1, used, current)
        for candidate_index, score, reasons in options[gold_index]:
            if candidate_index in used or score < MATCH_THRESHOLD:
                continue
            used.add(candidate_index)
            current.append((gold_index, candidate_index, score, reasons))
            visit(gold_index + 1, used, current)
            current.pop()
            used.remove(candidate_index)

    visit(0, set(), [])
    return best


def evaluate() -> dict:
    outcomes = _rows(GOLD_ROOT / "outcomes.csv")
    evidence = {
        row["evidence_id"]: row
        for row in _rows(GOLD_ROOT / "evidence.csv")
    }
    experiments = {
        row["gold_experiment_id"]: row
        for row in _rows(GOLD_ROOT / "experiments.csv")
    }
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    baseline_missing = set(
        baseline["evaluation"]["missing_gold_outcome_ids"]
    )
    visual_gold_ids = {
        row["supported_entity_id"]
        for row in evidence.values()
        if row["extraction_method"] == "manual_visual_pdf_review"
        and row["supported_entity_type"] == "outcome"
        and row["supported_entity_id"] in baseline_missing
    }

    by_paper: dict[str, list[dict[str, str]]] = {}
    for outcome in outcomes:
        paper_id = experiments[outcome["gold_experiment_id"]]["gold_paper_id"]
        by_paper.setdefault(paper_id, []).append(outcome)

    results = []
    candidate_total = 0
    matched_candidate_total = 0
    for paper_id, paper_gold in sorted(by_paper.items()):
        candidate_path = ATOMIC_ROOT / paper_id / "selected_candidates.json"
        candidates = [
            AtomicOutcomeCandidateV12.model_validate(row)
            for row in json.loads(
                candidate_path.read_text(encoding="utf-8")
            )
        ]
        packet = load_full_view(paper_id)
        source_by_id = {
            row.source_id: row.model_dump(mode="json", exclude_none=True)
            for row in packet.sources
        }
        evidence_text = {row.evidence_id: row.text for row in packet.evidence}
        text_gold = [
            row
            for row in paper_gold
            if row["gold_outcome_id"] not in visual_gold_ids
        ]
        options = []
        for gold in text_gold:
            row_options = []
            gold_evidence = evidence[gold["evidence_id"]]
            for candidate_index, candidate in enumerate(candidates):
                candidate_text = _candidate_text(candidate, evidence_text)
                locations = [
                    source_by_id[source_id]
                    for source_id in candidate.source_ids
                    if source_id in source_by_id
                ]
                score, reasons = _score(
                    gold,
                    gold_evidence,
                    candidate,
                    candidate_text=candidate_text,
                    candidate_locations=locations,
                )
                row_options.append((candidate_index, score, reasons))
            options.append(row_options)
        assignment = _best_assignment(options)
        matched_gold = {row[0] for row in assignment}
        matched_candidates = {row[1] for row in assignment}
        candidate_total += len(candidates)
        matched_candidate_total += len(matched_candidates)
        match_by_gold = {row[0]: row for row in assignment}
        for gold_index, gold in enumerate(text_gold):
            match = match_by_gold.get(gold_index)
            results.append(
                {
                    "gold_outcome_id": gold["gold_outcome_id"],
                    "paper_id": paper_id,
                    "endpoint_family": gold["endpoint_family"],
                    "recalled": match is not None,
                    "candidate_id": (
                        candidates[match[1]].candidate_id if match else None
                    ),
                    "score": match[2] if match else None,
                    "reasons": match[3] if match else [],
                }
            )

    recalled = sum(row["recalled"] for row in results)
    previous = [
        row
        for row in results
        if row["gold_outcome_id"] not in baseline_missing
    ]
    targeted = [
        row
        for row in results
        if row["gold_outcome_id"] in {"GO-002", "GO-003", "GO-017"}
    ]
    by_type = {}
    for family in sorted({row["endpoint_family"] for row in results}):
        typed = [row for row in results if row["endpoint_family"] == family]
        by_type[family] = {
            "recalled": sum(row["recalled"] for row in typed),
            "total": len(typed),
        }
    return {
        "evaluation_version": "atomic-outcome-inventory-eval-1.2.0",
        "scope": "local text-track candidates; no API calls",
        "text_recalled": recalled,
        "text_total": len(results),
        "text_rate": recalled / len(results),
        "missing_text_gold_outcome_ids": [
            row["gold_outcome_id"] for row in results if not row["recalled"]
        ],
        "previously_recovered_retained": (
            f"{sum(row['recalled'] for row in previous)}/{len(previous)}"
        ),
        "targeted_text_misses_recalled": (
            f"{sum(row['recalled'] for row in targeted)}/{len(targeted)}"
        ),
        "visual_gold_outcome_ids_deferred": sorted(visual_gold_ids),
        "recall_by_type": by_type,
        "selected_atomic_candidates_in_gold_papers": candidate_total,
        "one_to_one_gold_matched_candidates": matched_candidate_total,
        "gold_match_yield": (
            matched_candidate_total / candidate_total if candidate_total else 0
        ),
        "precision_status": (
            "candidate yield is not final extraction precision; critical-field "
            "precision is measured after validated records are produced"
        ),
        "results": results,
        "paid_api_requests": 0,
    }


def main() -> None:
    report = evaluate()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
