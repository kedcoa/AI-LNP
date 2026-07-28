"""Contracts shared by local complexity and outcome-coverage checks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutcomeCandidate(StrictModel):
    candidate_id: str
    paper_id: str
    endpoint_family: str
    evidence_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    evidence_text: str
    direct_signal_terms: list[str]
    figure_or_table: str | None
    route_hint: Literal["text", "vision"]
    confidence: Literal["high", "medium"]
    confidence_reasons: list[str]


class ComplexityAssessment(StrictModel):
    assessment_version: Literal["outcome-complexity-1.1.0"]
    paper_id: str
    complexity_score: int = Field(ge=0)
    route: Literal["simple", "complex"]
    reasons: list[str]
    candidate_groups: int
    endpoint_families: int
    visual_candidate_groups: int


class CandidateMatch(StrictModel):
    candidate_id: str
    outcome_id: str
    score: float


class UnmatchedCandidate(StrictModel):
    candidate_id: str
    endpoint_family: str
    route_hint: Literal["text", "vision"]
    evidence_ids: list[str]
    figure_or_table: str | None
    confidence: Literal["high", "medium"]


class ReviewCandidate(StrictModel):
    candidate_id: str
    endpoint_family: str
    route_hint: Literal["text", "vision"]
    evidence_ids: list[str]
    figure_or_table: str | None
    reason: str


class CoverageReport(StrictModel):
    coverage_version: Literal["outcome-coverage-1.1.0"]
    paper_id: str
    complexity_route: Literal["simple", "complex"]
    candidate_groups: int
    extracted_outcomes: int
    matched_candidates: list[CandidateMatch]
    unmatched_candidates: list[UnmatchedCandidate]
    review_candidates: list[ReviewCandidate]
    status: Literal["complete", "review_unmatched_groups", "not_applicable"]
    paid_api_requests: Literal[0] = 0
