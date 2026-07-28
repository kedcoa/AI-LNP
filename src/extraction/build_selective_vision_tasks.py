"""Build one-crop vision tasks only for explicit unresolved table/figure referrals."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from openai.lib._pydantic import to_strict_json_schema

from src.extraction.build_repair_tasks import COLLECTION_MODELS
from src.extraction.compact_validation import ValidationReport
from src.extraction.selective_vision_contracts import (
    CropBox,
    SelectiveVisionTask,
    VisionReferral,
    VisionTextEvidence,
)
from src.rag.compact_api_packet import CompactApiPacket


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = (
    ROOT / "data" / "staging" / "extraction" / "selective_vision_tasks_v1"
)
Renderer = Callable[[Path, int, CropBox | None, Path], None]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def render_pdf_region(
    pdf_path: Path,
    page_number: int,
    crop_box: CropBox | None,
    output_path: Path,
    *,
    zoom: float = 4.0,
) -> None:
    """Render one page or crop. PyMuPDF is loaded only in the PDF environment."""
    try:
        import fitz
    except ImportError as error:
        raise RuntimeError(
            "Selective-vision rendering requires the project's .venv-rag "
            "environment with PyMuPDF."
        ) from error
    document = fitz.open(pdf_path)
    if page_number > document.page_count:
        raise ValueError(
            f"Page {page_number} exceeds PDF page count {document.page_count}"
        )
    page = document[page_number - 1]
    clip = (
        fitz.Rect(
            crop_box.x0, crop_box.y0, crop_box.x1, crop_box.y1
        )
        if crop_box
        else page.rect
    )
    if not page.rect.contains(clip):
        raise ValueError("Crop box lies outside the selected PDF page")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False
    )
    pixmap.save(output_path)
    document.close()


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


def _text_evidence(packet: CompactApiPacket, evidence_id: str) -> VisionTextEvidence:
    row = next(item for item in packet.evidence if item.evidence_id == evidence_id)
    return VisionTextEvidence(
        evidence_id=row.evidence_id, text=row.text, source_ids=row.source_ids
    )


def build_task(
    *,
    referral: VisionReferral,
    report: ValidationReport,
    packet: CompactApiPacket,
    pdf_path: Path,
    output_root: Path = OUTPUT_ROOT,
    renderer: Renderer = render_pdf_region,
) -> SelectiveVisionTask:
    if referral.paper_id != report.paper_id or referral.paper_id != packet.paper_id:
        raise ValueError("Referral, validation report, and packet paper IDs must match")
    finding = next(
        row for row in report.findings if row.finding_id == referral.finding_id
    )
    if not finding.repairable:
        raise ValueError("Selective vision requires one field-level finding")
    collection = finding.record_collection
    field_name = finding.field_name
    assert collection is not None and field_name is not None

    source = next(
        row for row in packet.sources if row.source_id == referral.source_id
    )
    expected_kind = "table" if referral.trigger == "unresolved_table" else "figure"
    source_kind = (
        "table"
        if source.table_number or source.block_type in {"table", "table_row"}
        else "figure"
        if source.figure_number
        or source.block_type in {"figure", "figure_caption", "caption"}
        else None
    )
    if source_kind != expected_kind:
        raise ValueError("Referral trigger does not match the selected source")
    if source.page_number and source.page_number != referral.page_number:
        raise ValueError("Referral page does not match packet source page")

    allowed_ids = {row.evidence_id for row in packet.evidence}
    requested_ids = {
        referral.caption_evidence_id,
        *referral.referring_results_evidence_ids,
        *referral.methods_evidence_ids,
    }
    missing_ids = requested_ids - allowed_ids
    if missing_ids:
        raise ValueError(f"Referral evidence absent from packet: {sorted(missing_ids)}")

    task_dir = output_root / referral.paper_id / referral.finding_id
    crop_path = task_dir / "crop.png"
    renderer(pdf_path, referral.page_number, referral.crop_box, crop_path)
    if not crop_path.exists() or crop_path.stat().st_size == 0:
        raise ValueError("Renderer did not create a non-empty crop")
    crop_sha256 = _sha256(crop_path.read_bytes())

    unsigned = {
        "task_version": "selective-vision-task-1.0.0",
        "paper_id": referral.paper_id,
        "finding": finding.model_dump(mode="json"),
        "trigger": referral.trigger,
        "trigger_reason": referral.reason,
        "source_pdf": str(pdf_path),
        "source_pdf_sha256": _sha256(pdf_path.read_bytes()),
        "page_number": referral.page_number,
        "figure_or_table": referral.figure_or_table,
        "crop_box": (
            referral.crop_box.model_dump(mode="json")
            if referral.crop_box
            else None
        ),
        "crop_path": str(crop_path),
        "crop_sha256": crop_sha256,
        "crop_evidence_id": f"V-{crop_sha256[:16]}",
        "caption": _text_evidence(
            packet, referral.caption_evidence_id
        ).model_dump(mode="json"),
        "referring_results_passages": [
            _text_evidence(packet, evidence_id).model_dump(mode="json")
            for evidence_id in referral.referring_results_evidence_ids
        ],
        "methods_context": [
            _text_evidence(packet, evidence_id).model_dump(mode="json")
            for evidence_id in referral.methods_evidence_ids
        ],
        "expected_schema_fragment": _schema_fragment(collection, field_name),
    }
    task = SelectiveVisionTask.model_validate(
        {**unsigned, "task_checksum": _sha256(_canonical_json(unsigned))}
    )
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(
        task.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return task


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--referral", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    task = build_task(
        referral=VisionReferral.model_validate_json(
            args.referral.read_text(encoding="utf-8")
        ),
        report=ValidationReport.model_validate_json(
            args.validation_report.read_text(encoding="utf-8")
        ),
        packet=CompactApiPacket.model_validate_json(
            args.packet.read_text(encoding="utf-8")
        ),
        pdf_path=args.pdf,
        output_root=args.output_dir,
    )
    print(task.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
