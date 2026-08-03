"""Build bounded, experiment-scoped repair tasks from structural coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from src.extraction.missing_record_contracts import (
    MissingRecordCandidateFact,
    MissingRecordExperimentContext,
    MissingRecordExperimentSummary,
    MissingRecordOutcomeSummary,
    MissingRecordTask,
)
from src.extraction.repair_contracts import RepairEvidence
from src.extraction.run_missing_record_repair import build_openai_request
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12
from src.rag.compact_api_packet import estimate_tokens


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "data/staging/extraction/compact_one_call_v1_2"
REPORT_PATH = (
    ROOT / "reports/extraction/v12_structural_repair_tasks/summary.json"
)
DEFAULT_MODEL = "gpt-5.6-terra"


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


def _reported_value(row: dict[str, Any], field_name: str) -> Any:
    field = row.get(field_name)
    return field.get("value") if isinstance(field, dict) else None


def compact_outcome_summaries(
    result: dict[str, Any],
) -> list[MissingRecordOutcomeSummary]:
    """Project existing outcomes without evidence wrappers or narrative."""

    return [
        MissingRecordOutcomeSummary(
            outcome_id=row["outcome_id"],
            experiment_id=row["experiment_id"],
            assay=_reported_value(row, "assay"),
            endpoint=_reported_value(row, "endpoint"),
            comparator=_reported_value(row, "comparator"),
            qualitative_outcome=_reported_value(
                row, "qualitative_outcome"
            ),
        )
        for row in result.get("outcomes", [])
    ]


def compact_experiment_summaries(
    result: dict[str, Any],
) -> list[MissingRecordExperimentSummary]:
    """Project every existing experiment plus its linked outcome context."""

    outcomes_by_experiment: dict[str, list[dict[str, Any]]] = defaultdict(
        list
    )
    for row in result.get("outcomes", []):
        outcomes_by_experiment[row["experiment_id"]].append(row)
    summaries = []
    for row in result.get("experiments", []):
        linked = outcomes_by_experiment[row["experiment_id"]]
        summaries.append(
            MissingRecordExperimentSummary(
                experiment_id=row["experiment_id"],
                formulation_id=row["formulation_id"],
                payload_type=_reported_value(row, "payload_type"),
                payload_name=_reported_value(row, "payload_name"),
                encoded_product=_reported_value(row, "encoded_product"),
                molecular_target=_reported_value(row, "molecular_target"),
                delivery_recipient_cell=_reported_value(
                    row, "delivery_recipient_cell"
                ),
                therapeutic_target_cell=_reported_value(
                    row, "therapeutic_target_cell"
                ),
                tissue_or_organ=_reported_value(row, "tissue_or_organ"),
                species=_reported_value(row, "species"),
                disease_model=_reported_value(row, "disease_model"),
                experimental_context=_reported_value(
                    row, "experimental_context"
                ),
                dose=_reported_value(row, "dose"),
                dose_unit=_reported_value(row, "dose_unit"),
                route=_reported_value(row, "route"),
                timepoint=_reported_value(row, "timepoint"),
                timepoint_unit=_reported_value(row, "timepoint_unit"),
                outcome_endpoints=list(
                    dict.fromkeys(
                        value
                        for outcome_row in linked
                        if (
                            value := _reported_value(
                                outcome_row, "endpoint"
                            )
                        )
                        is not None
                    )
                ),
                comparator_context=list(
                    dict.fromkeys(
                        value
                        for outcome_row in linked
                        if (
                            value := _reported_value(
                                outcome_row, "comparator"
                            )
                        )
                        is not None
                    )
                ),
            )
        )
    return summaries


def estimate_input_tokens(
    task: MissingRecordTask,
    *,
    model: str,
) -> int:
    """Measure the serialized exact request used by generation."""

    return estimate_tokens(build_openai_request(task, model=model))


def estimate_worst_case_output_tokens(task: MissingRecordTask) -> int:
    return (
        600
        + 650 * len(task.candidate_ids)
        + 500 * task.permitted_new_experiments
    )


def _repair_route(candidate: AtomicOutcomeCandidateV12) -> str:
    return "vision" if candidate.route_hint == "vision" else "text"


def _visual_object_id(
    candidate: AtomicOutcomeCandidateV12,
) -> str | None:
    if _repair_route(candidate) != "vision":
        return None
    source_id = candidate.source_ids[0]
    return source_id.partition(":table-")[0]


def _within_static_caps(
    candidates: list[AtomicOutcomeCandidateV12],
) -> bool:
    return len(candidates) <= 8 and len(
        {
            evidence_id
            for candidate in candidates
            for evidence_id in candidate.evidence_ids
        }
    ) <= 12


def pack_candidate_tasks(
    candidates: list[AtomicOutcomeCandidateV12],
    *,
    task_factory: Callable[
        [list[AtomicOutcomeCandidateV12]], MissingRecordTask
    ],
    model: str,
    input_limit: int = 6_000,
    output_limit: int = 4_000,
) -> tuple[list[MissingRecordTask], list[str]]:
    """Greedily pack complete tasks within measured request limits."""

    grouped: dict[
        tuple[str, str, str], list[AtomicOutcomeCandidateV12]
    ] = defaultdict(list)
    for candidate in candidates:
        if candidate.provisional_experiment_id is None:
            raise ValueError(
                f"{candidate.candidate_id} cannot be queued without an "
                "experiment"
            )
        grouped[
            (
                _repair_route(candidate),
                candidate.provisional_experiment_id,
                _visual_object_id(candidate) or "",
            )
        ].append(candidate)

    tasks: list[MissingRecordTask] = []
    oversized: list[str] = []
    for partition in sorted(grouped):
        current: list[AtomicOutcomeCandidateV12] = []
        accepted_task: MissingRecordTask | None = None
        for candidate in sorted(
            grouped[partition], key=lambda row: row.candidate_id
        ):
            proposed = [*current, candidate]
            proposed_task = (
                task_factory(proposed)
                if _within_static_caps(proposed)
                else None
            )
            proposed_fits = (
                proposed_task is not None
                and estimate_input_tokens(
                    proposed_task,
                    model=model,
                )
                <= input_limit
                and estimate_worst_case_output_tokens(proposed_task)
                <= output_limit
            )
            if proposed_fits:
                current = proposed
                accepted_task = proposed_task
                continue
            if accepted_task is not None:
                tasks.append(accepted_task)
            current = []
            accepted_task = None

            single = [candidate]
            single_task = (
                task_factory(single)
                if _within_static_caps(single)
                else None
            )
            if (
                single_task is None
                or estimate_input_tokens(single_task, model=model)
                > input_limit
                or estimate_worst_case_output_tokens(single_task)
                > output_limit
            ):
                oversized.append(candidate.candidate_id)
                continue
            current = single
            accepted_task = single_task
        if accepted_task is not None:
            tasks.append(accepted_task)
    return tasks, sorted(oversized)


def build_for_run(
    run_dir: Path,
    *,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
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
    repair_candidates = [
        candidate_by_id[candidate_id] for candidate_id in sorted(repair_ids)
    ]

    provisional_by_id = {
        row["provisional_experiment_id"]: row
        for row in support["provisional_experiments"]
    }
    evidence_by_id = _evidence_map(request)
    source_inventory_sha = _sha(_canonical(support))
    experiment_summaries = compact_experiment_summaries(result)
    outcome_summaries = compact_outcome_summaries(result)

    def task_factory(
        rows: list[AtomicOutcomeCandidateV12],
    ) -> MissingRecordTask:
        provisional_id = rows[0].provisional_experiment_id
        if provisional_id is None:
            raise ValueError(
                f"{rows[0].candidate_id} cannot be queued without an "
                "experiment"
            )
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
            "task_version": "missing-record-task-1.2.0",
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
                row["outcome_id"] for row in result.get("outcomes", [])
            ],
            "existing_experiment_summaries": [
                row.model_dump(mode="json")
                for row in experiment_summaries
            ],
            "existing_outcome_summaries": [
                row.model_dump(mode="json") for row in outcome_summaries
            ],
            "permitted_new_experiments": 1,
            "permitted_new_outcomes": min(
                8, max(1, len(candidate_ids) * 2)
            ),
            "source_result_sha256": _sha(result_bytes),
            "source_inventory_sha256": source_inventory_sha,
        }
        return MissingRecordTask.model_validate(
            {
                **unsigned,
                "task_checksum": _sha(_canonical(unsigned)),
            }
        )

    tasks, oversized_candidate_ids = pack_candidate_tasks(
        repair_candidates,
        task_factory=task_factory,
        model=model,
    )
    task_metadata = []
    for task in tasks:
        candidates = [
            candidate_by_id[candidate_id]
            for candidate_id in task.candidate_ids
        ]
        first = candidates[0]
        task_metadata.append(
            {
                "provisional_experiment_id": (
                    first.provisional_experiment_id
                ),
                "candidate_ids": task.candidate_ids,
                "candidate_count": len(task.candidate_ids),
                "candidate_facts_included": True,
                "experiment_label": task.experiment_context.label,
                "evidence_ids": [
                    row.evidence_id for row in task.evidence
                ],
                "permitted_new_experiments": (
                    task.permitted_new_experiments
                ),
                "permitted_new_outcomes": task.permitted_new_outcomes,
                "repair_route": _repair_route(first),
                "visual_object_id": _visual_object_id(first),
                "estimated_input_tokens": estimate_input_tokens(
                    task, model=model
                ),
                "estimated_worst_case_output_tokens": (
                    estimate_worst_case_output_tokens(task)
                ),
            }
        )

    task_root = run_dir / "structural_repair_tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    for stale_path in task_root.glob("task_*.json"):
        stale_path.unlink()
    for index, task in enumerate(tasks, 1):
        (task_root / f"task_{index:02d}.json").write_text(
            task.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    manifest = {
        "task_build_version": "v12-structural-repair-tasks-1.0.0",
        "paper_id": support["paper_id"],
        "model": model,
        "task_count": len(tasks),
        "tasks": task_metadata,
        "human_review_candidate_ids": human_review_ids,
        "oversized_candidate_ids": oversized_candidate_ids,
        "visual_candidate_ids": sorted(
            row.candidate_id
            for row in repair_candidates
            if _repair_route(row) == "vision"
        ),
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
