"""Build the required human precision/experiment-link review for v1.2 results."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOT = ROOT / "data/staging/extraction/compact_one_call_v1_2"
OUTPUT_ROOT = ROOT / "reports/extraction/v12_main_route_precision_review"


def _value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def _evidence_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value.get("evidence_ids", []))
        for child in value.values():
            found |= _evidence_ids(child)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found |= _evidence_ids(child)
        return found
    return set()


def _evidence_map(request: dict[str, Any]) -> dict[str, str]:
    payload = request["request_payload"]
    rows = [
        *payload["evidence_packet"].get("evidence", []),
        *payload["outcome_recall_support"].get("local_evidence", []),
    ]
    return {row["evidence_id"]: row["text"] for row in rows}


def run(
    *,
    result_root: Path = RESULT_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    review_rows: list[dict[str, Any]] = []
    for paper_root in sorted(result_root.glob("GP-*")):
        result_path = paper_root / "result.json"
        request_path = paper_root / "request.json"
        if not result_path.exists() or not request_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        evidence = _evidence_map(request)
        experiments = {
            row["experiment_id"]: row for row in result.get("experiments", [])
        }
        for outcome in result.get("outcomes", []):
            experiment = experiments.get(outcome.get("experiment_id"), {})
            evidence_ids = sorted(_evidence_ids(outcome))
            review_rows.append({
                "paper_id": result["paper_id"],
                "outcome_id": outcome["outcome_id"],
                "experiment_id": outcome["experiment_id"],
                "payload_name": _value(experiment.get("payload_name")),
                "delivery_recipient_cell": _value(
                    experiment.get("delivery_recipient_cell")
                ),
                "therapeutic_target_cell": _value(
                    experiment.get("therapeutic_target_cell")
                ),
                "experimental_context": _value(
                    experiment.get("experimental_context")
                ),
                "assay": _value(outcome.get("assay")),
                "endpoint": _value(outcome.get("endpoint")),
                "outcome_value": _value(outcome.get("outcome_value")),
                "outcome_unit": _value(outcome.get("outcome_unit")),
                "qualitative_outcome": _value(
                    outcome.get("qualitative_outcome")
                ),
                "evidence_ids": " | ".join(evidence_ids),
                "evidence_text": " || ".join(
                    f"{identifier}: {evidence.get(identifier, '[missing]')}"
                    for identifier in evidence_ids
                ),
                "human_supported": "",
                "human_experiment_link_correct": "",
                "human_critical_fields_correct": "",
                "human_notes": "",
            })

    output_root.mkdir(parents=True, exist_ok=True)
    columns = list(review_rows[0]) if review_rows else [
        "paper_id",
        "outcome_id",
        "human_supported",
        "human_experiment_link_correct",
        "human_critical_fields_correct",
        "human_notes",
    ]
    with (output_root / "outcome_review.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(review_rows)
    manifest = {
        "review_version": "main-route-precision-review-1.2.0",
        "papers": len({row["paper_id"] for row in review_rows}),
        "outcomes": len(review_rows),
        "status": "pending_human_review",
        "required_critical_field_precision": 0.90,
        "required_wrong_experiment_links": 0,
        "explanation": (
            "Frozen gold is selective; unsupported outcomes and experiment "
            "links require human evidence review."
        ),
        "paid_api_requests": 0,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
