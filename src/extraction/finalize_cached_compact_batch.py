"""Revalidate and finalize cached current-schema compact results without API calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.extraction.compact_validation import validate_candidate
from src.extraction.assess_outcome_complexity import assess
from src.extraction.build_outcome_candidates import build_candidates
from src.extraction.check_outcome_coverage import check
from src.extraction.merge_compact_results import merge_results
from src.rag.compact_api_packet import CompactApiPacket


ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOT = ROOT / "data" / "staging" / "extraction" / "compact_one_call_v1"
PACKET_ROOT = ROOT / "data" / "staging" / "rag" / "compact_api_packets_v1"
OUTPUT_ROOT = ROOT / "data" / "staging" / "extraction" / "compact_merged_v1"
PAPER_IDS = [f"GP-{number:03d}" for number in range(1, 10)]


def finalize_batch(
    *,
    result_root: Path = RESULT_ROOT,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    completed: list[str] = []
    skipped: list[dict[str, str]] = []
    for paper_id in PAPER_IDS:
        candidate_path = result_root / paper_id / "result.json"
        candidate_text = candidate_path.read_text(encoding="utf-8")
        candidate = json.loads(candidate_text)
        if candidate.get("contract_version") != "compact-1.1.0":
            skipped.append(
                {
                    "paper_id": paper_id,
                    "reason": (
                        f"legacy contract {candidate.get('contract_version')}; "
                        "current-schema rerun required"
                    ),
                }
            )
            continue
        packet_path = packet_root / f"{paper_id}.json"
        packet = CompactApiPacket.model_validate_json(
            packet_path.read_text(encoding="utf-8")
        )
        parsed, report = validate_candidate(
            candidate_text,
            paper_id=paper_id,
            allowed_evidence_ids={row.evidence_id for row in packet.evidence},
        )
        if parsed is None:
            skipped.append(
                {
                    "paper_id": paper_id,
                    "reason": f"current validation failed with {len(report.findings)} findings",
                }
            )
            continue
        paper_output = output_root / paper_id
        paper_output.mkdir(parents=True, exist_ok=True)
        assessment = assess(packet)
        (paper_output / "complexity.json").write_text(
            assessment.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        if (
            assessment.route == "complex"
            and parsed.eligibility.decision == "eligible"
        ):
            coverage = check(
                packet,
                parsed.model_dump(mode="json"),
                assessment=assessment,
                candidates=build_candidates(packet),
            )
            (paper_output / "outcome_coverage.json").write_text(
                coverage.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            if coverage.status != "complete":
                skipped.append(
                    {
                        "paper_id": paper_id,
                        "reason": (
                            "complex outcome coverage unresolved: "
                            f"{len(coverage.unmatched_candidates)} actionable, "
                            f"{len(coverage.review_candidates)} review"
                        ),
                    }
                )
                continue
        report_path = paper_output / "source_validation_report.json"
        report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        merged = merge_results(
            candidate_path=candidate_path,
            validation_report_path=report_path,
            packet_path=packet_path,
            output_root=output_root,
        )
        if merged.status != "merged_valid":
            raise RuntimeError(f"Unexpected unresolved merge for {paper_id}")
        completed.append(paper_id)
    manifest = {
        "batch_version": "compact-merged-batch-1.0.0",
        "paid_api_requests": 0,
        "completed": completed,
        "skipped": skipped,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "batch_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(finalize_batch(output_root=args.output_root), indent=2))


if __name__ == "__main__":
    main()
