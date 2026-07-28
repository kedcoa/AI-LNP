"""Contracts for field-level repair tasks and their narrow responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.extraction.compact_validation import ValidationFinding


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepairEvidence(StrictModel):
    evidence_id: str
    text: str
    source_ids: list[str]


class RepairTask(StrictModel):
    task_version: Literal["narrow-repair-task-1.0.0"]
    paper_id: str
    finding: ValidationFinding
    invalid_record: dict[str, Any]
    relevant_cited_evidence: list[RepairEvidence]
    additional_targeted_passages: list[RepairEvidence] = Field(max_length=3)
    expected_schema_fragment: dict[str, Any]
    source_candidate_sha256: str
    task_checksum: str

    def model_payload(self) -> dict[str, Any]:
        """Return only the five scientific inputs allowed by the v7 timeline."""
        return {
            "paper_id": self.paper_id,
            "invalid_record": self.invalid_record,
            "validation_finding": self.finding.model_dump(mode="json"),
            "relevant_cited_evidence": [
                row.model_dump(mode="json") for row in self.relevant_cited_evidence
            ],
            "additional_targeted_passages": [
                row.model_dump(mode="json")
                for row in self.additional_targeted_passages
            ],
            "expected_schema_fragment": self.expected_schema_fragment,
        }


class RepairResponse(StrictModel):
    finding_id: str
    disposition: Literal["corrected", "missing", "ambiguous"]
    corrected_fragment: dict[str, Any] | None
    evidence_ids: list[str]
    explanation: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def corrected_or_abstained(self) -> "RepairResponse":
        if self.disposition == "corrected" and self.corrected_fragment is None:
            raise ValueError("corrected requires corrected_fragment")
        if self.disposition != "corrected" and self.corrected_fragment is not None:
            raise ValueError("missing/ambiguous must not return a corrected fragment")
        return self
