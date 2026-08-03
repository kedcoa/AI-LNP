"""Deterministically merge text and visual facts by locally issued IDs."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.extraction.application_normalization import canonicalize_fact
from src.extraction.full_paper_tasks import (
    context_candidate_evidence_envelopes,
    issue_context_candidates,
)


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


@dataclass
class _Issuance:
    candidate_id: str | None
    context_evidence_ids: set[str] = field(default_factory=set)
    visual_evidence_ids: set[str] = field(default_factory=set)
    visual_slot_evidence_ids: dict[str, set[str]] = field(
        default_factory=dict
    )
    scientific_identity: dict[str, Any] = field(default_factory=dict)


def _extend_unique(target: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _as_rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _all_evidence_ids(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found: set[str] = set()
        for key, child in value.items():
            if key.endswith("evidence_ids") and isinstance(child, list):
                found.update(item for item in child if isinstance(item, str))
            else:
                found.update(_all_evidence_ids(child))
        return found
    if isinstance(value, list):
        return set().union(*(_all_evidence_ids(row) for row in value), set())
    return set()


def _listed_evidence_ids(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _task_evidence_ids(task: Mapping[str, Any]) -> set[str]:
    allowed = _listed_evidence_ids(task.get("allowed_evidence_ids"))
    allowed.update(_listed_evidence_ids(task.get("evidence_ids")))
    for row in _as_rows(task.get("evidence")):
        evidence_id = row.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            allowed.add(evidence_id)
    return allowed


def _reported_value(value: Any) -> Any:
    if isinstance(value, Mapping) and "value" in value:
        return value["value"]
    return value


def _scientific_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field_name: _reported_value(value[field_name])
        for field_name in ("formulation", "payload", "dose")
        if value.get(field_name) is not None
    }


def _same_identity_value(left: Any, right: Any) -> bool:
    if (
        not isinstance(left, bool)
        and not isinstance(right, bool)
        and isinstance(left, (int, float))
        and isinstance(right, (int, float))
    ):
        return float(left) == float(right)
    return " ".join(str(left).casefold().split()) == " ".join(
        str(right).casefold().split()
    )


def _issued_experiments(
    paper_map: Mapping[str, Any],
) -> tuple[
    OrderedDict[str, _Issuance],
    set[str],
    list[tuple[str, str | None, str | None, str, str]],
    set[str],
]:
    issued: OrderedDict[str, _Issuance] = OrderedDict()
    invalid_ids: set[str] = set()
    conflicts: list[
        tuple[str, str | None, str | None, str, str]
    ] = []

    def register(
        experiment_id: str,
        candidate_id: str | None,
        *,
        context_evidence_ids: Iterable[str] = (),
        visual_evidence_ids: Iterable[str] = (),
        scientific_identity: Mapping[str, Any] | None = None,
        check_evidence_metadata: bool = False,
        source: str,
    ) -> None:
        context_evidence = set(context_evidence_ids)
        visual_evidence = set(visual_evidence_ids)
        incoming_identity = dict(scientific_identity or {})
        existing = issued.get(experiment_id)
        if existing is None:
            existing = _Issuance(candidate_id=candidate_id)
            issued[experiment_id] = existing
        else:
            conflict_reasons: list[str] = []
            if (
                existing.candidate_id is not None
                and candidate_id is not None
                and existing.candidate_id != candidate_id
            ):
                conflict_reasons.append("candidate_id")
            conflict_reasons.extend(
                f"scientific_identity.{field_name}"
                for field_name, value in incoming_identity.items()
                if field_name in existing.scientific_identity
                and not _same_identity_value(
                    existing.scientific_identity[field_name], value
                )
            )
            if (
                check_evidence_metadata
                and existing.context_evidence_ids
                and context_evidence
                and existing.context_evidence_ids != context_evidence
            ):
                conflict_reasons.append("context_evidence_ids")
            if (
                check_evidence_metadata
                and existing.visual_evidence_ids
                and visual_evidence
                and existing.visual_evidence_ids != visual_evidence
            ):
                conflict_reasons.append("visual_evidence_ids")
            if conflict_reasons:
                invalid_ids.add(experiment_id)
                conflicts.append(
                    (
                        experiment_id,
                        existing.candidate_id,
                        candidate_id,
                        source,
                        ", ".join(conflict_reasons),
                    )
                )
        if existing.candidate_id is None and candidate_id is not None:
            existing.candidate_id = candidate_id
        existing.context_evidence_ids.update(context_evidence)
        existing.visual_evidence_ids.update(visual_evidence)
        if incoming_identity:
            for field_name, value in incoming_identity.items():
                existing.scientific_identity.setdefault(field_name, value)

    if "provisional_experiment_contexts" in paper_map:
        candidates = issue_context_candidates(paper_map)
        envelopes = context_candidate_evidence_envelopes(
            paper_map, candidates
        )
        for candidate in candidates:
            register(
                candidate.experiment_id,
                candidate.candidate_id,
                context_evidence_ids=envelopes[candidate.candidate_id],
                scientific_identity=_scientific_identity(
                    candidate.model_dump(mode="json")
                ),
                check_evidence_metadata=True,
                source="paper_map.provisional_experiment_contexts",
            )

    top_envelopes = paper_map.get("candidate_evidence_envelopes")
    if not isinstance(top_envelopes, Mapping):
        top_envelopes = {}
    for key in (
        "experiments",
        "candidates",
        "context_candidates",
        "issued_experiments",
    ):
        for index, row in enumerate(_as_rows(paper_map.get(key))):
            experiment = row.get("experiment_id")
            if not isinstance(experiment, str) or not experiment:
                continue
            candidate = row.get(
                "candidate_id", row.get("provisional_context_id")
            )
            candidate_id = candidate if isinstance(candidate, str) else None
            generic = _listed_evidence_ids(row.get("evidence_ids"))
            context_allowed = generic | _listed_evidence_ids(
                row.get("context_evidence_ids")
            )
            if candidate_id is not None:
                context_allowed.update(
                    _listed_evidence_ids(top_envelopes.get(candidate_id))
                )
            visual_allowed = generic | _listed_evidence_ids(
                row.get("visual_evidence_ids")
            )
            register(
                experiment,
                candidate_id,
                context_evidence_ids=context_allowed,
                visual_evidence_ids=visual_allowed,
                scientific_identity=_scientific_identity(row),
                check_evidence_metadata=True,
                source=f"paper_map.{key}[{index}]",
            )

    inventory = paper_map.get("experiment_inventory")
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
            generic = _all_evidence_ids(value)
            register(
                experiment,
                candidate_id,
                context_evidence_ids=generic,
                visual_evidence_ids=_listed_evidence_ids(
                    value.get("visual_evidence_ids")
                ),
                scientific_identity=_scientific_identity(value),
                check_evidence_metadata=True,
                source=f"paper_map.experiment_inventory[{inventory_id!r}]",
            )

    for task_index, task in enumerate(_as_rows(paper_map.get("context_tasks"))):
        envelopes = task.get("candidate_evidence_envelopes")
        if not isinstance(envelopes, Mapping):
            envelopes = {}
        for candidate in _as_rows(task.get("candidates")):
            experiment = candidate.get("experiment_id")
            candidate_id = candidate.get("candidate_id")
            if not isinstance(experiment, str) or not experiment:
                continue
            if not isinstance(candidate_id, str):
                candidate_id = None
            register(
                experiment,
                candidate_id,
                context_evidence_ids=_listed_evidence_ids(
                    envelopes.get(candidate_id)
                ),
                scientific_identity=_scientific_identity(candidate),
                source=f"paper_map.context_tasks[{task_index}]",
            )

    for task_index, task in enumerate(_as_rows(paper_map.get("visual_tasks"))):
        task_allowed = _task_evidence_ids(task)
        task_candidates: dict[str, str | None] = {
            item: None
            for item in task.get("experiment_ids", [])
            if isinstance(item, str) and item
        }
        for row in _as_rows(task.get("candidates")):
            experiment_id = row.get("experiment_id")
            candidate_id = row.get("candidate_id")
            if isinstance(experiment_id, str) and experiment_id:
                task_candidates[experiment_id] = (
                    candidate_id if isinstance(candidate_id, str) else None
                )
        task_inventory = task.get("experiment_inventory")
        if isinstance(task_inventory, Mapping):
            for inventory_id, row in task_inventory.items():
                if not isinstance(row, Mapping):
                    continue
                experiment_id = row.get("experiment_id", inventory_id)
                candidate_id = row.get(
                    "candidate_id", row.get("provisional_context_id")
                )
                if isinstance(experiment_id, str) and experiment_id:
                    task_candidates[experiment_id] = (
                        candidate_id
                        if isinstance(candidate_id, str)
                        else None
                    )
        experiment_envelopes = task.get("experiment_evidence_envelopes")
        if not isinstance(experiment_envelopes, Mapping):
            experiment_envelopes = {}
        slot_envelopes = task.get("slot_evidence_envelopes")
        if not isinstance(slot_envelopes, Mapping):
            slot_envelopes = {}
        task_slots = _as_rows(task.get("slots"))
        for experiment_id, candidate_id in task_candidates.items():
            explicit_experiment_evidence = _listed_evidence_ids(
                experiment_envelopes.get(experiment_id)
            )
            if task_allowed and explicit_experiment_evidence:
                explicit_experiment_evidence &= task_allowed
            visual_evidence = explicit_experiment_evidence
            if len(task_candidates) == 1 and not visual_evidence:
                visual_evidence = task_allowed
            register(
                experiment_id,
                candidate_id,
                visual_evidence_ids=visual_evidence,
                scientific_identity=(
                    _scientific_identity(task_inventory[experiment_id])
                    if isinstance(task_inventory, Mapping)
                    and isinstance(task_inventory.get(experiment_id), Mapping)
                    else None
                ),
                source=f"paper_map.visual_tasks[{task_index}]",
            )
            issuance = issued[experiment_id]
            for slot in task_slots:
                if slot.get("experiment_id") != experiment_id:
                    continue
                slot_id = slot.get("slot_id")
                if not isinstance(slot_id, str) or not slot_id:
                    continue
                slot_evidence = _listed_evidence_ids(
                    slot_envelopes.get(slot_id)
                )
                if task_allowed and slot_evidence:
                    slot_evidence &= task_allowed
                if slot_evidence:
                    issuance.visual_slot_evidence_ids[slot_id] = (
                        slot_evidence
                    )

    paper_evidence_ids = _listed_evidence_ids(
        paper_map.get("issued_evidence_ids")
    )
    paper_evidence_ids.update(
        evidence_id
        for row in issued.values()
        for evidence_id in (
            row.context_evidence_ids | row.visual_evidence_ids
        )
    )
    return issued, invalid_ids, conflicts, paper_evidence_ids


def _facts(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nested = _as_rows(row.get("facts"))
    if nested:
        return nested
    return [row] if "field_name" in row else []


_SELECTIVE_OUTCOME_FIELDS = (
    "assay",
    "endpoint",
    "comparison_target",
    "comparator",
    "outcome_value",
    "outcome_unit",
    "numeric_value",
    "numeric_unit",
    "qualitative_outcome",
    "significance_wording",
    "recipient_cell",
    "formulation",
    "payload",
    "dose",
)


def _selective_outcome_group(
    outcome: Mapping[str, Any],
) -> Mapping[str, Any]:
    slot = outcome.get("slot_id", outcome.get("outcome_id"))
    slot_id = str(slot) if slot is not None else "unscoped"
    evidence_ids = outcome.get("evidence_ids")
    facts = [
        {
            "field_name": f"outcome.{slot_id}.{field_name}",
            "raw_value": outcome[field_name],
            "evidence_ids": evidence_ids,
        }
        for field_name in _SELECTIVE_OUTCOME_FIELDS
        if outcome.get(field_name) is not None
    ]
    return {
        "experiment_id": outcome.get("experiment_id"),
        "candidate_id": outcome.get("candidate_id"),
        "_slot_id": slot_id,
        "facts": facts,
        **{
            field_name: outcome[field_name]
            for field_name in ("formulation", "payload", "dose")
            if outcome.get(field_name) is not None
        },
    }


def _experiment_groups(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for key in ("experiment_facts", "experiments"):
        rows.extend(_as_rows(result.get(key)))
    rows.extend(
        _selective_outcome_group(row)
        for row in _as_rows(result.get("outcomes"))
    )
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

    issued, invalid_ids, issuance_conflicts, paper_evidence_ids = (
        _issued_experiments(paper_map)
    )
    fact_tables: dict[
        str | None,
        OrderedDict[str, OrderedDict[str, _FactAccumulator]],
    ] = {None: OrderedDict()}
    fact_tables.update(
        (experiment_id, OrderedDict())
        for experiment_id in issued
        if experiment_id not in invalid_ids
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
        allowed_evidence_ids: set[str],
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
        outside = [
            evidence_id
            for evidence_id in dict.fromkeys(evidence)
            if evidence_id not in allowed_evidence_ids
        ]
        if outside:
            quarantine(
                code="evidence_outside_experiment_envelope",
                message=(
                    "fact cites evidence outside its locally issued "
                    "evidence envelope"
                ),
                source=source,
                experiment_id=experiment_id,
                candidate_id=candidate_id,
                field_name=field_name,
                raw_values=[str(raw_value)],
                evidence_ids=outside,
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
            allowed_evidence_ids=paper_evidence_ids,
        )

    for (
        experiment_id,
        first_candidate,
        second_candidate,
        source,
        conflict_reason,
    ) in issuance_conflicts:
        quarantine(
            code="duplicate_issued_experiment_id",
            message=(
                "duplicate experiment issuance has conflicting metadata; "
                f"candidate_ids={first_candidate!r},{second_candidate!r}; "
                f"fields={conflict_reason}"
            ),
            source=source,
            experiment_id=experiment_id,
            candidate_id=second_candidate,
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
                    allowed_evidence_ids=paper_evidence_ids,
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
                if experiment_id in invalid_ids:
                    quarantine(
                        code="ambiguous_issued_experiment_id",
                        message=(
                            "result references an experiment ID disabled by "
                            "conflicting local issuance"
                        ),
                        source=source,
                        experiment_id=experiment_id,
                        candidate_id=candidate_id,
                        raw_values=raw_values,
                        evidence_ids=evidence_ids,
                    )
                    continue
                issuance = issued[experiment_id]
                expected_candidate_id = issuance.candidate_id
                identity_mismatches = [
                    field_name
                    for field_name, expected_value in (
                        issuance.scientific_identity.items()
                    )
                    if group.get(field_name) is not None
                    and not _same_identity_value(
                        _reported_value(group[field_name]), expected_value
                    )
                ]
                if (
                    (
                        expected_candidate_id is not None
                        and candidate_id is not None
                        and candidate_id != expected_candidate_id
                    )
                    or identity_mismatches
                ):
                    quarantine(
                        code="candidate_experiment_mismatch",
                        message=(
                            "result candidate or scientific identity does not "
                            "match the locally issued experiment ID; fields="
                            f"{identity_mismatches}"
                        ),
                        source=source,
                        experiment_id=experiment_id,
                        candidate_id=candidate_id,
                        raw_values=raw_values,
                        evidence_ids=evidence_ids,
                    )
                    continue
                if source_kind == "visual_results":
                    slot_id = group.get("_slot_id")
                    allowed_evidence_ids = (
                        issuance.visual_slot_evidence_ids.get(slot_id, set())
                        if isinstance(slot_id, str)
                        else set()
                    )
                    if not allowed_evidence_ids:
                        allowed_evidence_ids = issuance.visual_evidence_ids
                    if not allowed_evidence_ids:
                        quarantine(
                            code="missing_visual_evidence_envelope",
                            message=(
                                "multi-experiment visual results require an "
                                "explicit experiment or slot evidence envelope"
                            ),
                            source=source,
                            experiment_id=experiment_id,
                            candidate_id=candidate_id,
                            raw_values=raw_values,
                            evidence_ids=evidence_ids,
                        )
                        continue
                else:
                    allowed_evidence_ids = issuance.context_evidence_ids
                for fact_offset, fact in enumerate(group_facts):
                    add_fact(
                        fact,
                        experiment_id=experiment_id,
                        candidate_id=candidate_id,
                        source=f"{source}.facts[{fact_offset}]",
                        allowed_evidence_ids=allowed_evidence_ids,
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
                candidate_id=(
                    issued[experiment_id].candidate_id
                    if experiment_id in issued
                    else None
                ),
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
        for experiment_id, issuance in issued.items()
        if experiment_id not in invalid_ids
        for candidate_id in [issuance.candidate_id]
    ]
    return MergeResult(
        shared_facts=shared_facts,
        experiments=experiments,
        quarantined_conflicts=quarantined,
        validation_findings=findings,
    )
