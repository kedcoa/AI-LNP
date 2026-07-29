"""Prepare experiment-scoped v1.2 repair tasks from frozen validated results.

This module is deliberately local-only. It verifies the frozen result and
support checksums, validates the result against the current evidence envelope,
computes deterministic structural coverage, and then invokes the bounded task
builder. It never calls an AI service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.extraction.build_v12_structural_repair_tasks import build_for_run
from src.extraction.compact_validation import validate_candidate
from src.extraction.run_compact_one_call import load_packet
from src.extraction.v12_main_route import (
    allowed_v12_evidence_ids,
    evaluate_v12_structural_result_coverage,
)
from src.rag.compact_packet import CompactEvidencePacket


ROOT = Path(__file__).resolve().parents[2]
BASELINE_MANIFEST = (
    ROOT / "reports/extraction/v12_baseline/baseline_manifest.json"
)
SUPPORT_ROOT = ROOT / "data/staging/extraction/v12_main_route_support"
PACKET_ROOT = ROOT / "data/staging/rag/compact_api_packets_v1"
OUTPUT_ROOT = ROOT / "data/staging/extraction/v12_structural_primary"
LEGACY_EVIDENCE_TASK_ROOT = (
    ROOT / "data/staging/extraction/consolidated_gold_gap_tasks_v1"
)
FULL_PACKET_ROOT = ROOT / "data/staging/rag/compact_packets_v1"
ATOMIC_INVENTORY_ROOT = (
    ROOT / "data/staging/extraction/v12_atomic_inventory"
)
REPORT_PATH = (
    ROOT
    / "reports/extraction/v12_structural_primary/preparation_summary.json"
)
GOLD_IDENTIFIER = re.compile(r"\bG[OX]-\d+\b")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _baseline_rows(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in manifest["selected_result_files"]:
        path = ROOT / row["path"]
        paper_id = path.parent.name
        if paper_id in rows:
            raise ValueError(f"Duplicate frozen result for {paper_id}")
        rows[paper_id] = row
    return rows


def _support_rows(support_root: Path) -> dict[str, dict[str, Any]]:
    manifest = json.loads(
        (support_root / "manifest.json").read_text(encoding="utf-8")
    )
    return {row["paper_id"]: row for row in manifest["papers"]}


def _verified_legacy_evidence(
    paper_id: str,
    legacy_evidence_task_root: Path,
    full_packet_root: Path,
    atomic_inventory_root: Path,
) -> tuple[set[str], dict[str, Any]]:
    """Resolve every source citation against checksummed stored provenance."""

    task_path = legacy_evidence_task_root / paper_id / "task.json"
    evidence_ids: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    if task_path.exists():
        task_bytes = task_path.read_bytes()
        task = json.loads(task_bytes)
        task_checksum = task.get("task_checksum")
        unsigned = {
            key: value for key, value in task.items()
            if key != "task_checksum"
        }
        if task_checksum != _sha(_canonical(unsigned)):
            raise ValueError(
                f"Legacy evidence task checksum drift for {paper_id}"
            )
        if task.get("paper_id") != paper_id:
            raise ValueError(
                f"Legacy evidence task paper ID mismatch for {paper_id}"
            )
        for row in task.get("evidence", []):
            if not row.get("evidence_id") or not row.get("text"):
                raise ValueError(
                    f"Legacy evidence task has an incomplete evidence row for "
                    f"{paper_id}"
                )
            evidence_ids.add(row["evidence_id"])
        for row in task.get("visual_assets", []):
            evidence_id = row.get("crop_evidence_id")
            image_path = Path(row["image_path"])
            if not evidence_id or not image_path.exists():
                raise ValueError(
                    f"Legacy visual provenance is unavailable for {paper_id}"
                )
            if _sha(image_path.read_bytes()) != row.get("image_sha256"):
                raise ValueError(
                    f"Legacy visual asset checksum drift for {paper_id}: "
                    f"{image_path}"
                )
            evidence_ids.add(evidence_id)
        artifacts.append(
            {
                "kind": "legacy_repair_task",
                "path": _relative(task_path),
                "sha256": _sha(task_bytes),
                "embedded_checksum": task_checksum,
            }
        )

    full_packet_path = full_packet_root / f"{paper_id}.json"
    if full_packet_path.exists():
        full_packet_bytes = full_packet_path.read_bytes()
        full_packet = CompactEvidencePacket.model_validate_json(
            full_packet_bytes
        )
        if full_packet.paper_id != paper_id:
            raise ValueError(f"Full packet paper ID mismatch for {paper_id}")
        evidence_ids |= {row.evidence_id for row in full_packet.evidence}
        artifacts.append(
            {
                "kind": "validated_full_evidence_packet",
                "path": _relative(full_packet_path),
                "sha256": _sha(full_packet_bytes),
            }
        )

    claims_path = atomic_inventory_root / paper_id / "claims.json"
    if claims_path.exists():
        claims_bytes = claims_path.read_bytes()
        claims = json.loads(claims_bytes)
        for claim in claims:
            for row in claim.get("evidence", []):
                if not row.get("evidence_id") or not row.get("quote"):
                    raise ValueError(
                        f"Atomic claim has incomplete provenance for {paper_id}"
                    )
                evidence_ids.add(row["evidence_id"])
        artifacts.append(
            {
                "kind": "atomic_claim_evidence",
                "path": _relative(claims_path),
                "sha256": _sha(claims_bytes),
            }
        )

    # Persist checksummed provenance artifacts, not the entire corpus-sized ID
    # registry. The smaller verified_source_evidence_ids field below records
    # the citations the frozen result actually used.
    return evidence_ids, {"artifacts": artifacts}


def prepare_one(
    paper_id: str,
    *,
    baseline_row: dict[str, Any],
    support_row: dict[str, Any],
    support_root: Path,
    packet_root: Path,
    output_root: Path,
    legacy_evidence_task_root: Path,
    full_packet_root: Path,
    atomic_inventory_root: Path,
) -> dict[str, Any]:
    """Materialize one verified local run directory and its bounded tasks."""

    source_path = ROOT / baseline_row["path"]
    source_bytes = source_path.read_bytes()
    source_sha = _sha(source_bytes)
    if source_sha != baseline_row["sha256"]:
        raise ValueError(f"Frozen result checksum drift for {paper_id}")
    result = json.loads(source_bytes)
    if result.get("paper_id") != paper_id:
        raise ValueError(f"Frozen result paper ID mismatch for {paper_id}")

    support_path = support_root / paper_id / "support.json"
    support = json.loads(support_path.read_text(encoding="utf-8"))
    support_sha = _sha(_canonical(support))
    if support_sha != support_row["support_sha256"]:
        raise ValueError(f"Support checksum drift for {paper_id}")
    if support.get("paper_id") != paper_id:
        raise ValueError(f"Support paper ID mismatch for {paper_id}")

    packet = load_packet(paper_id, packet_root)
    packet_payload = packet.model_dump(mode="json", exclude_none=True)
    legacy_evidence_ids, legacy_registry = _verified_legacy_evidence(
        paper_id,
        legacy_evidence_task_root,
        full_packet_root,
        atomic_inventory_root,
    )
    allowed_evidence_ids = {
        row.evidence_id for row in packet.evidence
    } | allowed_v12_evidence_ids(support) | legacy_evidence_ids
    parsed, validation = validate_candidate(
        source_bytes.decode("utf-8"),
        paper_id=paper_id,
        allowed_evidence_ids=allowed_evidence_ids,
    )
    if parsed is None or validation.status != "valid":
        raise ValueError(
            f"Frozen result is not valid under the v1.2 evidence envelope for "
            f"{paper_id}: "
            + "; ".join(row.message for row in validation.findings)
        )

    request_payload = {
        "evidence_packet": packet_payload,
        "outcome_recall_support": support,
    }
    serialized_payload = _canonical(request_payload)
    gold_identifiers = sorted(set(GOLD_IDENTIFIER.findall(serialized_payload)))
    if gold_identifiers:
        raise ValueError(
            f"{paper_id} task input contains gold identifiers: "
            f"{gold_identifiers}"
        )
    coverage = evaluate_v12_structural_result_coverage(
        support, parsed.model_dump(mode="json")
    )

    run_dir = output_root / paper_id
    if run_dir.exists():
        raise FileExistsError(
            f"Prepared directory already exists for {paper_id}; refusing to "
            "silently replace its audit trail"
        )
    run_dir.mkdir(parents=True)
    request = {
        "preparation_version": "v12-frozen-baseline-structural-1.0.0",
        "paper_id": paper_id,
        "source_result": {
            "path": baseline_row["path"],
            "sha256": source_sha,
        },
        "support_snapshot": {
            "path": _relative(support_path),
            "sha256": support_sha,
        },
        "source_evidence_registry": legacy_registry,
        "request_payload": request_payload,
    }
    (run_dir / "request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "result.json").write_bytes(source_bytes)
    (run_dir / "v12_structural_coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    task_manifest = build_for_run(run_dir)
    source_citations = {
        evidence_id
        for record in (
            parsed.model_dump(mode="json").get(collection, [])
            for collection in (
                "formulations",
                "components",
                "experiments",
                "outcomes",
            )
        )
        for row in record
        for value in row.values()
        if isinstance(value, dict)
        for evidence_id in value.get("evidence_ids", [])
    } | set(parsed.eligibility.evidence_ids)
    unsigned_preparation = {
        "paper_id": paper_id,
        "source_result_path": baseline_row["path"],
        "source_result_sha256": source_sha,
        "support_sha256": support_sha,
        "packet_checksum": packet.packet_checksum,
        "source_evidence_registry": legacy_registry,
        "verified_source_evidence_ids": sorted(source_citations),
        "baseline_validation_status": validation.status,
        "structural_counts": coverage["counts"],
        "structural_routes": coverage["routes"],
        "integration_blocked": coverage["integration_blocked"],
        "task_count": task_manifest["task_count"],
        "human_review_candidate_ids": task_manifest[
            "human_review_candidate_ids"
        ],
        "gold_identifiers_in_task_input": gold_identifiers,
        "paid_api_requests": 0,
    }
    preparation = {
        **unsigned_preparation,
        "manifest_checksum": _sha(_canonical(unsigned_preparation)),
    }
    (run_dir / "preparation_manifest.json").write_text(
        json.dumps(preparation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return preparation


def run(
    paper_ids: list[str],
    *,
    baseline_manifest_path: Path = BASELINE_MANIFEST,
    support_root: Path = SUPPORT_ROOT,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = OUTPUT_ROOT,
    report_path: Path = REPORT_PATH,
    legacy_evidence_task_root: Path = LEGACY_EVIDENCE_TASK_ROOT,
    full_packet_root: Path = FULL_PACKET_ROOT,
    atomic_inventory_root: Path = ATOMIC_INVENTORY_ROOT,
) -> dict[str, Any]:
    baseline_manifest = json.loads(
        baseline_manifest_path.read_text(encoding="utf-8")
    )
    baseline_by_paper = _baseline_rows(baseline_manifest)
    support_by_paper = _support_rows(support_root)
    missing_baselines = sorted(set(paper_ids) - set(baseline_by_paper))
    missing_support = sorted(set(paper_ids) - set(support_by_paper))
    if missing_baselines:
        raise ValueError(
            f"No frozen result is registered for: {missing_baselines}"
        )
    if missing_support:
        raise ValueError(
            f"No checksummed support is registered for: {missing_support}"
        )

    papers = [
        prepare_one(
            paper_id,
            baseline_row=baseline_by_paper[paper_id],
            support_row=support_by_paper[paper_id],
            support_root=support_root,
            packet_root=packet_root,
            output_root=output_root,
            legacy_evidence_task_root=legacy_evidence_task_root,
            full_packet_root=full_packet_root,
            atomic_inventory_root=atomic_inventory_root,
        )
        for paper_id in paper_ids
    ]
    report = {
        "preparation_version": "v12-frozen-baseline-structural-summary-1.0.0",
        "papers": papers,
        "task_count": sum(row["task_count"] for row in papers),
        "generation_requests": 0,
        "paid_api_requests": 0,
        "ready_for_paid_calls": False,
        "approval_required_after_preflight": True,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append", required=True)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.paper_id,
                output_root=args.output_root,
                report_path=args.report_path,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
