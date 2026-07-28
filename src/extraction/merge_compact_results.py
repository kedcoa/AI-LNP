"""Deterministically merge Day 4 repair and vision fragments into one result."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.extraction.compact_validation import (
    ValidationFinding,
    ValidationReport,
    validate_candidate,
)
from src.extraction.assess_outcome_complexity import assess
from src.extraction.build_outcome_candidates import build_candidates
from src.extraction.check_outcome_coverage import check as check_outcome_coverage
from src.extraction.repair_contracts import RepairResponse, RepairTask
from src.extraction.run_narrow_repair import load_task as load_repair_task
from src.extraction.run_narrow_repair import validate_response as validate_repair
from src.extraction.run_selective_vision import load_task as load_vision_task
from src.extraction.run_selective_vision import validate_response as validate_vision
from src.extraction.selective_vision_contracts import (
    SelectiveVisionResponse,
    SelectiveVisionTask,
)
from src.rag.compact_api_packet import CompactApiPacket


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data" / "staging" / "extraction" / "compact_merged_v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MergeInput(StrictModel):
    route: Literal["repair", "vision"]
    finding_id: str
    disposition: str
    task_path: str
    result_path: str
    applied: bool
    reason: str


class MergeReport(StrictModel):
    merge_version: Literal["compact-merge-1.0.0"] = "compact-merge-1.0.0"
    paper_id: str
    status: Literal["merged_valid", "unresolved"]
    source_candidate_sha256: str
    source_validation_status: Literal["valid", "invalid"]
    inputs: list[MergeInput]
    unresolved_finding_ids: list[str]
    outcome_coverage_status: (
        Literal["complete", "review_unmatched_groups", "not_applicable"] | None
    )
    unresolved_outcome_candidate_ids: list[str]
    final_validation_status: Literal["valid", "invalid"]
    final_validation_findings: list[ValidationFinding]
    final_result_path: str | None


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_packet(path: Path) -> CompactApiPacket:
    packet = CompactApiPacket.model_validate_json(path.read_text(encoding="utf-8"))
    unsigned = packet.model_dump(
        mode="json", exclude={"packet_checksum"}, exclude_none=True
    )
    canonical = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if _sha256(canonical) != packet.packet_checksum:
        raise ValueError("Compact API packet checksum mismatch")
    return packet


def _finding_map(report: ValidationReport) -> dict[str, ValidationFinding]:
    rows = {row.finding_id: row for row in report.findings}
    if len(rows) != len(report.findings):
        raise ValueError("Validation report contains duplicate finding IDs")
    return rows


def _assert_same_finding(
    task_finding: ValidationFinding,
    report_finding: ValidationFinding,
) -> None:
    if task_finding != report_finding:
        raise ValueError(
            f"Task finding {task_finding.finding_id} does not match validation report"
        )
    if not report_finding.repairable:
        raise ValueError(f"Finding {report_finding.finding_id} is not field-repairable")


def _replace_field(
    candidate: dict[str, Any],
    finding: ValidationFinding,
    fragment: dict[str, Any],
) -> None:
    collection = finding.record_collection
    index = finding.record_index
    field_name = finding.field_name
    assert collection is not None and index is not None and field_name is not None
    if set(fragment) != {field_name}:
        raise ValueError(
            f"Finding {finding.finding_id} may replace exactly {field_name!r}"
        )
    rows = candidate.get(collection)
    if not isinstance(rows, list) or index >= len(rows):
        raise ValueError(f"Finding {finding.finding_id} points outside the candidate")
    if not isinstance(rows[index], dict) or field_name not in rows[index]:
        raise ValueError(f"Finding {finding.finding_id} field is absent from candidate")
    rows[index][field_name] = deepcopy(fragment[field_name])


def merge_results(
    *,
    candidate_path: Path,
    validation_report_path: Path,
    packet_path: Path,
    repair_pairs: list[tuple[Path, Path]] | None = None,
    vision_pairs: list[tuple[Path, Path]] | None = None,
    output_root: Path = OUTPUT_ROOT,
) -> MergeReport:
    candidate_bytes = candidate_path.read_bytes()
    candidate = json.loads(candidate_bytes)
    report = ValidationReport.model_validate_json(
        validation_report_path.read_text(encoding="utf-8")
    )
    packet = _load_packet(packet_path)
    paper_id = candidate.get("paper_id")
    if not isinstance(paper_id, str) or paper_id != report.paper_id:
        raise ValueError("Candidate and validation report paper IDs do not match")
    if paper_id != packet.paper_id:
        raise ValueError("Candidate and compact API packet paper IDs do not match")

    source_sha = _sha256(candidate_bytes)
    findings = _finding_map(report)
    applied_findings: set[str] = set()
    allowed_evidence_ids = {row.evidence_id for row in packet.evidence}
    inputs: list[MergeInput] = []

    for task_path, result_path in repair_pairs or []:
        task: RepairTask = load_repair_task(task_path)
        result = RepairResponse.model_validate_json(result_path.read_text(encoding="utf-8"))
        if task.paper_id != paper_id:
            raise ValueError("Repair task paper ID does not match candidate")
        if task.source_candidate_sha256 != source_sha:
            raise ValueError("Repair task was built from a different candidate")
        finding = findings.get(task.finding.finding_id)
        if finding is None:
            raise ValueError("Repair task finding is absent from validation report")
        _assert_same_finding(task.finding, finding)
        validate_repair(result, task)
        if result.finding_id in applied_findings:
            raise ValueError(f"Conflicting results for finding {result.finding_id}")
        applied = result.disposition == "corrected"
        reason = (
            "validated corrected fragment applied"
            if applied
            else f"explicit {result.disposition} disposition; no field applied"
        )
        if applied:
            assert result.corrected_fragment is not None
            _replace_field(candidate, finding, result.corrected_fragment)
            applied_findings.add(result.finding_id)
        inputs.append(
            MergeInput(
                route="repair",
                finding_id=result.finding_id,
                disposition=result.disposition,
                task_path=str(task_path),
                result_path=str(result_path),
                applied=applied,
                reason=reason,
            )
        )

    for task_path, result_path in vision_pairs or []:
        task: SelectiveVisionTask = load_vision_task(task_path)
        result = SelectiveVisionResponse.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        if task.paper_id != paper_id:
            raise ValueError("Vision task paper ID does not match candidate")
        finding = findings.get(task.finding.finding_id)
        if finding is None:
            raise ValueError("Vision task finding is absent from validation report")
        _assert_same_finding(task.finding, finding)
        validate_vision(result, task)
        if result.finding_id in applied_findings:
            raise ValueError(f"Conflicting results for finding {result.finding_id}")
        safe_resolution = (
            result.disposition == "resolved"
            and result.value_status in {"exact_reported", "derived"}
            and not result.requires_human_review
        )
        reason = (
            "validated exact/derived visual fragment applied"
            if safe_resolution
            else "visual result remains unresolved or requires human review"
        )
        if safe_resolution:
            assert result.corrected_fragment is not None
            _replace_field(candidate, finding, result.corrected_fragment)
            applied_findings.add(result.finding_id)
            allowed_evidence_ids.add(task.crop_evidence_id)
        inputs.append(
            MergeInput(
                route="vision",
                finding_id=result.finding_id,
                disposition=result.disposition,
                task_path=str(task_path),
                result_path=str(result_path),
                applied=safe_resolution,
                reason=reason,
            )
        )

    parsed, final_validation = validate_candidate(
        json.dumps(candidate, ensure_ascii=False),
        paper_id=paper_id,
        allowed_evidence_ids=allowed_evidence_ids,
    )
    coverage = None
    if parsed is not None:
        assessment = assess(packet)
        if (
            assessment.route == "complex"
            and parsed.eligibility.decision == "eligible"
        ):
            coverage = check_outcome_coverage(
                packet,
                parsed.model_dump(mode="json"),
                assessment=assessment,
                candidates=build_candidates(packet),
            )
    unresolved = sorted(set(findings) - applied_findings)
    run_dir = output_root / paper_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "final_result.json"
    coverage_complete = coverage is None or coverage.status == "complete"
    if parsed is not None and not unresolved and coverage_complete:
        result_path.write_text(
            json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        status: Literal["merged_valid", "unresolved"] = "merged_valid"
        final_result_path: str | None = str(result_path)
    else:
        if result_path.exists():
            raise FileExistsError(
                "A prior final_result.json exists, but this merge is unresolved"
            )
        status = "unresolved"
        final_result_path = None

    merge_report = MergeReport(
        paper_id=paper_id,
        status=status,
        source_candidate_sha256=source_sha,
        source_validation_status=report.status,
        inputs=inputs,
        unresolved_finding_ids=unresolved,
        outcome_coverage_status=coverage.status if coverage else None,
        unresolved_outcome_candidate_ids=(
            [
                row.candidate_id
                for row in [
                    *coverage.unmatched_candidates,
                    *coverage.review_candidates,
                ]
            ]
            if coverage
            else []
        ),
        final_validation_status=final_validation.status,
        final_validation_findings=final_validation.findings,
        final_result_path=final_result_path,
    )
    (run_dir / "merge_report.json").write_text(
        merge_report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return merge_report


def _pair(values: list[list[Path]]) -> list[tuple[Path, Path]]:
    return [(value[0], value[1]) for value in values]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge validated Day 4 field corrections into one compact result."
    )
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument(
        "--repair",
        type=Path,
        nargs=2,
        action="append",
        default=[],
        metavar=("TASK_JSON", "RESULT_JSON"),
    )
    parser.add_argument(
        "--vision",
        type=Path,
        nargs=2,
        action="append",
        default=[],
        metavar=("TASK_JSON", "RESULT_JSON"),
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    merged = merge_results(
        candidate_path=args.candidate,
        validation_report_path=args.validation_report,
        packet_path=args.packet,
        repair_pairs=_pair(args.repair),
        vision_pairs=_pair(args.vision),
        output_root=args.output_root,
    )
    print(merged.model_dump_json(indent=2))
    if merged.status != "merged_valid":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
