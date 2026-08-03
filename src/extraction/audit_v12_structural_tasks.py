"""Audit prepared structural repair tasks without calling an AI service."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.extraction.build_v12_structural_repair_tasks import (
    DEFAULT_MODEL,
    _visual_object_id,
    estimate_input_tokens,
    estimate_worst_case_output_tokens,
)
from src.extraction.deterministic_coverage_v12 import (
    assess_candidate_eligibility,
)
from src.extraction.run_missing_record_repair import load_task
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "data/staging/extraction/v12_structural_primary_v6"
REPORT_PATH = (
    ROOT / "reports/extraction/v12_structural_primary_v6/task_audit.json"
)
GOLD_IDENTIFIER = re.compile(r"\bG[OX]-\d+\b")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def audit(run_root: Path = RUN_ROOT) -> dict[str, Any]:
    run_root = run_root.resolve()
    papers: list[dict[str, Any]] = []
    global_candidate_ids: set[str] = set()
    issues: list[str] = []
    for run_dir in sorted(path for path in run_root.glob("GP-*") if path.is_dir()):
        paper_id = run_dir.name
        preparation = json.loads(
            (run_dir / "preparation_manifest.json").read_text(encoding="utf-8")
        )
        unsigned_preparation = {
            key: value
            for key, value in preparation.items()
            if key != "manifest_checksum"
        }
        if _sha(_canonical(unsigned_preparation)) != preparation[
            "manifest_checksum"
        ]:
            issues.append(f"{paper_id}:preparation_manifest_checksum_mismatch")

        request = json.loads(
            (run_dir / "request.json").read_text(encoding="utf-8")
        )
        support = request["request_payload"]["outcome_recall_support"]
        candidate_by_id = {
            row.candidate_id: row
            for row in (
                AtomicOutcomeCandidateV12.model_validate(value)
                for value in support["atomic_outcome_candidates"]
            )
        }
        coverage = json.loads(
            (run_dir / "v12_structural_coverage.json").read_text(
                encoding="utf-8"
            )
        )
        expected_repair = {
            row["candidate_id"]
            for row in coverage["candidates"]
            if row["route"] == "bounded_repair_task"
        }
        expected_human = {
            row["candidate_id"]
            for row in coverage["candidates"]
            if row["route"] == "human_review"
        }
        expected_confirmed = {
            row["candidate_id"]
            for row in coverage["candidates"]
            if row["route"] == "none"
        }
        task_root = run_dir / "structural_repair_tasks"
        task_manifest = json.loads(
            (task_root / "manifest.json").read_text(encoding="utf-8")
        )
        task_paths = sorted(task_root.glob("task_*.json"))
        if len(task_paths) != task_manifest["task_count"]:
            issues.append(f"{paper_id}:task_manifest_count_mismatch")
        manifest_tasks = task_manifest.get("tasks", [])
        if len(manifest_tasks) != task_manifest["task_count"]:
            issues.append(f"{paper_id}:task_metadata_count_mismatch")
        oversized_ids = set(
            task_manifest.get("oversized_candidate_ids", [])
        )
        model = task_manifest.get("model", DEFAULT_MODEL)
        text_task_ids: set[str] = set()
        vision_task_ids: set[str] = set()
        scoped_ids: set[str] = set()
        scoped_evidence_ids: set[str] = set()
        task_rows = []
        for task_index, task_path in enumerate(task_paths):
            try:
                task = load_task(task_path)
            except Exception as exc:  # surfaced verbatim in the persisted audit
                issues.append(
                    f"{paper_id}:{task_path.name}:invalid_task:{exc}"
                )
                continue
            metadata = (
                manifest_tasks[task_index]
                if task_index < len(manifest_tasks)
                else {}
            )
            metadata_ids = set(metadata.get("candidate_ids", []))
            if metadata_ids != set(task.candidate_ids):
                issues.append(
                    f"{paper_id}:{task_path.name}:"
                    "task_metadata_scope_mismatch"
                )
            repair_route = metadata.get("repair_route")
            if repair_route == "text":
                text_task_ids |= set(task.candidate_ids)
            elif repair_route == "vision":
                vision_task_ids |= set(task.candidate_ids)
            else:
                issues.append(
                    f"{paper_id}:{task_path.name}:invalid_repair_route:"
                    f"{repair_route}"
                )
            estimated_input = metadata.get("estimated_input_tokens")
            estimated_output = metadata.get(
                "estimated_worst_case_output_tokens"
            )
            if (
                isinstance(estimated_input, bool)
                or not isinstance(estimated_input, int)
                or estimated_input < 0
                or estimated_input > 6_000
            ):
                issues.append(
                    f"{paper_id}:{task_path.name}:input_token_cap_exceeded"
                )
            if (
                isinstance(estimated_output, bool)
                or not isinstance(estimated_output, int)
                or estimated_output < 0
                or estimated_output > 4_000
            ):
                issues.append(
                    f"{paper_id}:{task_path.name}:output_token_cap_exceeded"
                )
            actual_input = estimate_input_tokens(task, model=model)
            actual_output = estimate_worst_case_output_tokens(task)
            if actual_input > 6_000:
                issues.append(
                    f"{paper_id}:{task_path.name}:"
                    "actual_input_token_cap_exceeded"
                )
            if actual_output > 4_000:
                issues.append(
                    f"{paper_id}:{task_path.name}:"
                    "actual_output_token_cap_exceeded"
                )
            expected_visual_objects = {
                _visual_object_id(candidate_by_id[candidate_id])
                for candidate_id in task.candidate_ids
                if candidate_id in candidate_by_id
            }
            if (
                len(expected_visual_objects) != 1
                or metadata.get("visual_object_id")
                != next(iter(expected_visual_objects), None)
            ):
                issues.append(
                    f"{paper_id}:{task_path.name}:"
                    "visual_object_scope_mismatch"
                )
            raw = task_path.read_text(encoding="utf-8")
            gold = sorted(set(GOLD_IDENTIFIER.findall(raw)))
            if gold:
                issues.append(
                    f"{paper_id}:{task_path.name}:gold_identifiers:{gold}"
                )
            duplicate = scoped_ids & set(task.candidate_ids)
            if duplicate:
                issues.append(
                    f"{paper_id}:{task_path.name}:duplicate_scope:"
                    f"{sorted(duplicate)}"
                )
            scoped_ids |= set(task.candidate_ids)
            scoped_evidence_ids |= {
                evidence_id
                for fact in task.candidate_facts
                for evidence_id in fact.evidence_ids
            }
            global_duplicate = global_candidate_ids & set(task.candidate_ids)
            if global_duplicate:
                issues.append(
                    f"{paper_id}:{task_path.name}:global_duplicate_scope:"
                    f"{sorted(global_duplicate)}"
                )
            global_candidate_ids |= set(task.candidate_ids)
            if len(task.candidate_ids) > 8 or len(task.evidence) > 12:
                issues.append(f"{paper_id}:{task_path.name}:cap_exceeded")
            if set(task.candidate_ids) != {
                row.candidate_id for row in task.candidate_facts
            }:
                issues.append(
                    f"{paper_id}:{task_path.name}:candidate_fact_scope_mismatch"
                )
            for candidate_id in task.candidate_ids:
                candidate = candidate_by_id.get(candidate_id)
                if candidate is None:
                    issues.append(
                        f"{paper_id}:{task_path.name}:unknown_candidate:"
                        f"{candidate_id}"
                    )
                    continue
                assessment = assess_candidate_eligibility(candidate)
                if not assessment["eligible"]:
                    issues.append(
                        f"{paper_id}:{task_path.name}:ineligible_candidate:"
                        f"{candidate_id}:{assessment['reasons']}"
                    )
                if (
                    candidate.provisional_experiment_id
                    != task.experiment_context.provisional_experiment_id
                ):
                    issues.append(
                        f"{paper_id}:{task_path.name}:experiment_scope_mismatch:"
                        f"{candidate_id}"
                    )
                expected_route = (
                    "vision"
                    if candidate.route_hint == "vision"
                    else "text"
                )
                if repair_route != expected_route:
                    issues.append(
                        f"{paper_id}:{task_path.name}:route_mismatch:"
                        f"{candidate_id}"
                    )
            task_rows.append(
                {
                    "path": str(
                        task_path.relative_to(
                            ROOT
                            if task_path.is_relative_to(ROOT)
                            else run_root
                        )
                    ),
                    "sha256": _sha(task_path.read_bytes()),
                    "task_checksum": task.task_checksum,
                    "provisional_experiment_id": (
                        task.experiment_context.provisional_experiment_id
                    ),
                    "candidate_count": len(task.candidate_ids),
                    "evidence_count": len(task.evidence),
                    "vision_candidate_count": sum(
                        candidate.route_hint == "vision"
                        for candidate_id in task.candidate_ids
                        if (
                            candidate := candidate_by_id.get(candidate_id)
                        )
                        is not None
                    ),
                    "repair_route": repair_route,
                    "visual_object_id": metadata.get("visual_object_id"),
                    "estimated_input_tokens": estimated_input,
                    "estimated_worst_case_output_tokens": estimated_output,
                    "actual_input_tokens": actual_input,
                    "actual_worst_case_output_tokens": actual_output,
                }
            )
        routed_repair_ids = (
            text_task_ids | vision_task_ids | oversized_ids
        )
        if routed_repair_ids != expected_repair:
            issues.append(
                f"{paper_id}:repair_scope_mismatch:"
                f"missing={sorted(expected_repair - routed_repair_ids)}:"
                f"extra={sorted(routed_repair_ids - expected_repair)}"
            )
        if text_task_ids & vision_task_ids:
            issues.append(f"{paper_id}:text_vision_scope_overlap")
        if (
            (text_task_ids | vision_task_ids) & oversized_ids
            or oversized_ids & (expected_human | expected_confirmed)
        ):
            issues.append(f"{paper_id}:oversized_scope_overlap")
        if scoped_ids & (expected_human | expected_confirmed):
            issues.append(f"{paper_id}:nonrepair_candidate_in_task")
        coverage_ids = {
            row["candidate_id"] for row in coverage["candidates"]
        }
        conserved_ids = (
            text_task_ids
            | vision_task_ids
            | oversized_ids
            | expected_human
            | expected_confirmed
        )
        if conserved_ids != coverage_ids:
            issues.append(
                f"{paper_id}:candidate_conservation_mismatch:"
                f"missing={sorted(coverage_ids - conserved_ids)}:"
                f"extra={sorted(conserved_ids - coverage_ids)}"
            )
        visual_evidence = {
            row["evidence_id"]
            for row in support.get("accepted_visual_claims", [])
        }
        visual_confirmed = {
            evidence_id
            for candidate_id in expected_confirmed
            for evidence_id in candidate_by_id[candidate_id].evidence_ids
        }
        oversized_evidence = {
            evidence_id
            for candidate_id in oversized_ids
            if candidate_id in candidate_by_id
            for evidence_id in candidate_by_id[candidate_id].evidence_ids
        }
        if not visual_evidence <= (
            scoped_evidence_ids | oversized_evidence | visual_confirmed
        ):
            issues.append(f"{paper_id}:accepted_visual_claim_not_accounted_for")
        papers.append(
            {
                "paper_id": paper_id,
                "task_count": len(task_rows),
                "repair_candidate_count": len(expected_repair),
                "text_task_candidate_count": len(text_task_ids),
                "vision_task_candidate_count": len(vision_task_ids),
                "oversized_candidate_count": len(oversized_ids),
                "human_review_candidate_count": len(expected_human),
                "confirmed_candidate_count": len(expected_confirmed),
                "tasks": task_rows,
            }
        )
    return {
        "audit_version": "v12-structural-task-audit-1.0.0",
        "run_root": str(run_root),
        "papers": papers,
        "task_count": sum(row["task_count"] for row in papers),
        "repair_candidate_count": sum(
            row["repair_candidate_count"] for row in papers
        ),
        "issues": issues,
        "passed": not issues,
        "generation_requests": 0,
        "paid_api_requests": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = audit(args.run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
