"""Build bounded, experiment-scoped repair tasks from structural coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.extraction.missing_record_contracts import (
    MissingRecordCandidateFact,
    MissingRecordExperimentContext,
    MissingRecordTask,
)
from src.extraction.repair_contracts import RepairEvidence
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "data/staging/extraction/compact_one_call_v1_2"
REPORT_PATH = (
    ROOT / "reports/extraction/v12_structural_repair_tasks/summary.json"
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _evidence_map(request: dict[str, Any]) -> dict[str, RepairEvidence]:
    payload = request["request_payload"]
    rows = [
        *payload["evidence_packet"].get("evidence", []),
        *payload["outcome_recall_support"].get("local_evidence", []),
    ]
    return {
        row["evidence_id"]: RepairEvidence(
            evidence_id=row["evidence_id"],
            text=row["text"],
            source_ids=row.get("source_ids", []),
        )
        for row in rows
    }


def _batches(
    candidates: list[AtomicOutcomeCandidateV12],
) -> list[list[AtomicOutcomeCandidateV12]]:
    """Keep each task within 8 candidates and 12 unique evidence items."""

    batches: list[list[AtomicOutcomeCandidateV12]] = []
    current: list[AtomicOutcomeCandidateV12] = []
    evidence_ids: set[str] = set()
    for candidate in sorted(candidates, key=lambda row: row.candidate_id):
        combined = evidence_ids | set(candidate.evidence_ids)
        if current and (len(current) == 8 or len(combined) > 12):
            batches.append(current)
            current = []
            evidence_ids = set()
            combined = set(candidate.evidence_ids)
        if len(combined) > 12:
            raise ValueError(
                f"{candidate.candidate_id} alone exceeds the 12-evidence cap"
            )
        current.append(candidate)
        evidence_ids = combined
    if current:
        batches.append(current)
    return batches


def build_for_run(run_dir: Path) -> dict[str, Any]:
    request_path = run_dir / "request.json"
    result_path = run_dir / "result.json"
    coverage_path = run_dir / "v12_structural_coverage.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result_bytes = result_path.read_bytes()
    result = json.loads(result_bytes)
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    support = request["request_payload"]["outcome_recall_support"]
    candidate_by_id = {
        row.candidate_id: row
        for row in (
            AtomicOutcomeCandidateV12.model_validate(value)
            for value in support["atomic_outcome_candidates"]
        )
    }
    repair_ids = {
        row["candidate_id"]
        for row in coverage["candidates"]
        if row["route"] == "bounded_repair_task"
    }
    human_review_ids = sorted(
        row["candidate_id"]
        for row in coverage["candidates"]
        if row["route"] == "human_review"
    )
    grouped: dict[str, list[AtomicOutcomeCandidateV12]] = defaultdict(list)
    for candidate_id in sorted(repair_ids):
        candidate = candidate_by_id[candidate_id]
        if candidate.provisional_experiment_id is None:
            raise ValueError(
                f"{candidate_id} cannot be queued without an experiment"
            )
        grouped[candidate.provisional_experiment_id].append(candidate)

    associated_experiments = {
        row["provisional_experiment_id"]
        for row in coverage["experiment_associations"].values()
        if row.get("status") == "associated"
        and row.get("provisional_experiment_id")
    }
    provisional_by_id = {
        row["provisional_experiment_id"]: row
        for row in support["provisional_experiments"]
    }
    evidence_by_id = _evidence_map(request)
    tasks: list[MissingRecordTask] = []
    task_metadata = []
    source_inventory_sha = _sha(_canonical(support))
    for provisional_id, candidates in sorted(grouped.items()):
        for rows in _batches(candidates):
            candidate_ids = [row.candidate_id for row in rows]
            evidence_ids = list(
                dict.fromkeys(
                    evidence_id
                    for row in rows
                    for evidence_id in row.evidence_ids
                )
            )
            missing_evidence = [
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id not in evidence_by_id
            ]
            if missing_evidence:
                raise ValueError(
                    f"{provisional_id} has unavailable evidence: "
                    f"{missing_evidence}"
                )
            unsigned = {
                "task_version": "missing-record-task-1.1.0",
                "paper_id": support["paper_id"],
                "route_ids": [
                    f"structural:{candidate_id}"
                    for candidate_id in candidate_ids
                ],
                "candidate_ids": candidate_ids,
                "experiment_context": MissingRecordExperimentContext(
                    provisional_experiment_id=provisional_id,
                    label=provisional_by_id[provisional_id].get(
                        "label", provisional_id
                    ),
                    anchors=[
                        {
                            **anchor,
                            "evidence_ids": [
                                evidence_id
                                for evidence_id in anchor["evidence_ids"]
                                if evidence_id in evidence_ids
                            ],
                        }
                        for anchor in provisional_by_id[provisional_id][
                            "anchors"
                        ]
                    ],
                ).model_dump(mode="json"),
                "candidate_facts": [
                    MissingRecordCandidateFact(
                        candidate_id=row.candidate_id,
                        subject_text=row.subject_text,
                        predicate=row.predicate,
                        object_text=row.object_text,
                        endpoint_text=row.endpoint_text,
                        qualitative_result=row.qualitative_result,
                        numeric_value=row.numeric_value,
                        value_text=row.value_text,
                        unit=row.unit,
                        polarity=row.polarity,
                        evidence_ids=row.evidence_ids,
                    ).model_dump(mode="json")
                    for row in rows
                ],
                "evidence": [
                    evidence_by_id[evidence_id].model_dump(mode="json")
                    for evidence_id in evidence_ids
                ],
                "existing_formulation_ids": [
                    row["formulation_id"]
                    for row in result.get("formulations", [])
                ],
                "existing_experiment_ids": [
                    row["experiment_id"]
                    for row in result.get("experiments", [])
                ],
                "existing_outcome_ids": [
                    row["outcome_id"]
                    for row in result.get("outcomes", [])
                ],
                "permitted_new_experiments": (
                    0 if provisional_id in associated_experiments else 1
                ),
                "permitted_new_outcomes": min(
                    8, max(1, len(candidate_ids) * 2)
                ),
                "source_result_sha256": _sha(result_bytes),
                "source_inventory_sha256": source_inventory_sha,
            }
            task = MissingRecordTask.model_validate(
                {
                    **unsigned,
                    "task_checksum": _sha(_canonical(unsigned)),
                }
            )
            tasks.append(task)
            task_metadata.append(
                {
                    "provisional_experiment_id": provisional_id,
                    "candidate_ids": candidate_ids,
                    "candidate_facts_included": True,
                    "experiment_label": provisional_by_id[
                        provisional_id
                    ].get("label", provisional_id),
                    "evidence_ids": evidence_ids,
                    "permitted_new_experiments": (
                        task.permitted_new_experiments
                    ),
                    "permitted_new_outcomes": task.permitted_new_outcomes,
                }
            )

    task_root = run_dir / "structural_repair_tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    for index, task in enumerate(tasks, 1):
        (task_root / f"task_{index:02d}.json").write_text(
            task.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    manifest = {
        "task_build_version": "v12-structural-repair-tasks-1.0.0",
        "paper_id": support["paper_id"],
        "task_count": len(tasks),
        "tasks": task_metadata,
        "human_review_candidate_ids": human_review_ids,
        "contradiction_candidate_ids": sorted(
            row["candidate_id"]
            for row in coverage["candidates"]
            if row["verdict"] == "contradicted"
        ),
        "paid_api_requests": 0,
    }
    (task_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def run(
    *,
    paper_ids: list[str] | None = None,
    run_root: Path = RUN_ROOT,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    selected = set(paper_ids or [])
    rows = [
        build_for_run(run_dir)
        for run_dir in sorted(path for path in run_root.glob("GP-*") if path.is_dir())
        if (not selected or run_dir.name in selected)
        and (run_dir / "v12_structural_coverage.json").exists()
    ]
    summary = {
        "task_build_version": "v12-structural-repair-tasks-summary-1.0.0",
        "papers": rows,
        "task_count": sum(row["task_count"] for row in rows),
        "paid_api_requests": 0,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                paper_ids=args.paper_id,
                run_root=args.run_root,
                report_path=args.report_path,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
