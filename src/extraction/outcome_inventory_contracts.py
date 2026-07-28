"""Contracts for full-evidence outcome inventory and deterministic disposition."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.extraction.outcome_coverage_contracts import OutcomeCandidate


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateDisposition(StrictModel):
    candidate_id: str
    decision: Literal[
        "retained_unique",
        "merged_duplicate",
        "rejected_method",
        "rejected_background",
        "rejected_formula",
        "rejected_not_biological_outcome",
        "needs_human_review",
    ]
    canonical_candidate_id: str | None
    reason: str


class OutcomeInventory(StrictModel):
    inventory_version: Literal["full-outcome-inventory-1.0.0"]
    paper_id: str
    source_packet_checksum: str
    raw_candidate_count: int
    retained_candidates: list[OutcomeCandidate]
    dispositions: list[CandidateDisposition]
    candidate_recall_gate: Literal["ready_for_coverage", "needs_human_review"]
    paid_api_requests: Literal[0] = 0

    @property
    def unresolved_dispositions(self) -> list[CandidateDisposition]:
        return [
            row for row in self.dispositions if row.decision == "needs_human_review"
        ]
