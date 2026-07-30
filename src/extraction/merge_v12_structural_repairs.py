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
        row["experiment_id"] for row in source.get("experiments", [])
    }
    existing_outcome_ids = {
        row["outcome_id"] for row in source.get("outcomes", [])
    }
    existing_outcome_experiments = {
        row["outcome_id"]: row["experiment_id"]
        for row in source.get("outcomes", [])
    }
    new_experiment_ids: set[str] = set()
    new_outcome_ids: set[str] = set()
    new_experiments: list[dict[str, Any]] = []
    new_outcomes: list[dict[str, Any]] = []
    candidate_resolutions: list[dict[str, Any]] = []
    resolution_by_candidate: dict[str, dict[str, Any]] = {}
    resolution_outcome_task_candidates: dict[str, set[str]] = {}
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

        fragment_experiments = [
            row.model_dump(mode="json") for row in fragment.experiments
        ]
        fragment_outcomes = [
            row.model_dump(mode="json") for row in fragment.outcomes
        ]
        fragment_outcome_experiments = {
            row["outcome_id"]: row["experiment_id"]
            for row in fragment_outcomes
        }
        if fragment.candidate_resolutions:
            resolution_rows = [
                row.model_dump(mode="json")
                for row in fragment.candidate_resolutions
            ]
            resolution_ids = [row["candidate_id"] for row in resolution_rows]
            if len(set(resolution_ids)) != len(resolution_ids):
                raise ValueError("candidate resolution IDs must be unique")
            if set(resolution_ids) != set(task.candidate_ids):
                raise ValueError(
                    "Every task candidate requires one candidate resolution"
                )
            known_outcome_experiments = {
                **existing_outcome_experiments,
                **fragment_outcome_experiments,
            }
            known_experiments = (
                existing_experiment_ids | fragment_experiment_ids
            )
            recovered_resolutions = {
                row["candidate_id"]
                for row in resolution_rows
                if row["status"] != "unresolved"
            }
            unresolved_resolutions = set(resolution_ids) - recovered_resolutions
            if recovered_resolutions != set(fragment.recovered_candidate_ids):
                raise ValueError(
                    "Recovered candidate IDs must agree with candidate resolutions"
                )
            if unresolved_resolutions != set(
                fragment.unresolved_candidate_ids
            ):
                raise ValueError(
                    "Unresolved candidate IDs must agree with candidate resolutions"
                )
            for resolution in resolution_rows:
                outcome_ids = set(resolution["outcome_ids"])
                experiment_ids = set(resolution["experiment_ids"])
                if resolution["status"] == "unresolved":
                    if outcome_ids or experiment_ids:
                        raise ValueError(
                            "Unresolved candidate resolution cannot reference "
                            "an outcome or experiment"
                        )
                    continue
                if not outcome_ids or not experiment_ids:
                    raise ValueError(
                        "Recovered candidate resolution requires outcome and "
                        "experiment links"
                    )
                unknown_outcomes = outcome_ids - set(
                    known_outcome_experiments
                )
                if unknown_outcomes:
                    raise ValueError(
                        "candidate resolution references an unknown outcome: "
                        f"{sorted(unknown_outcomes)}"
                    )
                unknown_experiments = experiment_ids - known_experiments
                if unknown_experiments:
                    raise ValueError(
                        "candidate resolution references an unknown experiment: "
                        f"{sorted(unknown_experiments)}"
                    )
                wrong_experiment_outcomes = sorted(
                    outcome_id
                    for outcome_id in outcome_ids
                    if known_outcome_experiments[outcome_id]
                    not in experiment_ids
                )
                if wrong_experiment_outcomes:
                    raise ValueError(
                        "candidate resolution outcome has the wrong experiment "
                        f"link: {wrong_experiment_outcomes}"
                    )
                outcome_linked_experiments = {
                    known_outcome_experiments[outcome_id]
                    for outcome_id in outcome_ids
                }
                if outcome_linked_experiments != experiment_ids:
                    raise ValueError(
                        "Every candidate resolution experiment requires a "
                        "distinct linked outcome"
                    )

            linked_returned_outcome_ids = {
                outcome_id
                for resolution in resolution_rows
                if resolution["status"] != "unresolved"
                for outcome_id in resolution["outcome_ids"]
                if outcome_id in fragment_outcome_ids
                and fragment_outcome_experiments[outcome_id]
                in set(resolution["experiment_ids"])
            }
            unlinked_returned_outcomes = sorted(
                fragment_outcome_ids - linked_returned_outcome_ids
            )
            if unlinked_returned_outcomes:
                raise ValueError(
                    "Every returned outcome requires a recovered candidate "
                    f"resolution: {unlinked_returned_outcomes}"
                )
            referenced_returned_experiments = {
                experiment_id
                for resolution in resolution_rows
                if resolution["status"] != "unresolved"
                for experiment_id in resolution["experiment_ids"]
                if any(
                    outcome_id in fragment_outcome_ids
                    and fragment_outcome_experiments[outcome_id]
                    == experiment_id
                    for outcome_id in resolution["outcome_ids"]
                )
            }
            unlinked_returned_experiments = sorted(
                fragment_experiment_ids - referenced_returned_experiments
            )
            if unlinked_returned_experiments:
                raise ValueError(
                    "Every returned experiment requires a candidate resolution "
                    "and linked returned outcome: "
                    f"{unlinked_returned_experiments}"
                )
            for resolution in resolution_rows:
                candidate_id = resolution["candidate_id"]
                if candidate_id in resolution_by_candidate:
                    raise ValueError(
                        "Candidate appears in more than one candidate resolution"
                    )
                resolution_by_candidate[candidate_id] = resolution
                for outcome_id in resolution["outcome_ids"]:
                    resolution_outcome_task_candidates.setdefault(
                        outcome_id, set()
                    ).update(task.candidate_ids)
            candidate_resolutions.extend(resolution_rows)

        new_experiments.extend(fragment_experiments)
        new_outcomes.extend(fragment_outcomes)
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
                "candidate_resolutions": [
                    row.model_dump(mode="json")
                    for row in fragment.candidate_resolutions
                ],
            }
        )

    if recovered_candidate_ids & unresolved_candidate_ids:
        raise ValueError("Candidate dispositions conflict across fragments")
    proposed = deepcopy(source)
    proposed["experiments"].extend(new_experiments)
    proposed["outcomes"].extend(new_outcomes)
    parsed, validation = validate_candidate(
        json.dumps(proposed, ensure_ascii=False),
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
    parsed_result = parsed.model_dump(mode="json")
    outcomes_by_id = {
        row["outcome_id"]: row for row in parsed_result.get("outcomes", [])
    }
    resolution_claimants: dict[str, set[str]] = {}
    for resolution in candidate_resolutions:
        if resolution["status"] == "unresolved":
            continue
        for outcome_id in resolution["outcome_ids"]:
            resolution_claimants.setdefault(outcome_id, set()).add(
                resolution["candidate_id"]
            )
    confirmed_resolution_links: set[tuple[str, str]] = set()
    confirmed_non_claimant_links: set[tuple[str, str]] = set()
    resolution_structural_coverage = []
    for outcome_id, claimant_ids in sorted(resolution_claimants.items()):
        task_candidate_ids_for_outcome = (
            resolution_outcome_task_candidates[outcome_id]
        )
        outcome_structural = evaluate_structural_coverage(
            candidates=[
                candidate_by_id[candidate_id]
                for candidate_id in sorted(task_candidate_ids_for_outcome)
            ],
            provisional_experiments=support.get(
                "provisional_experiments", []
            ),
            result={
                **parsed_result,
                "outcomes": [outcomes_by_id[outcome_id]],
            },
        )
        for row in outcome_structural["candidates"]:
            raw_confirmed = any(
                assessment["verdict"] == "confirmed"
                for assessment in row["assessments"]
            )
            if raw_confirmed and row["candidate_id"] not in claimant_ids:
                confirmed_non_claimant_links.add(
                    (row["candidate_id"], outcome_id)
                )
            if row["verdict"] == "confirmed":
                confirmed_resolution_links.add(
                    (row["candidate_id"], outcome_id)
                )
        resolution_structural_coverage.append(
            {
                "outcome_id": outcome_id,
                "candidate_ids": sorted(claimant_ids),
                "evaluated_candidate_ids": sorted(
                    task_candidate_ids_for_outcome
                ),
                "coverage": outcome_structural,
            }
        )

    if confirmed_non_claimant_links:
        raise ValueError(
            "Resolution outcomes structurally confirm a non-claimant "
            f"candidate: {sorted(confirmed_non_claimant_links)}"
        )
    confirmed_outcomes_by_candidate_experiment: dict[
        tuple[str, str], list[str]
    ] = {}
    for candidate_id, outcome_id in confirmed_resolution_links:
        key = (
            candidate_id,
            str(outcomes_by_id[outcome_id]["experiment_id"]),
        )
        confirmed_outcomes_by_candidate_experiment.setdefault(
            key, []
        ).append(outcome_id)
    same_experiment_multiple_matches = sorted(
        (candidate_id, experiment_id, sorted(outcome_ids))
        for (
            candidate_id,
            experiment_id,
        ), outcome_ids in confirmed_outcomes_by_candidate_experiment.items()
        if len(outcome_ids) > 1
    )
    if same_experiment_multiple_matches:
        raise ValueError(
            "Candidate has multiple structural matches in the same experiment: "
            f"{same_experiment_multiple_matches}"
        )

    unverified_resolution_links = sorted(
        (resolution["candidate_id"], outcome_id)
        for resolution in candidate_resolutions
        if resolution["status"] != "unresolved"
        for outcome_id in resolution["outcome_ids"]
        if (resolution["candidate_id"], outcome_id)
        not in confirmed_resolution_links
    )
    resolution_candidate_ids = set(resolution_by_candidate)
    legacy_recovered_candidate_ids = (
        recovered_candidate_ids - resolution_candidate_ids
    )
    unverified_recovered = sorted(
        candidate_id
        for candidate_id in legacy_recovered_candidate_ids
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
        if row["candidate_id"] in legacy_recovered_candidate_ids
        and row["verdict"] == "confirmed"
        and row["selected_assessment"] is not None
    }
    confirmed_new_outcome_ids |= {
        outcome_id
        for _, outcome_id in confirmed_resolution_links
        if outcome_id in new_outcome_ids
    }
    unrelated_new_outcome_ids = sorted(
        new_outcome_ids - confirmed_new_outcome_ids
    )
    if unverified_resolution_links:
        raise ValueError(
            "Recovered candidate resolution links failed structural "
            f"verification: {unverified_resolution_links}"
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

    auditable_resolutions = [
        {
            **resolution,
            "structurally_confirmed_outcome_ids": sorted(
                outcome_id
                for candidate_id, outcome_id in confirmed_resolution_links
                if candidate_id == resolution["candidate_id"]
            ),
            "merge_disposition": (
                "quarantined"
                if resolution["status"] == "unresolved"
                else "verified"
            ),
        }
        for resolution in candidate_resolutions
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    report = {
        "merge_version": "v12-structural-repair-merge-1.1.0",
        "paper_id": packet.paper_id,
        "source_result_sha256": _sha(source_bytes),
        "support_sha256": support_sha,
        "inputs": inputs,
        "recovered_candidate_ids": sorted(recovered_candidate_ids),
        "unresolved_candidate_ids": sorted(unresolved_candidate_ids),
        "quarantined_candidate_ids": sorted(unresolved_candidate_ids),
        "candidate_resolutions": auditable_resolutions,
        "new_experiment_ids": sorted(new_experiment_ids),
        "new_outcome_ids": sorted(new_outcome_ids),
        "validation_status": validation.status,
        "structural_verification_passed": True,
        "structural_coverage": structural,
        "resolution_structural_coverage": resolution_structural_coverage,
        "integration_blocked": bool(unresolved_candidate_ids),
        "finalization_allowed": not unresolved_candidate_ids,
        "server_request_sent": False,
        "paid_api_requests": 0,
    }
    (output_path.parent / "v12_structural_merge_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
