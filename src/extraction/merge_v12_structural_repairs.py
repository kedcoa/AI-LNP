"""Merge v1.2 repair fragments only after deterministic fact verification."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.extraction.compact_validation import validate_candidate
from src.extraction.deterministic_coverage_v12 import (
    evaluate_structural_coverage,
)
from src.extraction.missing_record_contracts import MissingRecordFragment
from src.extraction.run_missing_record_repair import load_task, validate_response
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12
from src.rag.compact_api_packet import CompactApiPacket


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def merge(
    *,
    result_path: Path,
    packet_path: Path,
    support_path: Path,
    pairs: list[tuple[Path, Path]],
    output_path: Path,
    preparation_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Write a pending merged result only after recovered facts are confirmed."""

    if output_path.exists():
        raise FileExistsError("Refusing to overwrite an existing merged result")
    source_bytes = result_path.read_bytes()
    source = json.loads(source_bytes)
    merged = deepcopy(source)
    packet = CompactApiPacket.model_validate_json(
        packet_path.read_text(encoding="utf-8")
    )
    unsigned_packet = packet.model_dump(
        mode="json", exclude={"packet_checksum"}, exclude_none=True
    )
    if packet.packet_checksum != _sha(_canonical(unsigned_packet)):
        raise ValueError("Compact packet checksum mismatch")
    support = json.loads(support_path.read_text(encoding="utf-8"))
    if source.get("paper_id") != packet.paper_id:
        raise ValueError("Result and packet paper IDs differ")
    if support.get("paper_id") != packet.paper_id:
        raise ValueError("Support and packet paper IDs differ")
    support_sha = _sha(_canonical(support))
    candidate_by_id = {
        row.candidate_id: row
        for row in (
            AtomicOutcomeCandidateV12.model_validate(value)
            for value in support.get("atomic_outcome_candidates", [])
        )
    }

    existing_experiment_ids = {
        row["experiment_id"] for row in merged.get("experiments", [])
    }
    existing_outcome_ids = {
        row["outcome_id"] for row in merged.get("outcomes", [])
    }
    new_experiment_ids: set[str] = set()
    new_outcome_ids: set[str] = set()
    recovered_candidate_ids: set[str] = set()
    unresolved_candidate_ids: set[str] = set()
    allowed_evidence_ids = {row.evidence_id for row in packet.evidence}
    if preparation_manifest_path is not None:
        preparation = json.loads(
            preparation_manifest_path.read_text(encoding="utf-8")
        )
        manifest_checksum = preparation.pop("manifest_checksum", None)
        if manifest_checksum != _sha(_canonical(preparation)):
            raise ValueError("Preparation manifest checksum mismatch")
        if preparation.get("paper_id") != packet.paper_id:
            raise ValueError("Preparation manifest belongs to another paper")
        if preparation.get("source_result_sha256") != _sha(source_bytes):
            raise ValueError(
                "Preparation manifest was built from another source result"
            )
        if preparation.get("support_sha256") != support_sha:
            raise ValueError(
                "Preparation manifest was built from different v1.2 support"
            )
        if preparation.get("packet_checksum") != packet.packet_checksum:
            raise ValueError(
                "Preparation manifest was built from another compact packet"
            )
        allowed_evidence_ids |= set(
            preparation.get("verified_source_evidence_ids", [])
        )
    inputs = []
    seen_task_candidate_ids: set[str] = set()

    for task_path, fragment_path in pairs:
        task = load_task(task_path)
        fragment = MissingRecordFragment.model_validate_json(
            fragment_path.read_text(encoding="utf-8")
        )
        validate_response(fragment, task)
        if task.paper_id != packet.paper_id:
            raise ValueError("Task belongs to a different paper")
        if task.source_result_sha256 != _sha(source_bytes):
            raise ValueError("Task was built from a different source result")
        if task.source_inventory_sha256 != support_sha:
            raise ValueError("Task was built from different v1.2 support")
        if not set(task.candidate_ids) <= set(candidate_by_id):
            raise ValueError("Task cites a candidate absent from v1.2 support")
        duplicate_task_candidates = (
            seen_task_candidate_ids & set(task.candidate_ids)
        )
        if duplicate_task_candidates:
            raise ValueError(
                "Candidate appears in more than one repair task: "
                f"{sorted(duplicate_task_candidates)}"
            )
        seen_task_candidate_ids |= set(task.candidate_ids)

        fragment_experiment_ids = {
            row.experiment_id for row in fragment.experiments
        }
        fragment_outcome_ids = {row.outcome_id for row in fragment.outcomes}
        if (
            existing_experiment_ids & fragment_experiment_ids
            or new_experiment_ids & fragment_experiment_ids
        ):
            raise ValueError("Experiment ID collision across repair fragments")
        if (
            existing_outcome_ids & fragment_outcome_ids
            or new_outcome_ids & fragment_outcome_ids
        ):
            raise ValueError("Outcome ID collision across repair fragments")
        referenced_new_experiments = {
            row.experiment_id
            for row in fragment.outcomes
            if row.experiment_id in fragment_experiment_ids
        }
        if referenced_new_experiments != fragment_experiment_ids:
            raise ValueError("Every new experiment must have a new outcome")

        merged["experiments"].extend(
            row.model_dump(mode="json") for row in fragment.experiments
        )
        merged["outcomes"].extend(
            row.model_dump(mode="json") for row in fragment.outcomes
        )
        new_experiment_ids |= fragment_experiment_ids
        new_outcome_ids |= fragment_outcome_ids
        recovered_candidate_ids |= set(fragment.recovered_candidate_ids)
        unresolved_candidate_ids |= set(fragment.unresolved_candidate_ids)
        allowed_evidence_ids |= {
            row.evidence_id for row in task.evidence
        }
        inputs.append(
            {
                "task_path": str(task_path),
                "fragment_path": str(fragment_path),
                "recovered_candidate_ids": fragment.recovered_candidate_ids,
                "unresolved_candidate_ids": fragment.unresolved_candidate_ids,
            }
        )

    if recovered_candidate_ids & unresolved_candidate_ids:
        raise ValueError("Candidate dispositions conflict across fragments")
    parsed, validation = validate_candidate(
        json.dumps(merged, ensure_ascii=False),
        paper_id=packet.paper_id,
        allowed_evidence_ids=allowed_evidence_ids,
    )
    if parsed is None or validation.status != "valid":
        raise ValueError(
            "Proposed structural merge failed compact validation: "
            + "; ".join(row.message for row in validation.findings)
        )

    task_candidate_ids = recovered_candidate_ids | unresolved_candidate_ids
    structural = evaluate_structural_coverage(
        candidates=[
            candidate_by_id[candidate_id]
            for candidate_id in sorted(task_candidate_ids)
        ],
        provisional_experiments=support.get("provisional_experiments", []),
        result=parsed.model_dump(mode="json"),
    )
    report_by_candidate = {
        row["candidate_id"]: row for row in structural["candidates"]
    }
    unverified_recovered = sorted(
        candidate_id
        for candidate_id in recovered_candidate_ids
        if report_by_candidate[candidate_id]["verdict"] != "confirmed"
    )
    incorrectly_unresolved = sorted(
        candidate_id
        for candidate_id in unresolved_candidate_ids
        if report_by_candidate[candidate_id]["verdict"] == "confirmed"
    )
    confirmed_new_outcome_ids = {
        str(row["selected_assessment"]["output_outcome_id"])
        for row in structural["candidates"]
        if row["candidate_id"] in recovered_candidate_ids
        and row["verdict"] == "confirmed"
        and row["selected_assessment"] is not None
    }
    unrelated_new_outcome_ids = sorted(
        new_outcome_ids - confirmed_new_outcome_ids
    )
    if unverified_recovered:
        raise ValueError(
            "Recovered candidates failed structural verification: "
            f"{unverified_recovered}"
        )
    if incorrectly_unresolved:
        raise ValueError(
            "Candidates declared unresolved are structurally confirmed: "
            f"{incorrectly_unresolved}"
        )
    if unrelated_new_outcome_ids:
        raise ValueError(
            "New outcomes do not confirm a recovered candidate: "
            f"{unrelated_new_outcome_ids}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    report = {
        "merge_version": "v12-structural-repair-merge-1.0.0",
        "paper_id": packet.paper_id,
        "source_result_sha256": _sha(source_bytes),
        "support_sha256": support_sha,
        "inputs": inputs,
        "recovered_candidate_ids": sorted(recovered_candidate_ids),
        "unresolved_candidate_ids": sorted(unresolved_candidate_ids),
        "new_experiment_ids": sorted(new_experiment_ids),
        "new_outcome_ids": sorted(new_outcome_ids),
        "validation_status": validation.status,
        "structural_verification_passed": True,
        "structural_coverage": structural,
        "integration_blocked": bool(unresolved_candidate_ids),
        "finalization_allowed": not unresolved_candidate_ids,
        "paid_api_requests": 0,
    }
    (output_path.parent / "v12_structural_merge_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
