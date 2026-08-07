from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentBlock(StrictModel):
    block_id: str
    paper_id: str
    source_path: str
    source_kind: Literal[
        "pmc_xml", "pdf", "grobid_tei", "spreadsheet", "archive_member"
    ]
    section_path: str
    block_type: Literal["title", "abstract", "paragraph", "table", "figure_caption", "pdf_page"]
    text: str = Field(min_length=1)
    page_number: int | None = None
    xml_element_id: str | None = None
    table_number: str | None = None
    figure_number: str | None = None
    char_start: int = 0
    char_end: int
    parser: str
    parser_confidence: float = Field(ge=0, le=1)


class EntityCandidate(StrictModel):
    candidate_id: str
    paper_id: str
    block_id: str
    text: str
    entity_type: Literal[
        "lnp", "lipid_or_material", "payload", "cell", "tissue", "disease",
        "species", "route", "dose", "timepoint", "assay", "outcome",
        "gene_or_protein", "composition_signal", "formulation_label",
    ]
    char_start: int
    char_end: int
    detector: str
    confidence: float = Field(ge=0, le=1)


class RetrievalQuery(StrictModel):
    query_id: str
    paper_id: str
    question: str
    field_group: Literal[
        "formulation", "component", "payload", "experiment_boundary",
        "recipient_cell", "therapeutic_target", "model_context", "outcome",
    ]
    required_entity_types: list[str] = Field(default_factory=list)


class RetrievalHit(StrictModel):
    query_id: str
    block_id: str
    paper_id: str
    text: str
    section_path: str
    source_path: str
    source_kind: Literal["pmc_xml", "pdf", "grobid_tei"] | None = None
    block_type: Literal["title", "abstract", "paragraph", "table", "figure_caption", "pdf_page"] | None = None
    page_number: int | None
    xml_element_id: str | None = None
    table_number: str | None = None
    figure_number: str | None = None
    lexical_score: float | None = None
    vector_score: float | None = None
    fused_score: float
    entity_types: list[str] = Field(default_factory=list)


class RetrievalPacket(StrictModel):
    query: RetrievalQuery
    hits: list[RetrievalHit]
    retrieval_methods: list[str]
    warnings: list[str]


class EvidenceGate(StrictModel):
    """Machine-checkable decision about whether extraction may proceed."""

    passed: bool
    paper_id: str
    query_id: str
    accepted_block_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
