"""Strict contracts for Day 8 multimodal PDF evidence extraction."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PDFSourceLocation(StrictModel):
    file_name: str
    page: int = Field(ge=1)
    figure_or_table: str | None = None
    panel_or_cell: str | None = None
    evidence_source_type: Literal[
        "body_text", "caption", "table", "figure", "legend", "supplement"
    ]
    evidence_quote: str = Field(min_length=1)


class VisualEvidenceRecord(StrictModel):
    record_id: str
    paper_id: str
    experiment_id: str
    population: str
    intervention: str
    endpoint: str
    value: str
    unit: str | None = None
    location: PDFSourceLocation
    measurement_status: Literal[
        "exact", "exact_reported", "qualitative_reported", "visually_estimated"
    ]
    confidence: Literal["high", "medium", "low"]
    ambiguity: str | None = None


class BoundingBox(StrictModel):
    x0: float
    y0: float
    x1: float
    y1: float


class ReconstructedDocumentObject(StrictModel):
    object_id: str
    paper_id: str
    source_file: str
    page: int = Field(ge=1)
    object_type: Literal["figure", "table"]
    label: str
    caption: str
    surrounding_text: str
    bbox: BoundingBox
    crop_path: str
    page_image_path: str
    detection_method: Literal["caption_image_association", "caption_page_region"]
    embedded_image_count: int = Field(ge=0)


class PrintedFact(StrictModel):
    fact_id: str
    panel: str | None = None
    population: str
    intervention: str
    endpoint: str
    value: str
    unit: str | None = None
    visible_support: str
    support_kind: Literal["printed_text", "printed_data_label", "table_cell", "axis_tick"]
    confidence: Literal["high", "medium", "low"]


class QualitativeComparison(StrictModel):
    comparison_id: str
    panel: str | None = None
    endpoint: str
    subject_group: str
    comparator_groups: list[str]
    direction: Literal["higher", "lower", "similar", "present", "absent", "mixed"]
    visible_support: str
    exact_number_available: Literal[False] = False
    confidence: Literal["high", "medium", "low"]


class ExcludedEstimate(StrictModel):
    estimate_id: str
    panel: str | None = None
    endpoint: str
    estimated_value: str | None = None
    exclusion_reason: Literal[
        "no_printed_value", "unclear_axis", "low_resolution",
        "ambiguous_group_mapping", "requires_digitization"
    ]


class RawPanelLabel(StrictModel):
    label_id: str
    panel: str
    group: str | None = None
    label: str
    value: str
    unit: str | None = None
    label_type: Literal[
        "quadrant", "data_label", "axis_label", "legend", "timepoint",
        "sample_size", "significance", "other"
    ]
    visibly_printed: Literal[True] = True


class ObjectVisionExtraction(StrictModel):
    contract_version: Literal["2.0.0"] = "2.0.0"
    object_id: str
    readability: Literal["readable", "partially_readable", "unreadable"]
    object_type: Literal[
        "table", "bar_chart", "line_chart", "scatter_plot", "flow_cytometry",
        "microscopy", "diagram", "multi_panel", "other"
    ]
    panels_detected: list[str]
    raw_panel_labels: list[RawPanelLabel]
    printed_facts: list[PrintedFact]
    qualitative_comparisons: list[QualitativeComparison]
    excluded_estimates: list[ExcludedEstimate]
    unresolved_ambiguities: list[str]
    acceptance_status: Literal[
        "machine_readable", "qualitative_only", "human_review_required", "unreadable"
    ]

class PDFExtractionResult(StrictModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    paper_id: str
    source_files: list[str] = Field(min_length=1)
    records: list[VisualEvidenceRecord]
    unresolved_ambiguities: list[str] = Field(default_factory=list)


class BaselineComparison(StrictModel):
    gold_id: str
    whole_pdf_status: Literal["matched", "missed", "not_run"]
    targeted_status: Literal["matched", "missed", "not_run"]
    explanation: str


class PDFExtractionComparison(StrictModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    paper_id: str
    comparisons: list[BaselineComparison]


class MergedEvidenceSource(StrictModel):
    source_id: str
    source_kind: Literal["text_pdf", "object_vision"]
    file_name: str
    page: int = Field(ge=1)
    figure_or_table: str | None = None
    panel_or_cell: str | None = None
    evidence_quote: str
    value: str
    unit: str | None = None
    measurement_status: Literal[
        "exact", "exact_reported", "qualitative_reported", "visually_estimated"
    ]
    confidence: Literal["high", "medium", "low"]
    crop_path: str | None = None
    source_context: str | None = None
    source_pages: list[int] = Field(default_factory=list)


class MergedEvidenceRecord(StrictModel):
    merged_record_id: str
    paper_id: str
    experiment_id: str
    population: str
    intervention: str
    endpoint: str
    canonical_value: str
    canonical_unit: str | None = None
    merge_status: Literal["single_source", "complementary", "conflict"]
    sources: list[MergedEvidenceSource] = Field(min_length=1)
    deterministic_issues: list[str] = Field(default_factory=list)
    requires_human_review: bool


class EvidenceVerification(StrictModel):
    merged_record_id: str
    disposition: Literal["retain", "correct", "reject", "human_review"]
    corrected_value: str | None = None
    corrected_unit: str | None = None
    reason: str
    source_ids_checked: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
