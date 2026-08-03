"""Deterministically score application-required extraction facts.

The evaluator is deliberately gold-blind and provider-free.  Reference facts
are supplied by the caller and are matched only by exact identifiers, field
scope, conservative canonicalization, and aliases explicitly listed in the
reference.  It never performs fuzzy scientific matching.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.extraction.application_normalization import canonicalize_fact


CATEGORIES = (
    "formulation",
    "payload_administration",
    "biological_model",
    "assay",
    "qualitative_outcome",
    "exact_numeric",
    "provenance",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryScore(_StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    recall: float = Field(ge=0.0, le=1.0)


class ApplicationScore(_StrictModel):
    """Aggregate and paper-level application information metrics."""

    evaluation_version: str = "application-requirements-score-1.0.0"
    categories: dict[str, CategoryScore]
    per_paper_categories: dict[str, dict[str, CategoryScore]]
    per_paper_recall: dict[str, float]
    overall_recall: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    matched_reference_count: int = Field(ge=0)
    reference_denominator: int = Field(ge=0)
    matched_extracted_fact_count: int = Field(ge=0)
    extracted_fact_count: int = Field(ge=0)
    wrong_arm_link_count: int = Field(ge=0)
    invented_id_count: int = Field(ge=0)
    unsupported_numeric_count: int = Field(ge=0)
    missing_reference_ids: list[str]


@dataclass(frozen=True)
class _ActualFact:
    paper_id: str
    experiment_id: str | None
    field_name: str
    values: tuple[Any, ...]
    evidence_ids: tuple[str, ...]
    provenance: str | None
    reference_ids: frozenset[str]


@dataclass(frozen=True)
class _ReferenceFact:
    reference_id: str
    paper_id: str
    experiment_id: str | None
    category: str
    field_name: str
    expected: Any
    aliases: tuple[Any, ...]


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _papers(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    papers = _rows(document.get("papers"))
    if papers:
        return papers
    return [document]


def _string_ids(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _first_text(row: Mapping[str, Any], names: Iterable[str]) -> str | None:
    for name in names:
        value = row.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _fact_values(row: Mapping[str, Any]) -> tuple[Any, ...]:
    values: list[Any] = []
    raw_values = row.get("raw_values")
    if isinstance(raw_values, Sequence) and not isinstance(
        raw_values, (str, bytes)
    ):
        values.extend(raw_values)
    for name in ("raw_value", "canonical_value", "value", "expected"):
        if name in row and row[name] is not None:
            values.append(row[name])
    unique: list[Any] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return tuple(unique)


def _provenance(row: Mapping[str, Any]) -> str | None:
    for name in ("numeric_provenance", "value_source", "provenance"):
        value = row.get(name)
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            source = _first_text(value, ("kind", "source", "type", "status"))
            if source:
                return source
    return None


def _actual_facts(document: Mapping[str, Any]) -> list[_ActualFact]:
    facts: list[_ActualFact] = []
    for paper in _papers(document):
        paper_id = _first_text(paper, ("paper_id", "id"))
        if paper_id is None:
            raise ValueError("each extraction paper requires a paper_id")

        def append(row: Mapping[str, Any], experiment_id: str | None) -> None:
            field_name = _first_text(row, ("field_name", "field"))
            values = _fact_values(row)
            if field_name is None or not values:
                return
            reference_ids = _string_ids(row.get("reference_ids"))
            direct_reference_id = _first_text(
                row, ("reference_id", "requirement_id", "gold_id")
            )
            if direct_reference_id:
                reference_ids.add(direct_reference_id)
            facts.append(
                _ActualFact(
                    paper_id=paper_id,
                    experiment_id=experiment_id,
                    field_name=field_name,
                    values=values,
                    evidence_ids=tuple(sorted(_string_ids(row.get("evidence_ids")))),
                    provenance=_provenance(row),
                    reference_ids=frozenset(reference_ids),
                )
            )

        for row in _rows(paper.get("shared_facts")):
            append(row, None)
        for experiment in _rows(paper.get("experiments")):
            experiment_id = _first_text(experiment, ("experiment_id", "id"))
            for row in _rows(experiment.get("facts")):
                append(row, experiment_id)
        for row in _rows(paper.get("facts")):
            append(row, _first_text(row, ("experiment_id", "arm_id")))
        bundles = paper.get("accepted_candidate_outcomes")
        if not isinstance(bundles, Mapping):
            bundles = paper.get("candidate_outcomes")
        bundle_rows = (
            [row for row in bundles.values() if isinstance(row, Mapping)]
            if isinstance(bundles, Mapping)
            else _rows(bundles)
        )
        for bundle in bundle_rows:
            experiment_id = _first_text(bundle, ("experiment_id", "arm_id"))
            for container, field_name in (
                ("foundational_outcomes", "foundational_outcome"),
                ("comparative_outcomes", "comparative_outcome"),
            ):
                for assertion in _rows(bundle.get(container)):
                    append(
                        {
                            "field_name": field_name,
                            "raw_value": assertion.get("raw_text"),
                            "evidence_ids": assertion.get("evidence_ids", []),
                            "numeric_provenance": assertion.get(
                                "numeric_provenance"
                            ),
                        },
                        experiment_id,
                    )
            for assertion in _rows(bundle.get("exact_measurements")):
                common = {
                    "evidence_ids": assertion.get("evidence_ids", []),
                    "numeric_provenance": assertion.get("numeric_provenance"),
                }
                append(
                    {
                        **common,
                        "field_name": "outcome_value",
                        "raw_value": assertion.get("value"),
                    },
                    experiment_id,
                )
                if assertion.get("unit") is not None:
                    append(
                        {
                            **common,
                            "field_name": "outcome_unit",
                            "raw_value": assertion["unit"],
                        },
                        experiment_id,
                    )
    return facts


def _is_explicitly_reported(row: Mapping[str, Any], category: str) -> bool:
    reported = row.get("reported", True)
    if isinstance(reported, bool):
        if not reported:
            return False
    elif isinstance(reported, str) and reported.casefold() in {
        "false",
        "no",
        "not_reported",
        "unreported",
        "missing",
    }:
        return False
    status = _first_text(
        row,
        ("report_status", "reported_status", "value_status", "numeric_provenance"),
    )
    if status and status.casefold() in {
        "not_reported",
        "unreported",
        "graph_estimated",
        "estimated",
        "not_explicit",
    }:
        return False
    if category == "exact_numeric" and row.get("expected") is None:
        return False
    return True


def _reference_rows(paper: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for name in ("reference_facts", "requirements", "facts"):
        rows = _rows(paper.get(name))
        if rows or name in paper:
            return rows
    category_rows: list[Mapping[str, Any]] = []
    for category in CATEGORIES:
        for row in _rows(paper.get(category)):
            category_rows.append({**row, "category": category})
    return category_rows


def _reference_facts(document: Mapping[str, Any]) -> list[_ReferenceFact]:
    facts: list[_ReferenceFact] = []
    seen_ids: set[str] = set()
    for paper in _papers(document):
        paper_id = _first_text(paper, ("paper_id", "id"))
        if paper_id is None:
            raise ValueError("each reference paper requires a paper_id")
        for index, row in enumerate(_reference_rows(paper)):
            reference_id = _first_text(
                row, ("reference_id", "requirement_id", "gold_id", "id")
            )
            if reference_id is None:
                raise ValueError(
                    f"reference fact {paper_id}[{index}] requires a reference_id"
                )
            if reference_id in seen_ids:
                raise ValueError(f"duplicate reference_id: {reference_id}")
            seen_ids.add(reference_id)
            category = _first_text(row, ("category",))
            if category not in CATEGORIES:
                raise ValueError(
                    f"reference {reference_id} has unknown category: {category!r}"
                )
            if not _is_explicitly_reported(row, category):
                continue
            field_name = _first_text(row, ("field_name", "field"))
            if field_name is None:
                raise ValueError(f"reference {reference_id} requires a field_name")
            aliases = row.get("aliases", [])
            if not isinstance(aliases, Sequence) or isinstance(
                aliases, (str, bytes)
            ):
                raise ValueError(f"reference {reference_id} aliases must be a list")
            facts.append(
                _ReferenceFact(
                    reference_id=reference_id,
                    paper_id=paper_id,
                    experiment_id=_first_text(
                        row, ("experiment_id", "arm_id")
                    ),
                    category=category,
                    field_name=field_name,
                    expected=row.get("expected", row.get("value")),
                    aliases=tuple(aliases),
                )
            )
    return facts


def _canonical_value(field_name: str, value: Any) -> tuple[str, Any]:
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float, Decimal)):
        try:
            return ("number", Decimal(str(value)).normalize())
        except InvalidOperation:
            pass
    if value is None:
        return ("null", None)
    text = str(value)
    try:
        number = Decimal(text.strip()).normalize()
    except InvalidOperation:
        canonical = canonicalize_fact(field_name, text, ()).canonical_value
        return ("text", canonical)
    return ("number", number)


def _same_field(actual: str, reference: str) -> bool:
    return actual == reference or actual.rsplit(".", 1)[-1] == reference


def _matches(actual: _ActualFact, reference: _ReferenceFact) -> bool:
    if actual.paper_id != reference.paper_id:
        return False
    if reference.experiment_id != actual.experiment_id:
        return False
    if reference.category == "provenance":
        leaf = reference.field_name.rsplit(".", 1)[-1]
        if leaf in {"provenance", "source", "source_type"}:
            values: tuple[Any, ...] = (
                (actual.provenance,) if actual.provenance is not None else ()
            )
        elif leaf in {"evidence_id", "evidence_ids"}:
            values = actual.evidence_ids
        elif leaf in {"arm_link", "experiment_id"}:
            values = (
                (actual.experiment_id,)
                if actual.experiment_id is not None
                else ()
            )
        else:
            return False
        expected = {
            _canonical_value(reference.field_name, value)
            for value in (reference.expected, *reference.aliases)
        }
        return any(
            _canonical_value(reference.field_name, value) in expected
            for value in values
        )
    if not _same_field(actual.field_name, reference.field_name):
        return False
    if actual.reference_ids and reference.reference_id not in actual.reference_ids:
        return False
    if reference.category == "exact_numeric" and _is_graph_estimated(actual):
        return False
    expected = {
        _canonical_value(reference.field_name, value)
        for value in (reference.expected, *reference.aliases)
    }
    return any(
        _canonical_value(reference.field_name, value) in expected
        for value in actual.values
    )


def _is_graph_estimated(fact: _ActualFact) -> bool:
    if fact.provenance is None:
        return False
    return fact.provenance.casefold().replace("-", "_").replace(" ", "_") in {
        "graph_estimated",
        "estimated_from_graph",
        "bar_height_estimate",
        "estimated",
    }


def _category_for_field(field_name: str) -> str | None:
    leaf = field_name.rsplit(".", 1)[-1]
    if leaf in {
        "formulation",
        "formulation_name",
        "component",
        "component_identity",
        "component_ratio",
        "mass_ratio",
        "molar_ratio",
        "ratio_basis",
    }:
        return "formulation"
    if leaf in {
        "payload",
        "payload_identity",
        "dose",
        "dose_unit",
        "route",
        "administration_route",
    }:
        return "payload_administration"
    if leaf in {
        "species",
        "model",
        "experimental_model",
        "disease_model",
        "tissue",
        "organ",
        "recipient_cell",
        "recipient_context",
    }:
        return "biological_model"
    if leaf in {"assay", "endpoint"}:
        return "assay"
    if leaf in {
        "foundational_outcome",
        "comparative_outcome",
        "qualitative_outcome",
        "significance_wording",
        "comparison_target",
        "comparator",
    }:
        return "qualitative_outcome"
    if leaf in {
        "outcome_value",
        "outcome_unit",
        "numeric_value",
        "numeric_unit",
        "exact_measurement",
    }:
        return "exact_numeric"
    if leaf in {"provenance", "evidence_id", "evidence_ids", "arm_link"}:
        return "provenance"
    return None


def _conflicts(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        row
        for paper in _papers(document)
        for row in _rows(paper.get("quarantined_conflicts"))
    ]


def _safety_counts(
    extraction: Mapping[str, Any],
    reference: Mapping[str, Any],
    actual_facts: Sequence[_ActualFact],
) -> tuple[int, int, int]:
    conflicts = _conflicts(extraction)
    wrong_arm = sum(
        1
        for row in conflicts
        if _first_text(row, ("code", "reason"))
        in {"candidate_experiment_mismatch", "wrong_arm_link", "wrong_arm"}
    )
    explicit_invented: set[str] = set()
    anonymous_invented_conflicts = 0
    for paper in _papers(extraction):
        explicit_invented.update(_string_ids(paper.get("invented_ids")))
    for row in conflicts:
        code = _first_text(row, ("code", "reason")) or ""
        if code.startswith("unknown_") or code.startswith("invented_"):
            explicit_invented.update(
                identifier
                for name in (
                    "experiment_id",
                    "candidate_id",
                    "evidence_id",
                    "identifier",
                )
                if isinstance((identifier := row.get(name)), str) and identifier
            )
            for name in ("candidate_ids", "evidence_ids", "identifiers"):
                explicit_invented.update(_string_ids(row.get(name)))
            if not any(
                name in row
                for name in (
                    "experiment_id",
                    "candidate_id",
                    "evidence_id",
                    "identifier",
                    "candidate_ids",
                    "evidence_ids",
                    "identifiers",
                )
            ):
                anonymous_invented_conflicts += 1

    reference_papers = {
        _first_text(paper, ("paper_id", "id")): paper
        for paper in _papers(reference)
    }
    for paper in _papers(extraction):
        paper_id = _first_text(paper, ("paper_id", "id"))
        reference_paper = reference_papers.get(paper_id)
        if reference_paper is None:
            continue
        allowed_experiments = _string_ids(reference_paper.get("experiment_ids"))
        if not allowed_experiments:
            allowed_experiments = {
                identifier
                for row in _reference_rows(reference_paper)
                if (
                    identifier := _first_text(
                        row, ("experiment_id", "arm_id")
                    )
                )
            }
        if allowed_experiments:
            extracted_experiments = {
                identifier
                for row in _rows(paper.get("experiments"))
                if (identifier := _first_text(row, ("experiment_id", "id")))
            }
            explicit_invented.update(extracted_experiments - allowed_experiments)
        allowed_evidence = _string_ids(reference_paper.get("evidence_ids"))
        if allowed_evidence:
            extracted_evidence = {
                evidence_id
                for fact in actual_facts
                if fact.paper_id == paper_id
                for evidence_id in fact.evidence_ids
            }
            explicit_invented.update(extracted_evidence - allowed_evidence)

    unsupported_numeric = sum(
        1
        for fact in actual_facts
        if _category_for_field(fact.field_name) == "exact_numeric"
        and _is_graph_estimated(fact)
    )
    invented_count = max(len(explicit_invented), anonymous_invented_conflicts)
    return wrong_arm, invented_count, unsupported_numeric


def _category_scores(
    reference_facts: Sequence[_ReferenceFact],
    matched_reference_ids: set[str],
) -> dict[str, CategoryScore]:
    scores: dict[str, CategoryScore] = {}
    for category in CATEGORIES:
        category_reference = [
            row for row in reference_facts if row.category == category
        ]
        numerator = sum(
            row.reference_id in matched_reference_ids for row in category_reference
        )
        denominator = len(category_reference)
        scores[category] = CategoryScore(
            numerator=numerator,
            denominator=denominator,
            recall=_rate(numerator, denominator),
        )
    return scores


def evaluate_application_requirements(
    extraction: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> ApplicationScore:
    """Score merged extraction facts against a separately supplied reference."""

    actual = _actual_facts(extraction)
    expected = _reference_facts(reference)
    used_actual: set[int] = set()
    matched_reference_ids: set[str] = set()
    for reference_fact in expected:
        reusable_actual = reference_fact.category == "provenance"
        match_index = next(
            (
                index
                for index, actual_fact in enumerate(actual)
                if (reusable_actual or index not in used_actual)
                and _matches(actual_fact, reference_fact)
            ),
            None,
        )
        if match_index is not None:
            if not reusable_actual:
                used_actual.add(match_index)
            matched_reference_ids.add(reference_fact.reference_id)

    paper_ids = sorted(
        {
            *(
                _first_text(paper, ("paper_id", "id"))
                for paper in _papers(reference)
            ),
            *(fact.paper_id for fact in actual),
        }
        - {None}
    )
    per_paper_categories: dict[str, dict[str, CategoryScore]] = {}
    per_paper_recall: dict[str, float] = {}
    for paper_id in paper_ids:
        paper_reference = [row for row in expected if row.paper_id == paper_id]
        per_paper_categories[paper_id] = _category_scores(
            paper_reference, matched_reference_ids
        )
        paper_numerator = sum(
            row.reference_id in matched_reference_ids for row in paper_reference
        )
        per_paper_recall[paper_id] = _rate(
            paper_numerator, len(paper_reference)
        )

    scoreable_actual = [
        fact for fact in actual if _category_for_field(fact.field_name) is not None
    ]
    matched_actual_count = sum(
        index in used_actual
        and _category_for_field(fact.field_name) is not None
        for index, fact in enumerate(actual)
    )
    wrong_arm, invented, unsupported = _safety_counts(
        extraction, reference, actual
    )
    missing = sorted(
        row.reference_id
        for row in expected
        if row.reference_id not in matched_reference_ids
    )
    return ApplicationScore(
        categories=_category_scores(expected, matched_reference_ids),
        per_paper_categories=per_paper_categories,
        per_paper_recall=per_paper_recall,
        overall_recall=_rate(len(matched_reference_ids), len(expected)),
        precision=_rate(matched_actual_count, len(scoreable_actual)),
        matched_reference_count=len(matched_reference_ids),
        reference_denominator=len(expected),
        matched_extracted_fact_count=matched_actual_count,
        extracted_fact_count=len(scoreable_actual),
        wrong_arm_link_count=wrong_arm,
        invented_id_count=invented,
        unsupported_numeric_count=unsupported,
        missing_reference_ids=missing,
    )
