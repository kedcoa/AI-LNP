"""Deterministically merge text and visual facts by locally issued IDs."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.extraction.application_normalization import canonicalize_fact


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MergedFact(_StrictModel):
    field_name: str = Field(min_length=1)
    canonical_value: str
    raw_values: list[str] = Field(min_length=1)
    normalization_rules: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class MergedExperiment(_StrictModel):
    experiment_id: str = Field(min_length=1)
    candidate_id: str | None = None
    facts: list[MergedFact]


class QuarantinedConflict(_StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source: str = Field(min_length=1)
    experiment_id: str | None = None
    candidate_id: str | None = None
    field_name: str | None = None
    canonical_values: list[str] = Field(default_factory=list)
    raw_values: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class MergeValidationFinding(_StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source: str = Field(min_length=1)
    experiment_id: str | None = None
    candidate_id: str | None = None
    field_name: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class MergeResult(_StrictModel):
    shared_facts: list[MergedFact]
    experiments: list[MergedExperiment]
    quarantined_conflicts: list[QuarantinedConflict]
    validation_findings: list[MergeValidationFinding]


class _FactAccumulator:
    def __init__(self, field_name: str, canonical_value: str) -> None:
        self.field_name = field_name
        self.canonical_value = canonical_value
        self.raw_values: list[str] = []
        self.normalization_rules: list[str] = []
        self.evidence_ids: list[str] = []
        self.sources: list[str] = []

    def add(
        self,
        *,
        raw_value: str,
        normalization_rule: str,
        evidence_ids: Iterable[str],
        source: str,
    ) -> None:
        _extend_unique(self.raw_values, [raw_value])
        _extend_unique(self.normalization_rules, [normalization_rule])
        _extend_unique(self.evidence_ids, evidence_ids)
        _extend_unique(self.sources, [source])

    def merged(self) -> MergedFact:
        return MergedFact(
            field_name=self.field_name,
            canonical_value=self.canonical_value,
            raw_values=self.raw_values,
            normalization_rules=self.normalization_rules,
            evidence_ids=self.evidence_ids,
        )


def _extend_unique(target: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _as_rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _issued_experiments(
    paper_map: Mapping[str, Any],
) -> OrderedDict[str, str | None]:
    issued: OrderedDict[str, str | None] = OrderedDict()

    def collect(container: Mapping[str, Any]) -> None:
        for key in (
            "experiments",
            "candidates",
            "context_candidates",
            "issued_experiments",
        ):
            for row in _as_rows(container.get(key)):
                experiment_id = row.get("experiment_id")
                if not isinstance(experiment_id, str) or not experiment_id:
                    continue
                candidate = row.get("candidate_id")
                candidate_id = candidate if isinstance(candidate, str) else None
                if experiment_id not in issued:
                    issued[experiment_id] = candidate_id
        inventory = container.get("experiment_inventory")
        if isinstance(inventory, Mapping):
            for inventory_id, value in inventory.items():
                if not isinstance(value, Mapping):
                    continue
                experiment = value.get("experiment_id", inventory_id)
                if not isinstance(experiment, str) or not experiment:
                    continue
                candidate = value.get(
                    "candidate_id", value.get("provisional_context_id")
                )
                candidate_id = candidate if isinstance(candidate, str) else None
                if experiment not in issued:
                    issued[experiment] = candidate_id
        for task in _as_rows(container.get("context_tasks")):
            collect(task)

    collect(paper_map)
    return issued


def _facts(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nested = _as_rows(row.get("facts"))
    if nested:
        return nested
    return [row] if "field_name" in row else []


def _experiment_groups(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for key in ("experiment_facts", "experiments"):
        rows.extend(_as_rows(result.get(key)))
    if "experiment_id" in result:
        rows.append(result)
    return rows


def _all_fact_values(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    raw_values: list[str] = []
    evidence_ids: list[str] = []
    for row in rows:
        raw = row.get("raw_value", row.get("value"))
        if raw is not None:
            _extend_unique(raw_values, [str(raw)])
        evidence = row.get("evidence_ids")
        if isinstance(evidence, list):
            _extend_unique(
                evidence_ids,
                [item for item in evidence if isinstance(item, str)],
            )
    return raw_values, evidence_ids


def merge_full_paper_results(
    paper_map: Mapping[str, Any],
    context_results: Sequence[Mapping[str, Any]],
    visual_results: Sequence[Mapping[str, Any]],
) -> MergeResult:
    """Merge supported facts without reassigning IDs or selecting conflicts."""

    issued = _issued_experiments(paper_map)
    fact_tables: dict[
        str | None,
        OrderedDict[str, OrderedDict[str, _FactAccumulator]],
    ] = {None: OrderedDict()}
    fact_tables.update(
        (experiment_id, OrderedDict()) for experiment_id in issued
    )
    quarantined: list[QuarantinedConflict] = []
    findings: list[MergeValidationFinding] = []

    def quarantine(
        *,
        code: str,
        message: str,
        source: str,
        experiment_id: str | None = None,
        candidate_id: str | None = None,
        field_name: str | None = None,
        canonical_values: Iterable[str] = (),
        raw_values: Iterable[str] = (),
        evidence_ids: Iterable[str] = (),
    ) -> None:
        conflict = QuarantinedConflict(
            code=code,
            message=message,
            source=source,
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            field_name=field_name,
            canonical_values=list(dict.fromkeys(canonical_values)),
            raw_values=list(dict.fromkeys(raw_values)),
            evidence_ids=list(dict.fromkeys(evidence_ids)),
        )
        quarantined.append(conflict)
        findings.append(
            MergeValidationFinding(
                code=code,
                message=message,
                source=source,
                experiment_id=experiment_id,
                candidate_id=candidate_id,
                field_name=field_name,
                evidence_ids=conflict.evidence_ids,
            )
        )

    def add_fact(
        row: Mapping[str, Any],
        *,
        experiment_id: str | None,
        candidate_id: str | None,
        source: str,
    ) -> None:
        field_name = row.get("field_name")
        raw_value = row.get("raw_value", row.get("value"))
        evidence = row.get("evidence_ids")
        if (
            not isinstance(field_name, str)
            or not field_name
            or raw_value is None
            or not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(item, str) or not item for item in evidence)
        ):
            raw_values, evidence_ids = _all_fact_values([row])
            quarantine(
                code="invalid_fact",
                message="fact requires a field name, raw value, and evidence IDs",
                source=source,
                experiment_id=experiment_id,
                candidate_id=candidate_id,
                field_name=field_name if isinstance(field_name, str) else None,
                raw_values=raw_values,
                evidence_ids=evidence_ids,
            )
            return
        canonical = canonicalize_fact(field_name, str(raw_value), evidence)
        by_field = fact_tables[experiment_id]
        by_canonical = by_field.setdefault(field_name, OrderedDict())
        accumulator = by_canonical.setdefault(
            canonical.canonical_value,
            _FactAccumulator(field_name, canonical.canonical_value),
        )
        accumulator.add(
            raw_value=canonical.raw_value,
            normalization_rule=canonical.normalization_rule,
            evidence_ids=canonical.evidence_ids,
            source=source,
        )

    for index, row in enumerate(_as_rows(paper_map.get("shared_facts"))):
        add_fact(
            row,
            experiment_id=None,
            candidate_id=None,
            source=f"paper_map.shared_facts[{index}]",
        )

    sources = (
        ("context_results", context_results),
        ("visual_results", visual_results),
    )
    for source_kind, results in sources:
        for result_index, result in enumerate(results):
            source_root = f"{source_kind}[{result_index}]"
            for fact_index, fact in enumerate(
                _as_rows(result.get("shared_facts"))
            ):
                add_fact(
                    fact,
                    experiment_id=None,
                    candidate_id=None,
                    source=f"{source_root}.shared_facts[{fact_index}]",
                )
            for group_index, group in enumerate(_experiment_groups(result)):
                source = f"{source_root}.experiment_facts[{group_index}]"
                experiment = group.get("experiment_id")
                candidate = group.get("candidate_id")
                experiment_id = (
                    experiment if isinstance(experiment, str) else None
                )
                candidate_id = candidate if isinstance(candidate, str) else None
                group_facts = _facts(group)
                raw_values, evidence_ids = _all_fact_values(group_facts)
                if experiment_id not in issued:
                    quarantine(
                        code="unknown_experiment_id",
                        message=(
                            "result references an experiment ID not issued "
                            "locally"
                        ),
                        source=source,
                        experiment_id=experiment_id,
                        candidate_id=candidate_id,
                        raw_values=raw_values,
                        evidence_ids=evidence_ids,
                    )
                    continue
                expected_candidate_id = issued[experiment_id]
                if (
                    expected_candidate_id is not None
                    and candidate_id is not None
                    and candidate_id != expected_candidate_id
                ):
                    quarantine(
                        code="candidate_experiment_mismatch",
                        message=(
                            "result candidate ID does not match the locally issued "
                            "experiment ID"
                        ),
                        source=source,
                        experiment_id=experiment_id,
                        candidate_id=candidate_id,
                        raw_values=raw_values,
                        evidence_ids=evidence_ids,
                    )
                    continue
                for fact_offset, fact in enumerate(group_facts):
                    add_fact(
                        fact,
                        experiment_id=experiment_id,
                        candidate_id=candidate_id,
                        source=f"{source}.facts[{fact_offset}]",
                    )

    def finalize(
        experiment_id: str | None,
        table: OrderedDict[str, OrderedDict[str, _FactAccumulator]],
    ) -> list[MergedFact]:
        merged: list[MergedFact] = []
        for field_name, alternatives in table.items():
            if len(alternatives) == 1:
                merged.append(next(iter(alternatives.values())).merged())
                continue
            accumulators = list(alternatives.values())
            quarantine(
                code="conflicting_canonical_values",
                message="multiple canonical values were reported for one field",
                source="|".join(
                    dict.fromkeys(
                        source
                        for accumulator in accumulators
                        for source in accumulator.sources
                    )
                ),
                experiment_id=experiment_id,
                candidate_id=issued.get(experiment_id),
                field_name=field_name,
                canonical_values=[row.canonical_value for row in accumulators],
                raw_values=[
                    value
                    for accumulator in accumulators
                    for value in accumulator.raw_values
                ],
                evidence_ids=[
                    evidence_id
                    for accumulator in accumulators
                    for evidence_id in accumulator.evidence_ids
                ],
            )
        return merged

    shared_facts = finalize(None, fact_tables[None])
    experiments = [
        MergedExperiment(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            facts=finalize(experiment_id, fact_tables[experiment_id]),
        )
        for experiment_id, candidate_id in issued.items()
    ]
    return MergeResult(
        shared_facts=shared_facts,
        experiments=experiments,
        quarantined_conflicts=quarantined,
        validation_findings=findings,
    )
