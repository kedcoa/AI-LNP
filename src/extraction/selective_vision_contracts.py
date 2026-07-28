"""Contracts for the Day 4 selective figure/table vision route."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.extraction.compact_validation import ValidationFinding


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CropBox(StrictModel):
    """PDF point coordinates, measured from the page's top-left corner."""

    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(gt=0)
    y1: float = Field(gt=0)

    @model_validator(mode="after")
    def positive_area(self) -> "CropBox":
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("crop box must have positive width and height")
        return self


class VisionReferral(StrictModel):
    """Explicit proof that text extraction left one table/figure unresolved."""

    referral_version: Literal["selective-vision-referral-1.0.0"]
    paper_id: str
    finding_id: str
    trigger: Literal["unresolved_table", "unresolved_figure"]
    reason: str = Field(min_length=1, max_length=500)
    source_id: str
    page_number: int = Field(ge=1)
    figure_or_table: str
    crop_box: CropBox | None = None
    caption_evidence_id: str
    referring_results_evidence_ids: list[str] = Field(min_length=1, max_length=3)
    methods_evidence_ids: list[str] = Field(default_factory=list, max_length=3)


class VisionTextEvidence(StrictModel):
    evidence_id: str
    text: str
    source_ids: list[str]


class SelectiveVisionTask(StrictModel):
    task_version: Literal["selective-vision-task-1.0.0"]
    paper_id: str
    finding: ValidationFinding
    trigger: Literal["unresolved_table", "unresolved_figure"]
    trigger_reason: str
    source_pdf: str
    source_pdf_sha256: str
    page_number: int = Field(ge=1)
    figure_or_table: str
    crop_box: CropBox | None
    crop_path: str
    crop_sha256: str
    crop_evidence_id: str
    caption: VisionTextEvidence
    referring_results_passages: list[VisionTextEvidence] = Field(
        min_length=1, max_length=3
    )
    methods_context: list[VisionTextEvidence] = Field(
        default_factory=list, max_length=3
    )
    expected_schema_fragment: dict[str, Any]
    task_checksum: str

    def text_payload(self) -> dict[str, Any]:
        """Return only the text and location context allowed by the timeline."""
        return {
            "paper_id": self.paper_id,
            "finding": self.finding.model_dump(mode="json"),
            "trigger": self.trigger,
            "trigger_reason": self.trigger_reason,
            "visual_location": {
                "page_number": self.page_number,
                "figure_or_table": self.figure_or_table,
                "crop_box": (
                    self.crop_box.model_dump(mode="json") if self.crop_box else None
                ),
                "crop_evidence_id": self.crop_evidence_id,
            },
            "caption": self.caption.model_dump(mode="json"),
            "referring_results_passages": [
                row.model_dump(mode="json")
                for row in self.referring_results_passages
            ],
            "methods_context": [
                row.model_dump(mode="json") for row in self.methods_context
            ],
            "expected_schema_fragment": self.expected_schema_fragment,
        }


class SelectiveVisionResponse(StrictModel):
    finding_id: str
    disposition: Literal["resolved", "missing", "ambiguous", "human_review"]
    field_name: str
    corrected_fragment: dict[str, Any] | None
    value_status: Literal[
        "exact_reported", "derived", "visually_estimated", "not_resolved"
    ]
    supporting_evidence_ids: list[str]
    figure_or_table: str
    panel_or_table_cell: str | None
    visible_support: str = Field(min_length=1, max_length=500)
    derivation: str | None
    confidence: Literal["high", "medium", "low"]
    requires_human_review: bool

    @model_validator(mode="after")
    def enforce_visual_safety(self) -> "SelectiveVisionResponse":
        if self.value_status == "visually_estimated":
            if self.disposition != "human_review" or not self.requires_human_review:
                raise ValueError("visually estimated values require human review")
            if not self.panel_or_table_cell:
                raise ValueError("visual estimates require panel_or_table_cell")
        if self.disposition == "resolved":
            if self.corrected_fragment is None:
                raise ValueError("resolved requires corrected_fragment")
            if self.value_status not in {"exact_reported", "derived"}:
                raise ValueError("resolved requires exact_reported or derived")
            if not self.panel_or_table_cell:
                raise ValueError("resolved requires panel_or_table_cell")
        elif self.disposition in {"missing", "ambiguous"}:
            if self.corrected_fragment is not None:
                raise ValueError("missing/ambiguous cannot return a correction")
            if self.value_status != "not_resolved":
                raise ValueError("missing/ambiguous requires not_resolved")
        if self.value_status == "derived" and not self.derivation:
            raise ValueError("derived values require a derivation")
        if self.disposition == "human_review" and not self.requires_human_review:
            raise ValueError("human_review disposition requires review")
        return self
