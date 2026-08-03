"""Deterministically score application-required extraction facts.

The evaluator is deliberately gold-blind and provider-free.  Reference facts
are supplied by the caller and are matched only by exact identifiers, field
scope, conservative canonicalization, and aliases explicitly listed in the
reference.  It never performs fuzzy scientific matching.
"""

from __future__ import annotations

from collections import defaultdict
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


def _matches_content(actual: _ActualFact, reference: _ReferenceFact) -> bool:
    if actual.paper_id != reference.paper_id:
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
    if _category_for_field(actual.field_name) != reference.category:
        return False
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


def _matches(actual: _ActualFact, reference: _ReferenceFact) -> bool:
    return (
        reference.experiment_id == actual.experiment_id
        and _matches_content(actual, reference)
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


def _conflicts(
    document: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    return [
        (paper_id, row)
        for paper in _papers(document)
        if (paper_id := _first_text(paper, ("paper_id", "id"))) is not None
        for row in _rows(paper.get("quarantined_conflicts"))
    ]


def _reference_papers(
    document: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    return {
        paper_id: paper
        for paper in _papers(document)
        if (paper_id := _first_text(paper, ("paper_id", "id"))) is not None
    }


def _allowed_experiment_ids(paper: Mapping[str, Any]) -> set[str]:
    identifiers = _string_ids(paper.get("experiment_ids"))
    if identifiers:
        return identifiers
    return {
        identifier
        for row in _reference_rows(paper)
        if (identifier := _first_text(row, ("experiment_id", "arm_id")))
    }


def _bundle_rows(paper: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bundles = paper.get("accepted_candidate_outcomes")
    if not isinstance(bundles, Mapping):
        bundles = paper.get("candidate_outcomes")
    if isinstance(bundles, Mapping):
        return [row for row in bundles.values() if isinstance(row, Mapping)]
    return _rows(bundles)


def _extracted_experiment_ids(
    paper: Mapping[str, Any],
    actual_facts: Sequence[_ActualFact],
    paper_id: str,
) -> set[str]:
    identifiers = {
        fact.experiment_id
        for fact in actual_facts
        if fact.paper_id == paper_id and fact.experiment_id is not None
    }
    identifiers.update(
        identifier
        for row in _rows(paper.get("experiments"))
        if (identifier := _first_text(row, ("experiment_id", "id")))
    )
    identifiers.update(
        identifier
        for row in _bundle_rows(paper)
        if (identifier := _first_text(row, ("experiment_id", "arm_id")))
    )
    return identifiers


def _wrong_arm_count(
    extraction: Mapping[str, Any],
    reference: Mapping[str, Any],
    actual_facts: Sequence[_ActualFact],
    reference_facts: Sequence[_ReferenceFact],
) -> int:
    reference_papers = _reference_papers(reference)
    detected: set[tuple[str, str, str, tuple[tuple[str, Any], ...]]] = set()
    for actual in actual_facts:
        if actual.experiment_id is None:
            continue
        reference_paper = reference_papers.get(actual.paper_id)
        if reference_paper is None:
            continue
        valid_ids = _allowed_experiment_ids(reference_paper)
        if actual.experiment_id not in valid_ids:
            continue
        if any(_matches(actual, expected) for expected in reference_facts):
            continue
        if any(
            expected.experiment_id is not None
            and expected.experiment_id != actual.experiment_id
            and expected.experiment_id in valid_ids
            and _matches_content(actual, expected)
            for expected in reference_facts
        ):
            detected.add(
                (
                    actual.paper_id,
                    actual.experiment_id,
                    actual.field_name.rsplit(".", 1)[-1],
                    tuple(
                        dict.fromkeys(
                            _canonical_value(actual.field_name, value)
                            for value in actual.values
                        )
                    ),
                )
            )

    quarantined: set[tuple[str, str | None, str | None]] = set()
    anonymous = 0
    for paper_id, row in _conflicts(extraction):
        if _first_text(row, ("code", "reason")) not in {
            "candidate_experiment_mismatch",
            "wrong_arm_link",
            "wrong_arm",
        }:
            continue
        experiment_id = _first_text(row, ("experiment_id", "arm_id"))
        field_name = _first_text(row, ("field_name", "field"))
        field_leaf = field_name.rsplit(".", 1)[-1] if field_name else None
        if experiment_id is None and field_leaf is None:
            anonymous += 1
        else:
            quarantined.add((paper_id, experiment_id, field_leaf))

    additional_quarantines = sum(
        not any(
            detected_paper == paper_id
            and (experiment_id is None or detected_experiment == experiment_id)
            and (field_name is None or detected_field == field_name)
            for (
                detected_paper,
                detected_experiment,
                detected_field,
                _,
            ) in detected
        )
        for paper_id, experiment_id, field_name in quarantined
    )
    return len(detected) + additional_quarantines + anonymous


def _contains_number(fact: _ActualFact) -> bool:
    return any(
        _canonical_value(fact.field_name, value)[0] == "number"
        for value in fact.values
    )


def _unsupported_numeric_count(
    actual_facts: Sequence[_ActualFact],
    reference_facts: Sequence[_ReferenceFact],
) -> int:
    count = 0
    for fact in actual_facts:
        if (
            _category_for_field(fact.field_name) != "exact_numeric"
            or not _contains_number(fact)
        ):
            continue
        if _is_graph_estimated(fact):
            count += 1
            continue
        provenance = (fact.provenance or "").casefold().replace("-", "_")
        if provenance != "exact_reported":
            continue
        if not any(
            reference.category == "exact_numeric"
            and _matches(fact, reference)
            for reference in reference_facts
        ):
            count += 1
    return count


def _safety_counts(
    extraction: Mapping[str, Any],
    reference: Mapping[str, Any],
    actual_facts: Sequence[_ActualFact],
    reference_facts: Sequence[_ReferenceFact],
) -> tuple[int, int, int]:
    conflicts = _conflicts(extraction)
    wrong_arm = _wrong_arm_count(
        extraction, reference, actual_facts, reference_facts
    )
    explicit_invented: set[str] = set()
    anonymous_invented_conflicts = 0
    for paper in _papers(extraction):
        explicit_invented.update(_string_ids(paper.get("invented_ids")))
    for _, row in conflicts:
        code = _first_text(row, ("code", "reason")) or ""
        if code.startswith("unknown_") or code.startswith("invented_"):
            row_identifiers = {
                identifier
                for name in (
                    "experiment_id",
                    "candidate_id",
                    "evidence_id",
                    "identifier",
                )
                if isinstance((identifier := row.get(name)), str) and identifier
            }
            for name in ("candidate_ids", "evidence_ids", "identifiers"):
                row_identifiers.update(_string_ids(row.get(name)))
            explicit_invented.update(row_identifiers)
            if not row_identifiers:
                anonymous_invented_conflicts += 1

    reference_papers = _reference_papers(reference)
    for paper in _papers(extraction):
        paper_id = _first_text(paper, ("paper_id", "id"))
        reference_paper = reference_papers.get(paper_id)
        if reference_paper is None:
            continue
        allowed_experiments = _allowed_experiment_ids(reference_paper)
        if allowed_experiments:
            extracted_experiments = _extracted_experiment_ids(
                paper, actual_facts, paper_id
            )
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

    unsupported_numeric = _unsupported_numeric_count(
        actual_facts, reference_facts
    )
    invented_count = len(explicit_invented) + anonymous_invented_conflicts
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


def _maximum_matches(
    actual_facts: Sequence[_ActualFact],
    reference_facts: Sequence[_ReferenceFact],
) -> tuple[set[str], set[int]]:
    """Return deterministic maximum one-to-one matches within fact groups."""

    groups: dict[tuple[str, str, str, str | None], list[int]] = defaultdict(list)
    for index, reference in enumerate(reference_facts):
        groups[
            (
                reference.paper_id,
                reference.category,
                reference.field_name.rsplit(".", 1)[-1],
                reference.experiment_id,
            )
        ].append(index)

    matched_reference_ids: set[str] = set()
    matched_actual_indices: set[int] = set()
    for group in sorted(groups, key=lambda value: tuple(str(item) for item in value)):
        reference_indices = sorted(
            groups[group], key=lambda index: reference_facts[index].reference_id
        )
        adjacency = {
            reference_index: sorted(
                (
                    actual_index
                    for actual_index, actual in enumerate(actual_facts)
                    if _matches(actual, reference_facts[reference_index])
                ),
                key=lambda index: (
                    actual_facts[index].field_name,
                    repr(
                        tuple(
                            _canonical_value(actual_facts[index].field_name, value)
                            for value in actual_facts[index].values
                        )
                    ),
                    index,
                ),
            )
            for reference_index in reference_indices
        }
        actual_owner: dict[int, int] = {}

        def augment(reference_index: int, seen: set[int]) -> bool:
            for actual_index in adjacency[reference_index]:
                if actual_index in seen:
                    continue
                seen.add(actual_index)
                owner = actual_owner.get(actual_index)
                if owner is None or augment(owner, seen):
                    actual_owner[actual_index] = reference_index
                    return True
            return False

        for reference_index in reference_indices:
            augment(reference_index, set())
        for actual_index, reference_index in actual_owner.items():
            reference = reference_facts[reference_index]
            matched_reference_ids.add(reference.reference_id)
            if reference.category != "provenance":
                matched_actual_indices.add(actual_index)
    return matched_reference_ids, matched_actual_indices


def evaluate_application_requirements(
    extraction: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> ApplicationScore:
    """Score merged extraction facts against a separately supplied reference."""

    actual = _actual_facts(extraction)
    expected = _reference_facts(reference)
    matched_reference_ids, matched_actual_indices = _maximum_matches(
        actual, expected
    )

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
        index in matched_actual_indices
        and _category_for_field(fact.field_name) is not None
        for index, fact in enumerate(actual)
    )
    wrong_arm, invented, unsupported = _safety_counts(
        extraction, reference, actual, expected
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
