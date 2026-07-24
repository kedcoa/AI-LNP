"""Merge Day 8 text-PDF and object-vision evidence without hiding conflicts."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .pdf_multimodal_contracts import (
    MergedEvidenceRecord,
    MergedEvidenceSource,
    ObjectVisionExtraction,
    PDFExtractionResult,
)
from .reconstruct_pdf_objects import OUTPUT as VISION_OUTPUT
from .run_abstract_first import ROOT
from .run_day8_pdf import OUTPUT as PDF_OUTPUT


OUTPUT = ROOT / "data/staging/extraction/day8_afternoon"


def normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9αβγ+/-]+", text.lower()))


def key(paper_id: str, population: str, intervention: str, endpoint: str) -> tuple[str, ...]:
    return tuple(normalized(value) for value in (paper_id, population, intervention, endpoint))


def audit_source(source: MergedEvidenceSource) -> list[str]:
    issues: list[str] = []
    if source.page < 1:
        issues.append("invalid_page")
    if source.measurement_status == "visually_estimated":
        issues.append("derived_value_requires_human_verification")
    if not source.evidence_quote.strip():
        issues.append("missing_evidence")
    if source.source_kind == "object_vision" and not source.figure_or_table:
        issues.append("missing_figure_or_table")
    return issues


def load_pdf_sources() -> list[tuple[tuple[str, ...], str, str, MergedEvidenceSource]]:
    rows = []
    for path in sorted(PDF_OUTPUT.glob("*/targeted.validated.json")):
        result = PDFExtractionResult.model_validate_json(path.read_text())
        for record in result.records:
            loc = record.location
            source = MergedEvidenceSource(
                source_id=f"pdf:{record.record_id}",
                source_kind="text_pdf",
                file_name=loc.file_name,
                page=loc.page,
                figure_or_table=loc.figure_or_table,
                panel_or_cell=loc.panel_or_cell,
                evidence_quote=loc.evidence_quote,
                value=record.value,
                unit=record.unit,
                measurement_status=record.measurement_status,
                confidence=record.confidence,
                source_context=loc.evidence_quote,
                source_pages=[loc.page],
            )
            rows.append((
                key(record.paper_id, record.population, record.intervention, record.endpoint),
                record.experiment_id,
                record.record_id,
                source,
            ))
    return rows


def preferred_vision_paths() -> list[Path]:
    corrected = {path.name.removesuffix(".human_corrected.json") for path in
                 VISION_OUTPUT.glob("results/*.human_corrected.json")}
    paths = list(VISION_OUTPUT.glob("results/*.human_corrected.json"))
    paths.extend(
        path for path in VISION_OUTPUT.glob("results/*.validated.json")
        if path.name.removesuffix(".validated.json") not in corrected
    )
    return sorted(paths)


def load_vision_sources() -> list[tuple[tuple[str, ...], str, str, MergedEvidenceSource]]:
    inventory = {
        row["object_id"]: row
        for row in json.loads((VISION_OUTPUT / "object_inventory.json").read_text())
    }
    rows = []
    for path in preferred_vision_paths():
        result = ObjectVisionExtraction.model_validate_json(path.read_text())
        obj = inventory[result.object_id]
        for fact in result.printed_facts:
            source_id = f"vision:{result.object_id}:{fact.fact_id}"
            source = MergedEvidenceSource(
                source_id=source_id,
                source_kind="object_vision",
                file_name=Path(obj["source_file"]).name,
                page=obj["page"],
                figure_or_table=obj["label"],
                panel_or_cell=fact.panel,
                evidence_quote=fact.visible_support,
                value=fact.value,
                unit=fact.unit,
                measurement_status="exact_reported",
                confidence=fact.confidence,
                crop_path=obj["crop_path"],
                source_context=obj["caption"],
                # Figure captions can continue onto the following PDF page.
                # The verifier receives both pages and independently checks them.
                source_pages=[obj["page"], obj["page"] + 1],
            )
            experiment_id = f"visual:{result.object_id}:{fact.panel or 'unpanelled'}"
            rows.append((
                key(obj["paper_id"], fact.population, fact.intervention, fact.endpoint),
                experiment_id,
                source_id,
                source,
            ))
    return rows


def merge() -> list[MergedEvidenceRecord]:
    grouped: dict[tuple[str, ...], list[tuple[str, str, MergedEvidenceSource]]] = defaultdict(list)
    for record_key, experiment_id, source_id, source in load_pdf_sources() + load_vision_sources():
        grouped[record_key].append((experiment_id, source_id, source))

    merged = []
    for index, (record_key, members) in enumerate(sorted(grouped.items()), 1):
        sources = [row[2] for row in members]
        values = {(normalized(row.value), normalized(row.unit or "")) for row in sources}
        kinds = {row.source_kind for row in sources}
        status = (
            "conflict" if len(values) > 1
            else "complementary" if len(kinds) > 1
            else "single_source"
        )
        issues = sorted({issue for source in sources for issue in audit_source(source)})
        if status == "conflict":
            issues.append("conflicting_values")
        paper_id, population, intervention, endpoint = record_key
        first = sources[0]
        merged.append(MergedEvidenceRecord(
            merged_record_id=f"D8M-{index:04d}",
            paper_id=paper_id.upper(),
            experiment_id=members[0][0],
            population=population,
            intervention=intervention,
            endpoint=endpoint,
            canonical_value=first.value,
            canonical_unit=first.unit,
            merge_status=status,
            sources=sources,
            deterministic_issues=issues,
            requires_human_review=bool(issues) or status == "conflict",
        ))
    return merged


def run() -> dict:
    records = merge()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "merged_evidence.json"
    path.write_text(json.dumps(
        [row.model_dump(mode="json") for row in records],
        indent=2, ensure_ascii=False,
    ) + "\n")
    manifest = {
        "records": len(records),
        "single_source": sum(row.merge_status == "single_source" for row in records),
        "complementary": sum(row.merge_status == "complementary" for row in records),
        "conflicts": sum(row.merge_status == "conflict" for row in records),
        "human_review_required": sum(row.requires_human_review for row in records),
    }
    (OUTPUT / "merge_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
