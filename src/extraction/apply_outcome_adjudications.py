"""Apply the frozen Day 5 human outcome-coverage decisions without an API call."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from src.extraction.check_outcome_coverage import check
from src.extraction.compact_validation import validate_candidate
from src.rag.compact_api_packet import CompactApiPacket


ROOT = Path(__file__).resolve().parents[2]
MERGED_ROOT = ROOT / "data/staging/extraction/compact_merged_v1"
PACKET_ROOT = ROOT / "data/staging/rag/compact_api_packets_v1"


def reported(value: Any, *evidence_ids: str) -> dict[str, Any]:
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": list(evidence_ids),
        "missing_reason": None,
    }


def missing(reason: str) -> dict[str, Any]:
    return {
        "value": None,
        "status": "missing",
        "evidence_ids": [],
        "missing_reason": reason,
    }


def adjudicate_gp004(result: dict[str, Any]) -> list[dict[str, Any]]:
    outcome = next(row for row in result["outcomes"] if row["outcome_id"] == "O2")
    evidence_id = "GP-004-E-fc1b2e9e166859e2"
    qualitative = outcome["qualitative_outcome"]
    if evidence_id not in qualitative["evidence_ids"]:
        qualitative["evidence_ids"].append(evidence_id)
    qualitative["value"] = (
        "Single injections of either HGF or EGF mRNA-LNP decreased steatosis; "
        "combined HGF/EGF mRNA-LNP produced more efficient steatosis reversal. "
        "A sharp decrease was observed 2 days after the first combined injection, "
        "while steatosis was maintained in Poly(C) RNA-LNP-treated mice."
    )
    return [
        {
            "candidate_id": "OC-936f1774e2b8c800",
            "decision": "merged_into_existing_outcome",
            "target_outcome_ids": ["O2"],
            "reason": "Same steatosis endpoint; passage adds treatment-arm detail.",
        }
    ]


def adjudicate_gp006(result: dict[str, Any]) -> list[dict[str, Any]]:
    existing = {row["outcome_id"] for row in result["outcomes"]}
    if existing & {"O4", "O5", "O6", "O7"}:
        raise ValueError("GP-006 adjudicated outcome IDs already exist")

    insertion_evidence = (
        "GP-006-E-b9606d3f1fb87b4c",
        "GP-006-E-d51e57e7bfc1ef65",
    )
    result["outcomes"].extend(
        [
            {
                "outcome_id": "O4",
                "experiment_id": "E1",
                "assay": reported("indel-variant analysis by deep sequencing", *insertion_evidence),
                "endpoint": reported("frequency of the +2 F8 insertion pattern", *insertion_evidence),
                "comparator": reported("deletion variants", *insertion_evidence),
                "outcome_value": reported(0.78, *insertion_evidence),
                "outcome_unit": reported("%", *insertion_evidence),
                "qualitative_outcome": reported(
                    "The +2 insertion pattern was less frequent than deletion variants.",
                    *insertion_evidence,
                ),
            },
            {
                "outcome_id": "O5",
                "experiment_id": "E1",
                "assay": reported("indel-variant analysis by deep sequencing", *insertion_evidence),
                "endpoint": reported("frequency of the +5 F8 insertion pattern", *insertion_evidence),
                "comparator": reported("deletion variants", *insertion_evidence),
                "outcome_value": reported(0.0, *insertion_evidence),
                "outcome_unit": reported("%", *insertion_evidence),
                "qualitative_outcome": reported(
                    "The +5 insertion pattern was not detected and was less frequent than deletion variants.",
                    *insertion_evidence,
                ),
            },
            {
                "outcome_id": "O6",
                "experiment_id": "E1",
                "assay": reported(
                    "activated partial thromboplastin time (aPTT) assay",
                    "GP-006-E-61352269ff3b61f2",
                ),
                "endpoint": reported(
                    "endogenous FVIII activity after two Cas9/sgRNA LNP injections",
                    "GP-006-E-5f1df7ac5c7ec3f9",
                    "GP-006-E-0e932dc79aa7ba74",
                ),
                "comparator": missing("No comparator was reported for the 2.6% FVIII value."),
                "outcome_value": reported(
                    2.6,
                    "GP-006-E-5f1df7ac5c7ec3f9",
                    "GP-006-E-0e932dc79aa7ba74",
                ),
                "outcome_unit": reported(
                    "% FVIII activity",
                    "GP-006-E-5f1df7ac5c7ec3f9",
                    "GP-006-E-0e932dc79aa7ba74",
                ),
                "qualitative_outcome": reported(
                    "LNP treatment significantly improved FVIII activity.",
                    "GP-006-E-0062483addf27f5e",
                ),
            },
            {
                "outcome_id": "O7",
                "experiment_id": "E1",
                "assay": reported(
                    "activated partial thromboplastin time (aPTT) assay",
                    "GP-006-E-8e9084aadcfe157d",
                    "GP-006-E-d9a16a0c73e6b6b2",
                ),
                "endpoint": reported(
                    "sustained endogenous FVIII activity after targeted correction of the mutant F8 gene",
                    "GP-006-E-8e9084aadcfe157d",
                    "GP-006-E-d9a16a0c73e6b6b2",
                    "GP-006-E-8f4df2feafb0205d",
                ),
                "comparator": missing(
                    "No comparator was reported for the sustained 3.30% FVIII value."
                ),
                "outcome_value": reported(
                    3.30,
                    "GP-006-E-8e9084aadcfe157d",
                    "GP-006-E-d9a16a0c73e6b6b2",
                ),
                "outcome_unit": reported(
                    "% FVIII activity (± 0.68%)",
                    "GP-006-E-8e9084aadcfe157d",
                    "GP-006-E-d9a16a0c73e6b6b2",
                ),
                "qualitative_outcome": reported(
                    "FVIII activity was sustained over 26 weeks, and targeted F8 "
                    "correction produced improved coagulation.",
                    "GP-006-E-8e9084aadcfe157d",
                    "GP-006-E-d9a16a0c73e6b6b2",
                    "GP-006-E-8f4df2feafb0205d",
                ),
            },
        ]
    )
    return [
        {
            "candidate_id": "OC-781d40fc07cf2489",
            "decision": "split_into_two_outcomes",
            "target_outcome_ids": ["O4", "O5"],
            "reason": "The passage reports distinct +2 and +5 insertion frequencies.",
        },
        {
            "candidate_id": "OC-28df22f2c9dbf0b3",
            "decision": "added_and_combined",
            "target_outcome_ids": ["O6"],
            "reason": "Combined with the duplicate 2.6% Figure 4A evidence group.",
        },
        {
            "candidate_id": "OC-6c01cb0fbfbd3499",
            "decision": "duplicate_merged",
            "target_outcome_ids": ["O6"],
            "reason": "Same 2.6% FVIII activity outcome.",
        },
        {
            "candidate_id": "OC-dc5047c7993bca64",
            "decision": "added",
            "target_outcome_ids": ["O7"],
            "reason": "Distinct sustained 3.30 ± 0.68% FVIII activity outcome.",
        },
        {
            "candidate_id": "OC-62c57df1960db222",
            "decision": "supporting_evidence_merged",
            "target_outcome_ids": ["O7"],
            "reason": "F8 correction explains the sustained FVIII/coagulation result.",
        },
    ]


def apply(paper_id: str) -> dict[str, Any]:
    run_dir = MERGED_ROOT / paper_id
    result_path = run_dir / "final_result.json"
    backup_path = run_dir / "pre_outcome_adjudication_result.json"
    packet = CompactApiPacket.model_validate_json(
        (PACKET_ROOT / f"{paper_id}.json").read_text(encoding="utf-8")
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if backup_path.exists():
        raise FileExistsError(f"Adjudication backup already exists for {paper_id}")
    shutil.copy2(result_path, backup_path)

    if paper_id == "GP-004":
        decisions = adjudicate_gp004(result)
    elif paper_id == "GP-006":
        decisions = adjudicate_gp006(result)
    else:
        raise ValueError(f"No frozen adjudication instructions for {paper_id}")

    parsed, validation = validate_candidate(
        json.dumps(result, ensure_ascii=False),
        paper_id=paper_id,
        allowed_evidence_ids={row.evidence_id for row in packet.evidence},
    )
    if parsed is None:
        raise ValueError(f"Adjudicated {paper_id} result failed validation")
    result_path.write_text(
        json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    coverage = check(packet, parsed.model_dump(mode="json"))
    report = {
        "adjudication_version": "outcome-coverage-human-1.0.0",
        "paper_id": paper_id,
        "human_decisions": decisions,
        "paid_api_requests": 0,
        "final_validation_status": validation.status,
        "post_adjudication_coverage_status": coverage.status,
        "remaining_actionable_candidates": [
            row.model_dump(mode="json") for row in coverage.unmatched_candidates
        ],
        "backup_path": str(backup_path),
        "final_result_path": str(result_path),
    }
    (run_dir / "outcome_adjudication.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "post_adjudication_coverage.json").write_text(
        coverage.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    reports = [apply(paper_id) for paper_id in ("GP-004", "GP-006")]
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
