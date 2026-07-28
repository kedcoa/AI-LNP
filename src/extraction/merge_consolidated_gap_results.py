"""Validate and merge one consolidated paper response into a new result tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from src.extraction.compact_validation import validate_candidate
from src.extraction.missing_record_contracts import MissingRecordFragment
from src.extraction.run_consolidated_gap_recovery import load_task, validate


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data/staging/extraction/consolidated_gold_gap_merged_v1"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def merge(
    *,
    task_path: Path,
    fragment_path: Path,
    source_result_path: Path,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    task = load_task(task_path)
    fragment = MissingRecordFragment.model_validate_json(
        fragment_path.read_text(encoding="utf-8")
    )
    validate(fragment, task)
    source_bytes = source_result_path.read_bytes()
    if _sha(source_bytes) != task.source_result_sha256:
        raise ValueError("Consolidated task was built from a different source result")
    result = deepcopy(json.loads(source_bytes))
    if result.get("paper_id") != task.paper_id:
        raise ValueError("Source result belongs to a different paper")
    existing_experiments = {
        row["experiment_id"] for row in result.get("experiments", [])
    }
    existing_outcomes = {row["outcome_id"] for row in result.get("outcomes", [])}
    if existing_experiments & {
        row.experiment_id for row in fragment.experiments
    }:
        raise ValueError("New experiment ID collides with source result")
    if existing_outcomes & {row.outcome_id for row in fragment.outcomes}:
        raise ValueError("New outcome ID collides with source result")
    result["experiments"].extend(
        row.model_dump(mode="json") for row in fragment.experiments
    )
    result["outcomes"].extend(row.model_dump(mode="json") for row in fragment.outcomes)
    allowed_evidence = {
        row.evidence_id for row in task.evidence
    } | {
        asset.crop_evidence_id for asset in task.visual_assets
    }
    # Existing records cite evidence from the original compact result; preserve
    # those locally validated IDs while applying strict checks to new records.
    def collect(value):
        found = set()
        if isinstance(value, dict):
            found |= set(value.get("evidence_ids", []))
            for child in value.values():
                found |= collect(child)
        elif isinstance(value, list):
            for child in value:
                found |= collect(child)
        return found

    allowed_evidence |= collect(json.loads(source_bytes))
    parsed, validation = validate_candidate(
        json.dumps(result, ensure_ascii=False),
        paper_id=task.paper_id,
        allowed_evidence_ids=allowed_evidence,
    )
    if parsed is None or validation.status != "valid":
        raise ValueError(
            "Consolidated merge failed compact validation: "
            + "; ".join(row.message for row in validation.findings)
        )
    run_dir = output_root / task.paper_id
    output_path = run_dir / "final_result.json"
    if output_path.exists():
        raise FileExistsError("Refusing to overwrite an existing consolidated merge")
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "merge_version": "consolidated-gap-merge-1.0.0",
        "paper_id": task.paper_id,
        "source_result_sha256": _sha(source_bytes),
        "task_checksum": task.task_checksum,
        "recovered_candidate_ids": fragment.recovered_candidate_ids,
        "unresolved_candidate_ids": fragment.unresolved_candidate_ids,
        "new_experiment_ids": [
            row.experiment_id for row in fragment.experiments
        ],
        "new_outcome_ids": [row.outcome_id for row in fragment.outcomes],
        "final_validation_status": validation.status,
        "benchmark_merge_complete": not fragment.unresolved_candidate_ids,
        "final_result_path": str(output_path),
    }
    (run_dir / "merge_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--fragment", type=Path, required=True)
    parser.add_argument("--source-result", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(
        json.dumps(
            merge(
                task_path=args.task,
                fragment_path=args.fragment,
                source_result_path=args.source_result,
                output_root=args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
