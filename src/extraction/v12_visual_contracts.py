"""Strict, local-only contracts for the v1.2 visual evidence track."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisualBBoxV12(StrictModel):
    left: float
    top: float
    right: float
    bottom: float
    coord_origin: str


class DoclingTextItemV12(StrictModel):
    label: str
    text: str = Field(min_length=1)
    page_in_crop: int = Field(ge=1)
    bbox: VisualBBoxV12 | None = None


class DoclingTableCellV12(StrictModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(ge=1)
    column_span: int = Field(ge=1)
    text: str
    is_row_header: bool
    is_column_header: bool


class DoclingTableV12(StrictModel):
    table_index: int = Field(ge=0)
    rows: int = Field(ge=0)
    columns: int = Field(ge=0)
    grid: list[list[str]]
    cells: list[DoclingTableCellV12]


class DoclingVisualObjectV12(StrictModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    object_id: str
    paper_id: str
    source_file: str
    original_page: int = Field(ge=1)
    figure_or_table: str
    inventory_object_type: Literal["figure", "table"]
    caption: str
    source_crop: str
    source_crop_sha256: str
    parser_name: Literal["docling"] = "docling"
    parser_version: str
    parser_config: dict[str, str | int | bool]
    parse_seconds: float = Field(ge=0)
    parse_status: Literal["parsed", "failed"]
    text_items: list[DoclingTextItemV12]
    tables: list[DoclingTableV12]
    picture_count: int = Field(ge=0)
    warnings: list[str]


class VisualAtomicClaimV12(StrictModel):
    claim_id: str
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    endpoint: str | None = None
    result_type: Literal["exact_numeric", "qualitative"]
    value: str = Field(
        min_length=1,
        description=(
            "Exact printed value for exact_numeric, or direction/localization "
            "without percentages or numeric estimates for qualitative."
        ),
    )
    unit: str | None = None
    intervention_context: str | None = None
    panel_or_cell: str = Field(min_length=1)
    visible_support: list[str] = Field(
        min_length=1,
        description=(
            "Visible labels and observations. Qualitative claims must not "
            "include percentages or estimated bar/point values."
        ),
    )
    evidence_kinds: list[
        Literal["image", "docling_table_cell", "docling_ocr", "caption"]
    ] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def check_result_shape(self) -> "VisualAtomicClaimV12":
        if self.result_type == "qualitative" and self.unit:
            raise ValueError("qualitative claims cannot carry a numeric unit")
        if self.result_type == "qualitative":
            qualitative_text = " ".join([self.value, *self.visible_support])
            if re.search(
                r"(?:approximately|about|~)\s*\d|\d+(?:\.\d+)?\s*%",
                qualitative_text,
                re.I,
            ):
                raise ValueError(
                    "qualitative claims cannot include numeric estimates"
                )
        return self


class VlmVisualDecisionV12(StrictModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    object_id: str
    query_id: str
    status: Literal["extract", "abstain"]
    claims: list[VisualAtomicClaimV12]
    abstention_reason: Literal[
        "target_not_visible",
        "insufficient_resolution",
        "ambiguous_mapping",
        "missing_required_context",
        "unsupported_inference",
    ] | None
    missing_requirements: list[str]

    @model_validator(mode="after")
    def check_decision_shape(self) -> "VlmVisualDecisionV12":
        if self.status == "extract":
            if not self.claims:
                raise ValueError("extract decisions require at least one claim")
            if self.abstention_reason is not None:
                raise ValueError("extract decisions cannot include an abstention reason")
        else:
            if self.claims:
                raise ValueError("abstain decisions cannot include claims")
            if self.abstention_reason is None:
                raise ValueError("abstain decisions require a reason")
        return self


# Backward-compatible name for the original Gemma benchmark fixtures.
GemmaVisualDecisionV12 = VlmVisualDecisionV12
