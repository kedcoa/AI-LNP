"""Strict contracts for the Codex CLI and Ollama shadow benchmark."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TerminalDisposition = Literal[
    "accepted",
    "rejected_by_validation",
    "model_abstained",
    "schema_failure",
    "timeout_or_runtime_failure",
    "requires_human_review",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BenchmarkCase(StrictModel):
    case_id: str = Field(min_length=1)
    route: Literal["audit", "gate_b"]
    paper_id: str = Field(pattern=r"^GP-\d{3}$")
    source_paths: list[str] = Field(min_length=1)
    source_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    prompt: str = Field(min_length=1)
    payload: dict[str, Any]
    output_schema: dict[str, Any]


class AuditFinding(StrictModel):
    finding_id: str = Field(min_length=1)
    finding_type: Literal[
        "likely_omission",
        "unsupported_relationship",
        "wrong_arm_association",
        "incomplete_required_field",
        "comet_readiness_gap",
    ]
    severity: Literal["low", "medium", "high"]
    record_ids: list[str]
    evidence_ids: list[str]
    explanation: str = Field(min_length=1)
    suggested_disposition: Literal["accept", "flag", "quarantine", "human_review"]


class AuditResponse(StrictModel):
    disposition: Literal["completed", "abstained"]
    findings: list[AuditFinding]
    checked_requirement_categories: list[str]
    unresolved_reason: str | None

    @model_validator(mode="after")
    def validate_abstention(self) -> "AuditResponse":
        if self.disposition == "abstained" and not self.unresolved_reason:
            raise ValueError("An abstained audit requires unresolved_reason")
        if self.disposition == "completed" and self.unresolved_reason:
            raise ValueError("A completed audit cannot include unresolved_reason")
        return self


class AttemptResult(StrictModel):
    case_id: str = Field(min_length=1)
    route: Literal["audit", "gate_b"]
    backend: Literal["codex", "ollama", "saved"]
    model: str = Field(min_length=1)
    source_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    prompt_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    completed_at: datetime
    duration_seconds: float = Field(ge=0)
    exit_code: int | None
    terminal_disposition: TerminalDisposition
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    token_measurement_reason: str | None
    stdout_path: str
    stderr_path: str
    parsed_result: dict[str, Any] | None
    validation_issues: list[str]
    paid_api_requests: int = Field(default=0, ge=0)
    production_writes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_token_measurement(self) -> "AttemptResult":
        missing = self.input_tokens is None or self.output_tokens is None
        if missing and not self.token_measurement_reason:
            raise ValueError(
                "token_measurement_reason is required when token counts are unmeasured"
            )
        if not missing and self.token_measurement_reason:
            raise ValueError(
                "token_measurement_reason must be null when both token counts are measured"
            )
        return self


class ApplicationRequirement(StrictModel):
    requirement_id: str
    requirement_type: Literal[
        "component", "formulation", "experiment", "outcome", "arm"
    ]
    paper_id: str
    evidence_ids: list[str]
    expected: dict[str, Any]


class RequirementResult(StrictModel):
    requirement_id: str
    status: Literal["full", "partial", "missing", "unsafe"]
    matched_record_ids: list[str]
    evidence_ids: list[str]
    explanation: str


class RouteEvaluation(StrictModel):
    route: Literal["audit", "gate_b"]
    issued_attempts: int = Field(ge=0)
    terminal_attempts: int = Field(ge=0)
    full_requirements: int = Field(ge=0)
    total_requirements: int = Field(ge=0)
    full_recall: float = Field(ge=0, le=1)
    complete_arms: int = Field(ge=0)
    total_arms: int = Field(ge=0)
    safety_findings: dict[str, int]
    infrastructure_complete: bool
    requirement_results: list[RequirementResult]


class BenchmarkDecision(StrictModel):
    auditor_recommendation: Literal[
        "adopt_shadow_auditor", "do_not_adopt_auditor", "insufficient_evidence"
    ]
    extractor_recommendation: Literal[
        "continue_low_risk_shadow", "retain_openai", "insufficient_evidence"
    ]
    auditor_reasons: list[str]
    extractor_reasons: list[str]
    paid_api_requests: int = Field(default=0, ge=0)
