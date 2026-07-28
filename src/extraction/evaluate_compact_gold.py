"""Evaluate cached compact extraction results against the frozen nine-paper gold set."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.extraction.compact_contracts import CompactExtractionResponse


ROOT = Path(__file__).resolve().parents[2]
GOLD_ROOT = ROOT / "data" / "annotations" / "gold_v1"
PACKET_ROOT = ROOT / "data" / "staging" / "rag" / "compact_api_packets_v1"
RESULT_ROOT = ROOT / "data" / "staging" / "extraction" / "compact_one_call_v1"
OUTPUT_ROOT = ROOT / "reports" / "extraction" / "day5_compact_gold_morning"
PAPER_IDS = [f"GP-{number:03d}" for number in range(1, 10)]
CURRENT_CONTRACT_VERSION = "compact-1.1.0"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _number(value: str) -> float | None:
    if not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _field_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _gold_outcomes_by_paper(
    experiments: list[dict[str, str]], outcomes: list[dict[str, str]]
) -> dict[str, list[dict[str, str]]]:
    experiment_paper = {
        row["gold_experiment_id"]: row["gold_paper_id"] for row in experiments
    }
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in outcomes:
        grouped[experiment_paper[row["gold_experiment_id"]]].append(row)
    return grouped


def _exact_gold_outcomes(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    exact: list[dict[str, Any]] = []
    for row in rows:
        value = _number(row["outcome_value"])
        if row["value_status"] == "reported" and value is not None:
            exact.append(
                {
                    "gold_outcome_id": row["gold_outcome_id"],
                    "endpoint_name": row["endpoint_name"],
                    "value": value,
                    "unit": row["outcome_unit"],
                    "evidence_id": row["evidence_id"],
                }
            )
    return exact


def _result_numbers(result: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for row in result.get("outcomes", []):
        value = _field_value(row.get("outcome_value"))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found.append(
                {
                    "outcome_id": row.get("outcome_id"),
                    "endpoint": _field_value(row.get("endpoint")),
                    "value": float(value),
                    "unit": _field_value(row.get("outcome_unit")),
                }
            )
    return found


def _expected_eligibility(paper: dict[str, str]) -> str:
    if paper["screening_decision"] == "exclude":
        return "ineligible"
    if paper["screening_decision"] == "include":
        return "eligible"
    return "manual_review"


def evaluate(
    *,
    gold_root: Path = GOLD_ROOT,
    packet_root: Path = PACKET_ROOT,
    result_root: Path = RESULT_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    papers = {row["gold_paper_id"]: row for row in _rows(gold_root / "papers.csv")}
    experiments = _rows(gold_root / "experiments.csv")
    outcomes = _rows(gold_root / "outcomes.csv")
    outcomes_by_paper = _gold_outcomes_by_paper(experiments, outcomes)
    packet_manifest = json.loads((packet_root / "manifest.json").read_text())
    preservation = packet_manifest["frozen_gold_preservation"]

    paper_rows: list[dict[str, Any]] = []
    exact_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, str]] = []
    current_schema_papers = 0
    eligibility_correct = 0
    papers_requiring_review = 0
    total_input = total_output = total_tokens = 0

    for paper_id in PAPER_IDS:
        result = json.loads((result_root / paper_id / "result.json").read_text())
        manifest = json.loads((result_root / paper_id / "manifest.json").read_text())
        usage = manifest.get("usage") or {}
        total_input += int(usage.get("input_tokens") or 0)
        total_output += int(usage.get("output_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        contract_version = result.get("contract_version")
        current_schema = contract_version == CURRENT_CONTRACT_VERSION
        current_schema_papers += int(current_schema)

        if current_schema:
            parsed = CompactExtractionResponse.model_validate(result)
            actual_eligibility = parsed.eligibility.decision
            unresolved_count = len(parsed.unresolved_items)
        else:
            actual_eligibility = (
                "eligible" if result.get("formulations") else "ineligible"
            )
            unresolved_count = len(result.get("unresolved_items", []))

        expected = _expected_eligibility(papers[paper_id])
        eligibility_match = (
            actual_eligibility == expected if expected != "manual_review" else None
        )
        if eligibility_match is True:
            eligibility_correct += 1
        needs_review = unresolved_count > 0 or not current_schema or expected == "manual_review"
        papers_requiring_review += int(needs_review)

        extracted_numbers = _result_numbers(result)
        exact_gold = _exact_gold_outcomes(outcomes_by_paper.get(paper_id, []))
        for gold in exact_gold:
            matches = [
                row
                for row in extracted_numbers
                if abs(row["value"] - gold["value"]) <= 1e-9
            ]
            exact_rows.append(
                {
                    "paper_id": paper_id,
                    **gold,
                    "recalled": bool(matches),
                    "candidate_matches": matches,
                }
            )

        if result.get("formulations") or result.get("experiments") or result.get("outcomes"):
            review_rows.append(
                {
                    "paper_id": paper_id,
                    "review_type": "critical_field_precision",
                    "status": "human_review_required",
                    "reason": (
                        "The frozen gold is selective, so an extracted field absent from "
                        "gold cannot be labeled unsupported automatically."
                    ),
                }
            )
            review_rows.append(
                {
                    "paper_id": paper_id,
                    "review_type": "experiment_mixing_and_unsupported_claims",
                    "status": "human_review_required",
                    "reason": (
                        "Schema links are valid, but scientific co-reference and support "
                        "must be compared with source evidence."
                    ),
                }
            )

        paper_rows.append(
            {
                "paper_id": paper_id,
                "contract_version": contract_version,
                "current_schema": current_schema,
                "expected_eligibility": expected,
                "actual_eligibility": actual_eligibility,
                "eligibility_match": eligibility_match,
                "unresolved_items": unresolved_count,
                "requires_human_review": needs_review,
                "record_counts": manifest.get("record_counts", {}),
                "usage": usage,
            }
        )

    exact_recalled = sum(row["recalled"] for row in exact_rows)
    exact_total = len(exact_rows)
    available = int(preservation["available_in_budgeted_packet"])
    frozen_total = int(preservation["frozen_gold_locations"])
    comparable_eligibility = sum(
        row["expected_eligibility"] != "manual_review" for row in paper_rows
    )
    structurally_valid = sum(
        bool(
            json.loads(
                (result_root / paper_id / "manifest.json").read_text()
            ).get("checks", {}).get("all_evidence_ids_exist_in_packet")
        )
        for paper_id in PAPER_IDS
    )

    automated_gate_pass = (
        current_schema_papers == 9
        and exact_recalled == exact_total
        and available == frozen_total
        and eligibility_correct == comparable_eligibility
        and structurally_valid == 9
        and not review_rows
    )
    summary = {
        "evaluation_version": "day5-compact-gold-morning-1.0.0",
        "scope": "cached compact route; no API calls made by evaluator",
        "paper_count": 9,
        "schema_comparability": {
            "current_schema_papers": current_schema_papers,
            "required": 9,
            "passed": current_schema_papers == 9,
        },
        "retrieval_recall": {
            "available_gold_locations": available,
            "total_gold_locations": frozen_total,
            "rate": available / frozen_total,
            "unavailable_evidence_ids": [
                row["evidence_id"]
                for row in preservation["results"]
                if not row["available_in_budgeted_packet"]
            ],
        },
        "eligibility_accuracy": {
            "correct": eligibility_correct,
            "comparable_papers": comparable_eligibility,
            "rate": eligibility_correct / comparable_eligibility,
            "manual_review_papers": [
                row["paper_id"]
                for row in paper_rows
                if row["expected_eligibility"] == "manual_review"
            ],
        },
        "exact_outcome_recall": {
            "recalled": exact_recalled,
            "total_exact_gold_outcomes": exact_total,
            "rate": exact_recalled / exact_total if exact_total else None,
        },
        "evidence_reference_correctness": {
            "structurally_valid_papers": structurally_valid,
            "paper_count": 9,
            "rate": structurally_valid / 9,
            "semantic_correctness": "human_review_required",
        },
        "human_review_rate": {
            "papers_requiring_review": papers_requiring_review,
            "paper_count": 9,
            "rate": papers_requiring_review / 9,
        },
        "critical_field_precision": "pending_human_review",
        "experiment_mixing_errors": "pending_human_review",
        "unsupported_claims": "pending_human_review",
        "token_usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_tokens,
        },
        "paid_api_requests_this_evaluation": 0,
        "automated_morning_gate": "pass" if automated_gate_pass else "not_passed",
        "gate_reasons": [
            reason
            for condition, reason in [
                (
                    current_schema_papers != 9,
                    "Not all papers use the current compact contract.",
                ),
                (
                    available != frozen_total,
                    "Not all frozen gold evidence locations reached the compact packet.",
                ),
                (
                    exact_recalled != exact_total,
                    "Not all exact frozen outcomes were recalled.",
                ),
                (
                    eligibility_correct != comparable_eligibility,
                    "At least one comparable paper has the wrong eligibility decision.",
                ),
                (
                    bool(review_rows),
                    "Semantic precision, mixing, and unsupported-claim review is pending.",
                ),
            ]
            if condition
        ],
        "papers": paper_rows,
        "exact_outcomes": exact_rows,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "evaluation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output_root / "human_review_queue.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["paper_id", "review_type", "status", "reason"]
        )
        writer.writeheader()
        writer.writerows(review_rows)
    with (output_root / "paper_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        fields = [
            "paper_id",
            "contract_version",
            "current_schema",
            "expected_eligibility",
            "actual_eligibility",
            "eligibility_match",
            "unresolved_items",
            "requires_human_review",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in paper_rows)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(evaluate(output_root=args.output_root), indent=2))


if __name__ == "__main__":
    main()
