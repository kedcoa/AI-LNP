"""Build minimal field-level repair packets from deterministic findings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from openai.lib._pydantic import to_strict_json_schema

from src.extraction.compact_contracts import (
    ComponentRecord,
    ExperimentRecord,
    FormulationRecord,
    OutcomeRecord,
)
from src.extraction.compact_validation import ValidationReport
from src.extraction.repair_contracts import RepairEvidence, RepairTask
from src.rag.compact_api_packet import CompactApiPacket


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data" / "staging" / "extraction" / "narrow_repair_tasks_v1"
COLLECTION_MODELS = {
    "formulations": FormulationRecord,
    "components": ComponentRecord,
    "experiments": ExperimentRecord,
    "outcomes": OutcomeRecord,
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _repair_evidence(row: Any) -> RepairEvidence:
    return RepairEvidence(
        evidence_id=row.evidence_id,
        text=row.text,
        source_ids=row.source_ids,
    )


def _schema_fragment(collection: str, field_name: str) -> dict[str, Any]:
    model = COLLECTION_MODELS[collection]
    schema = to_strict_json_schema(model)
    if field_name not in schema["properties"]:
        raise ValueError(f"{collection}.{field_name} is not a contract field")
    return {
        "field_name": field_name,
        "schema": schema["properties"][field_name],
        "$defs": schema.get("$defs", {}),
    }


def build_task(
    *,
    candidate: dict[str, Any],
    candidate_bytes: bytes,
    report: ValidationReport,
    finding_id: str,
    packet: CompactApiPacket,
    max_additional_passages: int = 3,
) -> RepairTask:
    finding = next(row for row in report.findings if row.finding_id == finding_id)
    if not finding.repairable:
        raise ValueError(f"{finding_id} is not a field-level repair finding")
    collection = finding.record_collection
    index = finding.record_index
    field_name = finding.field_name
    assert collection is not None and index is not None and field_name is not None

    invalid_record = candidate[collection][index]
    evidence_by_id = {row.evidence_id: row for row in packet.evidence}
    missing = set(finding.cited_evidence_ids) - set(evidence_by_id)
    if missing:
        raise ValueError(f"Finding cites evidence absent from packet: {sorted(missing)}")
    relevant = [
        _repair_evidence(evidence_by_id[evidence_id])
        for evidence_id in finding.cited_evidence_ids
    ]

    cited = set(finding.cited_evidence_ids)
    targeted = [
        _repair_evidence(row)
        for row in packet.evidence
        if row.evidence_id not in cited
        and any(
            field_name.lower() in tag.lower()
            or tag.lower() in field_name.lower()
            for tag in row.retrieval_field_tags
        )
    ][:max_additional_passages]

    unsigned = {
        "task_version": "narrow-repair-task-1.0.0",
        "paper_id": report.paper_id,
        "finding": finding.model_dump(mode="json"),
        "invalid_record": invalid_record,
        "relevant_cited_evidence": [
            row.model_dump(mode="json") for row in relevant
        ],
        "additional_targeted_passages": [
            row.model_dump(mode="json") for row in targeted
        ],
        "expected_schema_fragment": _schema_fragment(collection, field_name),
        "source_candidate_sha256": _sha256(candidate_bytes),
    }
    return RepairTask.model_validate(
        {**unsigned, "task_checksum": _sha256(_canonical_json(unsigned))}
    )


def build_all(
    *,
    candidate_path: Path,
    validation_report_path: Path,
    packet_path: Path,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    candidate_bytes = candidate_path.read_bytes()
    candidate = json.loads(candidate_bytes)
    report = ValidationReport.model_validate_json(
        validation_report_path.read_text(encoding="utf-8")
    )
    packet = CompactApiPacket.model_validate_json(
        packet_path.read_text(encoding="utf-8")
    )
    output_dir = output_root / report.paper_id
    output_dir.mkdir(parents=True, exist_ok=True)
    built, skipped = [], []
    for finding in report.findings:
        if not finding.repairable:
            skipped.append(finding.finding_id)
            continue
        task = build_task(
            candidate=candidate,
            candidate_bytes=candidate_bytes,
            report=report,
            finding_id=finding.finding_id,
            packet=packet,
        )
        path = output_dir / f"{finding.finding_id}.json"
        path.write_text(task.model_dump_json(indent=2) + "\n", encoding="utf-8")
        built.append(str(path))
    manifest = {
        "paper_id": report.paper_id,
        "built_tasks": built,
        "skipped_non_field_findings": skipped,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(
        json.dumps(
            build_all(
                candidate_path=args.candidate,
                validation_report_path=args.validation_report,
                packet_path=args.packet,
                output_root=args.output_dir,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
