"""Compact contract v1.2 with explicit inequalities and variability."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from src.extraction.compact_contracts import (
    ComponentRecord,
    EligibilityRecord,
    ExperimentRecord,
    FormulationRecord,
    NumberField,
    OutcomeRecord,
    ReportedField,
    StrictContract,
)


class OutcomeRecordV12(OutcomeRecord):
    value_qualifier: ReportedField[
        Literal[
            "exact",
            "approximate",
            "greater_than",
            "less_than",
            "not_detected",
        ]
    ]
    variability_value: NumberField
    variability_type: ReportedField[
        Literal["SD", "SEM", "CI", "range", "not_reported"]
    ]


class CompactExtractionResponseV12(StrictContract):
    contract_version: Literal["compact-1.2.0"]
    paper_id: str
    eligibility: EligibilityRecord
    formulations: list[FormulationRecord]
    components: list[ComponentRecord]
    experiments: list[ExperimentRecord]
    outcomes: list[OutcomeRecordV12]
    unresolved_items: list[str]

    @model_validator(mode="after")
    def validate_links(self) -> "CompactExtractionResponseV12":
        records = [
            *self.formulations,
            *self.components,
            *self.experiments,
            *self.outcomes,
        ]
        if self.eligibility.decision != "eligible" and records:
            raise ValueError("Non-eligible papers must return empty extraction lists")
        if self.eligibility.decision == "eligible" and not (
            self.formulations and self.experiments and self.outcomes
        ):
            raise ValueError(
                "Eligible papers require formulation, experiment, and outcome records"
            )
        formulation_ids = [row.formulation_id for row in self.formulations]
        experiment_ids = [row.experiment_id for row in self.experiments]
        outcome_ids = [row.outcome_id for row in self.outcomes]
        for name, values in (
            ("formulation", formulation_ids),
            ("experiment", experiment_ids),
            ("outcome", outcome_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name}_id values must be unique")
        formulation_set = set(formulation_ids)
        experiment_set = set(experiment_ids)
        if any(row.formulation_id not in formulation_set for row in self.components):
            raise ValueError("Component references an unknown formulation")
        if any(row.formulation_id not in formulation_set for row in self.experiments):
            raise ValueError("Experiment references an unknown formulation")
        if any(row.experiment_id not in experiment_set for row in self.outcomes):
            raise ValueError("Outcome references an unknown experiment")
        return self

    def validate_evidence_ids(self, allowed: set[str]) -> None:
        if set(self.eligibility.evidence_ids) - allowed:
            raise ValueError("Eligibility references unknown evidence IDs")
        for record in [
            *self.formulations,
            *self.components,
            *self.experiments,
            *self.outcomes,
        ]:
            for field_name in record.__class__.model_fields:
                value = getattr(record, field_name)
                if isinstance(value, ReportedField):
                    unknown = set(value.evidence_ids) - allowed
                    if unknown:
                        raise ValueError(
                            f"{record.__class__.__name__}.{field_name} references "
                            f"unknown evidence IDs: {sorted(unknown)}"
                        )
