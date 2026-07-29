"""Compare abstract-first output with frozen answers without changing either."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data" / "annotations" / "gold_v1"
PREDICTIONS = ROOT / "data" / "staging" / "extraction" / "abstract_first_v1"
REPORT = ROOT / "reports" / "extraction" / "day5_abstract_first_evaluation.json"
REVIEW = ROOT / "data" / "review" / "day5_abstract_first_manual_review.jsonl"


def rows(name: str) -> list[dict[str, str]]:
    with (GOLD / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def reported(field: dict[str, Any]) -> Any:
    return field.get("value") if field.get("value_status") == "reported" else None


def evaluate() -> dict[str, Any]:
    papers = rows("papers.csv")
    gold_formulations = rows("formulations.csv")
    gold_components = rows("components.csv")
    gold_experiments = rows("experiments.csv")
    gold_outcomes = rows("outcomes.csv")
    totals: Counter[str] = Counter()
    per_paper: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []

    for paper in papers:
        paper_id = paper["gold_paper_id"]
        path = PREDICTIONS / f"{paper_id}.json"
        if not path.exists():
            per_paper.append({"paper_id": paper_id, "status": "missing_prediction"})
            totals["missing_predictions"] += 1
            review_rows.append(
                {
                    "paper_id": paper_id,
                    "reason": "model_output_failed_contract_validation",
                    "decision": "pending_human_approval",
                }
            )
            continue
        prediction = json.loads(path.read_text(encoding="utf-8"))
        expected_zero = paper["screening_decision"] == "exclude"
        predicted_count = sum(len(prediction[key]) for key in ("formulations", "components", "experiments", "outcomes"))
        if expected_zero:
            result = "correct" if predicted_count == 0 else "incorrect"
            totals[result] += 1
            per_paper.append({"paper_id": paper_id, "zero_record_expectation": result})
            if result == "incorrect":
                review_rows.append({"paper_id": paper_id, "reason": "records_extracted_from_excluded_paper"})
            continue

        expected = {
            "formulations": [x for x in gold_formulations if x["gold_paper_id"] == paper_id],
            "components": [],
            "experiments": [x for x in gold_experiments if x["gold_paper_id"] == paper_id],
            "outcomes": [],
        }
        formulation_ids = {x["gold_formulation_id"] for x in expected["formulations"]}
        expected["components"] = [x for x in gold_components if x["gold_formulation_id"] in formulation_ids]
        experiment_ids = {x["gold_experiment_id"] for x in expected["experiments"]}
        expected["outcomes"] = [x for x in gold_outcomes if x["gold_experiment_id"] in experiment_ids]

        checks: list[dict[str, Any]] = []
        mappings = {
            "formulations": ("formulation_name", "formulation_name"),
            "components": ("component_name_reported", "component_name_reported"),
            "experiments": ("payload_name", "payload_name"),
            "outcomes": ("endpoint_name", "endpoint_name"),
        }
        for entity, (gold_key, predicted_key) in mappings.items():
            predicted_values = [norm(reported(x[predicted_key])) for x in prediction[entity]]
            for gold_row in expected[entity]:
                expected_value = norm(gold_row[gold_key])
                matched = any(
                    candidate and (candidate in expected_value or expected_value in candidate)
                    for candidate in predicted_values
                )
                result = "correct" if matched else "missing"
                totals[result] += 1
                checks.append({"entity": entity, "field": gold_key, "expected": gold_row[gold_key], "result": result})

        low_confidence = [e["evidence_id"] for e in prediction["evidence"] if e["extraction_confidence"] == "low"]
        missing_count = sum(check["result"] == "missing" for check in checks)
        if low_confidence or missing_count:
            review_rows.append(
                {"paper_id": paper_id, "low_confidence_evidence_ids": low_confidence, "missing_gold_fields": missing_count, "decision": "pending_human_approval"}
            )
        per_paper.append({"paper_id": paper_id, "checks": checks, "low_confidence_evidence_ids": low_confidence})

    report = {"summary": dict(totals), "per_paper": per_paper, "gate_G1": "pending_human_approval"}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW.open("w", encoding="utf-8") as handle:
        for item in review_rows:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
