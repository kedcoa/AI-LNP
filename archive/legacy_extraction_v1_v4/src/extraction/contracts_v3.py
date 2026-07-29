"""Experiment-first v3 contracts: freeze event boundaries before fields."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSentenceV3(StrictModel):
    sentence_id: str
    text: str = Field(min_length=1)


class ExperimentBoundaryV3(StrictModel):
    reader_experiment_key: str
    experiment_label: str
    evidence_sentence_ids: list[str] = Field(min_length=1)
    experiment_anchor_quote: str = Field(min_length=1)
    formulation_or_delivery_system_mention: str | None = None
    payload_or_treatment_mention: str | None = None
    biological_model_mention: str | None = None
    recipient_cell_mention: str | None = None
    therapeutic_target_mention: str | None = None
    distinctness_reason: str


class ExperimentMapV3(StrictModel):
    contract_version: Literal["3.0.0"]
    paper_id: str
    reader_id: Literal["reader_a", "reader_b"]
    original_experiments_present: bool
    experiments: list[ExperimentBoundaryV3]

    @model_validator(mode="after")
    def experiments_match_presence(self):
        if self.original_experiments_present != bool(self.experiments):
            raise ValueError("original_experiments_present must match experiment list")
        return self
