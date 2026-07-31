"""Score merged full-paper extraction artifacts against a separately loaded key.

The evaluator is deliberately downstream of extraction.  It accepts only local
artifact and answer-key paths, performs deterministic exact/alias matching, and
never contacts a provider.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FullPaperScore(BaseModel):
    """Deterministic benchmark metrics with explicit numerator denominators."""

    model_config = ConfigDict(extra="forbid")

    evaluation_version: str = "full-paper-benchmark-score-1.0.0"
    paper_id: str
    artifact_path: str
    overall_micro_recall: float = Field(ge=0.0, le=1.0)
    shared_paper_recall: float = Field(ge=0.0, le=1.0)
    experiment_fact_recall: float = Field(ge=0.0, le=1.0)
    complete_arm_recall: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    matched_gold_fact_count: int = Field(ge=0)
    total_gold_fact_count: int = Field(ge=0)
    matched_shared_fact_count: int = Field(ge=0)
    total_shared_fact_count: int = Field(ge=0)
    matched_experiment_fact_count: int = Field(ge=0)
    total_experiment_fact_count: int = Field(ge=0)
    complete_arm_count: int = Field(ge=0)
    total_arm_count: int = Field(ge=0)
    correct_extracted_fact_count: int = Field(ge=0)
    extracted_benchmark_fact_count: int = Field(ge=0)
    duplicate_extracted_fact_count: int = Field(ge=0)
    unsupported_invention_count: int = Field(ge=0)
    wrong_arm_link_count: int = Field(ge=0)
    missing_gold_ids: list[str]
    per_recipient_context_recall: dict[str, float]
    paid_api_requests: int = Field(default=0, ge=0)


_ARTIFACT_NAMES = (
    "merged_extraction.json",
    "merged_result.json",
    "final_result.json",
    "result.json",
    "merged.json",
    "extraction.json",
)
_PAPER_MAP_NAMES = (
    "paper_map.json",
    "validated_paper_map.json",
    "map_result.json",
)
_ARM_IDENTITY_FIELDS = (
    "formulation",
    "payload",
    "dose",
    "dose_unit",
    "recipient_context",
)
_REQUIRED_GOLD_FIELDS = {
    "gold_id",
    "namespace",
    "entity",
    "arm",
    "field",
    "expected",
    "aliases",
    "source_quote",
    "source_locator",
    "criticality",
}


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _artifact_path(extraction_dir: Path) -> Path:
    if not extraction_dir.is_dir():
        raise NotADirectoryError(
            f"extraction_dir is not a directory: {extraction_dir}"
        )
    for name in _ARTIFACT_NAMES:
        path = extraction_dir / name
        if path.is_file():
            return path
    recursive = sorted(
        path
        for name in _ARTIFACT_NAMES
        for path in extraction_dir.rglob(name)
        if path.is_file()
    )
    if len(recursive) == 1:
        return recursive[0]
    if not recursive:
        raise FileNotFoundError(
            "no merged extraction artifact found; expected one of "
            f"{list(_ARTIFACT_NAMES)} under {extraction_dir}"
        )
    raise ValueError(
        "multiple merged extraction artifacts found; pass a directory "
        f"containing exactly one benchmark target: {recursive}"
    )


def _paper_map(extraction_dir: Path, artifact: Mapping[str, Any]) -> dict[str, Any] | None:
    embedded = artifact.get("paper_map")
    if isinstance(embedded, dict):
        return embedded
    for name in _PAPER_MAP_NAMES:
        path = extraction_dir / name
        if path.is_file():
            return _load_object(path, label="paper map")
    return None


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(
        str.maketrans(
            {
                "μ": "u",
                "µ": "u",
                "–": "-",
                "—": "-",
                "−": "-",
                "‐": "-",
                "‑": "-",
                "⁄": "/",
            }
        )
    )
    normalized = normalized.casefold().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*([/:])\s*", r"\1", normalized)
    return normalized


def _canonical_number(value: int | float | Decimal) -> tuple[str, str]:
    try:
        number = Decimal(str(value)).normalize()
    except InvalidOperation as error:
        raise ValueError(f"invalid numeric benchmark value: {value!r}") from error
    return ("number", format(number, "f"))


def _canonical_value(value: Any) -> Any:
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float, Decimal)):
        return _canonical_number(value)
    if isinstance(value, str):
        return ("text", _normalize_text(value))
    if isinstance(value, list):
        return ("list", tuple(_canonical_value(item) for item in value))
    if isinstance(value, Mapping):
        return (
            "object",
            tuple(
                sorted(
                    (
                        _normalize_text(str(key)),
                        _canonical_value(child),
                    )
                    for key, child in value.items()
                )
            ),
        )
    if value is None:
        return ("null", None)
    raise ValueError(f"unsupported benchmark value type: {type(value).__name__}")


def _matches_expected(actual: Any, gold: Mapping[str, Any]) -> bool:
    actual_key = _canonical_value(actual)
    candidates = [gold["expected"], *gold.get("aliases", [])]
    return any(actual_key == _canonical_value(value) for value in candidates)


def _validate_gold(gold: Mapping[str, Any]) -> list[dict[str, Any]]:
    paper_id = gold.get("paper_id")
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("gold paper_id must be a non-empty string")
    facts: list[dict[str, Any]] = []
    for container, namespace in (
        ("shared_facts", "shared"),
        ("experiment_facts", "experiment"),
    ):
        rows = gold.get(container)
        if not isinstance(rows, list):
            raise ValueError(f"gold {container} must be a list")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"gold {container}[{index}] must be an object")
            missing = sorted(_REQUIRED_GOLD_FIELDS - set(row))
            if missing:
                raise ValueError(
                    f"gold {container}[{index}] is missing fields: {missing}"
                )
            if not isinstance(row["gold_id"], str) or not row["gold_id"].strip():
                raise ValueError(
                    f"gold {container}[{index}].gold_id must be non-empty"
                )
            if row["namespace"] != namespace:
                raise ValueError(
                    f"gold {container}[{index}] has namespace "
                    f"{row['namespace']!r}, expected {namespace!r}"
                )
            if not isinstance(row["aliases"], list):
                raise ValueError(
                    f"gold {container}[{index}].aliases must be a list"
                )
            entity = row["entity"]
            if not isinstance(entity, dict) or not entity.get(
                "entity_type"
            ) or not entity.get("identity"):
                raise ValueError(
                    f"gold {container}[{index}].entity lacks semantic identity"
                )
            if namespace == "experiment":
                arm = row["arm"]
                if not isinstance(arm, dict):
                    raise ValueError(
                        f"gold {container}[{index}].arm must be an object"
                    )
                missing_arm = [
                    field for field in _ARM_IDENTITY_FIELDS if arm.get(field) is None
                ]
                if missing_arm or not arm.get("arm_id"):
                    raise ValueError(
                        f"gold {container}[{index}].arm lacks identity fields: "
                        f"{missing_arm}"
                    )
            facts.append(row)
    ids = [row["gold_id"] for row in facts]
    if len(ids) != len(set(ids)):
        duplicates = sorted(
            identifier for identifier in set(ids) if ids.count(identifier) > 1
        )
        raise ValueError(f"gold_id values must be unique: {duplicates}")
    return facts


def _entity_matches(
    actual: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> bool:
    if not isinstance(actual, Mapping):
        return False
    if _normalize_text(str(actual.get("entity_type", ""))) != _normalize_text(
        str(expected.get("entity_type", ""))
    ):
        return False
    actual_identity = _canonical_value(actual.get("identity"))
    identities = [expected.get("identity"), *expected.get("aliases", [])]
    return any(actual_identity == _canonical_value(value) for value in identities)


def _alias_groups(
    gold_facts: Iterable[Mapping[str, Any]],
) -> dict[str, dict[Any, set[Any]]]:
    groups: dict[str, dict[Any, set[Any]]] = defaultdict(dict)
    for fact in gold_facts:
        field = str(fact["field"])
        canonical = _canonical_value(fact["expected"])
        values = {
            canonical,
            *(_canonical_value(value) for value in fact.get("aliases", [])),
        }
        groups[field].setdefault(canonical, set()).update(values)
    return groups


def _identity_value_matches(
    actual: Any,
    expected: Any,
    *,
    field: str,
    alias_groups: Mapping[str, Mapping[Any, set[Any]]],
) -> bool:
    actual_key = _canonical_value(actual)
    expected_key = _canonical_value(expected)
    if actual_key == expected_key:
        return True
    return actual_key in alias_groups.get(field, {}).get(expected_key, set())


def _arm_matches(
    actual: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
    *,
    alias_groups: Mapping[str, Mapping[Any, set[Any]]],
) -> bool:
    if not isinstance(actual, Mapping):
        return False
    return all(
        actual.get(field) is not None
        and _identity_value_matches(
            actual[field],
            expected[field],
            field=field,
            alias_groups=alias_groups,
        )
        for field in _ARM_IDENTITY_FIELDS
    )


def _reported_value(value: Any) -> Any | None:
    if not isinstance(value, Mapping):
        return value
    if value.get("status") == "missing":
        return None
    if "value" in value:
        return value["value"]
    return value


def _actual_fact(
    *,
    namespace: str,
    entity_type: str,
    entity_identity: str,
    field: str,
    value: Any,
    arm: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "namespace": namespace,
        "entity": {
            "entity_type": entity_type,
            "identity": entity_identity,
        },
        "arm": arm,
        "field": field,
        "value": value,
    }


def _projected_facts(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for container, namespace in (
        ("shared_facts", "shared"),
        ("experiment_facts", "experiment"),
    ):
        rows = artifact.get(container, [])
        if not isinstance(rows, list):
            raise ValueError(f"artifact {container} must be a list")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(
                    f"artifact {container}[{index}] must be an object"
                )
            if row.get("namespace") != namespace:
                raise ValueError(
                    f"artifact {container}[{index}] namespace must be {namespace!r}"
                )
            if not row.get("field") or "value" not in row:
                raise ValueError(
                    f"artifact {container}[{index}] requires field and value"
                )
            facts.append(row)
    return facts


def _paper_map_facts(
    paper_id: str,
    paper_map: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if paper_map is None:
        return []
    facts: list[dict[str, Any]] = []
    for formulation in paper_map.get("formulations", []):
        if not isinstance(formulation, Mapping):
            continue
        name = _reported_value(formulation.get("name"))
        if name is None:
            continue
        facts.append(
            _actual_fact(
                namespace="shared",
                entity_type="formulation",
                entity_identity=str(name),
                field="formulation",
                value=name,
            )
        )
        role_order: list[Any] = []
        for component in formulation.get("components", []):
            if not isinstance(component, Mapping):
                continue
            identity = _reported_value(component.get("identity"))
            role = _reported_value(component.get("role"))
            if identity is not None:
                facts.append(
                    _actual_fact(
                        namespace="shared",
                        entity_type="formulation",
                        entity_identity=str(name),
                        field="component",
                        value=identity,
                    )
                )
            if role is not None:
                role_order.append(role)
        if role_order:
            facts.append(
                _actual_fact(
                    namespace="shared",
                    entity_type="formulation",
                    entity_identity=str(name),
                    field="component_order",
                    value=role_order,
                )
            )
        for ratio in formulation.get("ratios", []):
            value = _reported_value(ratio)
            if value is not None:
                facts.append(
                    _actual_fact(
                        namespace="shared",
                        entity_type="formulation",
                        entity_identity=str(name),
                        field="ratio",
                        value=value,
                    )
                )
        for basis in formulation.get("ratio_bases", []):
            value = _reported_value(basis)
            if value is not None:
                facts.append(
                    _actual_fact(
                        namespace="shared",
                        entity_type="formulation",
                        entity_identity=str(name),
                        field="ratio_basis",
                        value=value,
                    )
                )
    for payload in paper_map.get("payloads", []):
        if not isinstance(payload, Mapping):
            continue
        identity = _reported_value(payload.get("identity"))
        if identity is None:
            continue
        facts.append(
            _actual_fact(
                namespace="shared",
                entity_type="payload",
                entity_identity=str(identity),
                field="payload",
                value=identity,
            )
        )
        role = _reported_value(payload.get("role"))
        if role is not None:
            facts.append(
                _actual_fact(
                    namespace="shared",
                    entity_type="payload",
                    entity_identity=str(identity),
                    field="payload_role",
                    value=role,
                )
            )
    for source_field, target_field in (
        ("common_routes", "route"),
        ("common_species", "species"),
        ("common_models", "experimental_model"),
    ):
        for row in paper_map.get(source_field, []):
            value = _reported_value(row)
            if value is not None:
                facts.append(
                    _actual_fact(
                        namespace="shared",
                        entity_type="paper",
                        entity_identity=paper_id,
                        field=target_field,
                        value=value,
                    )
                )
    return facts


def _compact_facts(
    artifact: Mapping[str, Any],
    paper_map: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    paper_id = str(artifact.get("paper_id", ""))
    facts = _paper_map_facts(paper_id, paper_map)
    formulations_by_id: dict[str, str] = {}
    for formulation in artifact.get("formulations", []):
        if not isinstance(formulation, Mapping):
            continue
        formulation_id = str(formulation.get("formulation_id", ""))
        name = _reported_value(formulation.get("formulation_name"))
        identity = str(name if name is not None else formulation_id)
        formulations_by_id[formulation_id] = identity
        for source_field, target_field in (
            ("formulation_name", "formulation"),
            ("composition", "composition"),
            ("composition_basis", "ratio_basis"),
            ("np_ratio", "np_ratio"),
        ):
            value = _reported_value(formulation.get(source_field))
            if value is not None:
                facts.append(
                    _actual_fact(
                        namespace="shared",
                        entity_type="formulation",
                        entity_identity=identity,
                        field=target_field,
                        value=value,
                    )
                )
    for component in artifact.get("components", []):
        if not isinstance(component, Mapping):
            continue
        formulation_id = str(component.get("formulation_id", ""))
        parent = formulations_by_id.get(formulation_id, formulation_id)
        identity = _reported_value(component.get("identity"))
        if identity is not None:
            facts.append(
                _actual_fact(
                    namespace="shared",
                    entity_type="formulation",
                    entity_identity=parent,
                    field="component",
                    value=identity,
                )
            )
        role = _reported_value(component.get("role"))
        if role is not None and identity is not None:
            facts.append(
                _actual_fact(
                    namespace="shared",
                    entity_type="component",
                    entity_identity=str(identity),
                    field="component_role",
                    value=role,
                )
            )

    experiment_arms: dict[str, dict[str, Any]] = {}
    seen_shared: set[Any] = set()
    experiment_field_map = (
        ("payload_name", "payload"),
        ("payload_role", "payload_role"),
        ("dose", "dose"),
        ("dose_unit", "dose_unit"),
        ("delivery_recipient_cell", "recipient_context"),
        ("route", "route"),
        ("species", "species"),
        ("experimental_model", "experimental_model"),
        ("tissue_or_organ", "tissue"),
        ("timepoint", "timepoint"),
        ("timepoint_unit", "timepoint_unit"),
    )
    for experiment in artifact.get("experiments", []):
        if not isinstance(experiment, Mapping):
            continue
        experiment_id = str(experiment.get("experiment_id", ""))
        formulation_id = str(experiment.get("formulation_id", ""))
        formulation = formulations_by_id.get(formulation_id, formulation_id)
        payload = _reported_value(experiment.get("payload_name"))
        dose = _reported_value(experiment.get("dose"))
        dose_unit = _reported_value(experiment.get("dose_unit"))
        recipient = _reported_value(experiment.get("delivery_recipient_cell"))
        arm = {
            "formulation": formulation,
            "payload": payload,
            "dose": dose,
            "dose_unit": dose_unit,
            "recipient_context": recipient,
        }
        experiment_arms[experiment_id] = arm
        facts.append(
            _actual_fact(
                namespace="experiment",
                entity_type="arm",
                entity_identity=experiment_id,
                field="formulation",
                value=formulation,
                arm=arm,
            )
        )
        for source_field, target_field in experiment_field_map:
            value = _reported_value(experiment.get(source_field))
            if value is None:
                continue
            facts.append(
                _actual_fact(
                    namespace="experiment",
                    entity_type="arm",
                    entity_identity=experiment_id,
                    field=target_field,
                    value=value,
                    arm=arm,
                )
            )
            if target_field in {
                "payload",
                "payload_role",
                "route",
                "species",
                "experimental_model",
                "tissue",
                "timepoint",
                "timepoint_unit",
            }:
                shared_entity_type = (
                    "payload"
                    if target_field in {"payload", "payload_role"}
                    else "paper"
                )
                shared_identity = str(payload) if shared_entity_type == "payload" else paper_id
                shared_key = (
                    target_field,
                    _canonical_value(value),
                    shared_entity_type,
                    shared_identity,
                )
                if shared_key not in seen_shared:
                    seen_shared.add(shared_key)
                    facts.append(
                        _actual_fact(
                            namespace="shared",
                            entity_type=shared_entity_type,
                            entity_identity=shared_identity,
                            field=target_field,
                            value=value,
                        )
                    )
    for outcome in artifact.get("outcomes", []):
        if not isinstance(outcome, Mapping):
            continue
        experiment_id = str(outcome.get("experiment_id", ""))
        arm = experiment_arms.get(experiment_id)
        for field in (
            "assay",
            "endpoint",
            "comparator",
            "outcome_value",
            "outcome_unit",
            "qualitative_outcome",
        ):
            value = _reported_value(outcome.get(field))
            if value is None:
                continue
            facts.append(
                _actual_fact(
                    namespace="experiment",
                    entity_type="arm",
                    entity_identity=experiment_id,
                    field=field,
                    value=value,
                    arm=arm,
                )
            )
    return facts


def _extracted_facts(
    artifact: Mapping[str, Any],
    paper_map: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if "shared_facts" in artifact or "experiment_facts" in artifact:
        return _projected_facts(artifact)
    return _compact_facts(artifact, paper_map)


def evaluate(extraction_dir: Path, gold_path: Path) -> FullPaperScore:
    """Evaluate one local merged artifact against one caller-supplied gold key."""

    extraction_dir = Path(extraction_dir)
    gold_path = Path(gold_path)
    artifact_path = _artifact_path(extraction_dir)
    artifact = _load_object(artifact_path, label="merged extraction artifact")
    gold = _load_object(gold_path, label="full-paper answer key")
    gold_facts = _validate_gold(gold)
    paper_id = str(gold["paper_id"])
    if artifact.get("paper_id") != paper_id:
        raise ValueError(
            "artifact paper_id does not match gold paper_id: "
            f"{artifact.get('paper_id')!r} != {paper_id!r}"
        )

    extracted = _extracted_facts(
        artifact,
        _paper_map(extraction_dir, artifact),
    )
    benchmark_fields = {
        (str(fact["namespace"]), str(fact["field"])) for fact in gold_facts
    }
    benchmark_extracted = [
        fact
        for fact in extracted
        if (str(fact.get("namespace")), str(fact.get("field")))
        in benchmark_fields
    ]
    aliases = _alias_groups(gold_facts)
    matched_ids: set[str] = set()
    correct_extracted = 0
    unsupported = 0
    wrong_links = 0
    duplicates = 0

    for actual in benchmark_extracted:
        namespace = str(actual.get("namespace"))
        field = str(actual.get("field"))
        value_candidates = [
            fact
            for fact in gold_facts
            if fact["namespace"] == namespace
            and fact["field"] == field
            and _matches_expected(actual.get("value"), fact)
        ]
        if namespace == "experiment":
            correctly_linked = [
                fact
                for fact in value_candidates
                if _arm_matches(
                    actual.get("arm"),
                    fact["arm"],
                    alias_groups=aliases,
                )
            ]
        else:
            correctly_linked = [
                fact
                for fact in value_candidates
                if _entity_matches(actual.get("entity"), fact["entity"])
            ]
        available = [
            fact for fact in correctly_linked if fact["gold_id"] not in matched_ids
        ]
        if available:
            matched_ids.add(available[0]["gold_id"])
            correct_extracted += 1
        elif correctly_linked:
            duplicates += 1
        elif namespace == "experiment" and value_candidates:
            wrong_links += 1
        else:
            unsupported += 1

    shared = [fact for fact in gold_facts if fact["namespace"] == "shared"]
    experiments = [
        fact for fact in gold_facts if fact["namespace"] == "experiment"
    ]
    matched_shared = sum(fact["gold_id"] in matched_ids for fact in shared)
    matched_experiments = sum(
        fact["gold_id"] in matched_ids for fact in experiments
    )
    arm_facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    context_facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in experiments:
        arm_facts[str(fact["arm"]["arm_id"])].append(fact)
        context_facts[str(fact["arm"]["recipient_context"])].append(fact)
    complete_arms = sum(
        all(fact["gold_id"] in matched_ids for fact in facts)
        for facts in arm_facts.values()
    )
    missing = [
        fact["gold_id"] for fact in gold_facts if fact["gold_id"] not in matched_ids
    ]
    return FullPaperScore(
        paper_id=paper_id,
        artifact_path=str(artifact_path),
        overall_micro_recall=_rate(len(matched_ids), len(gold_facts)),
        shared_paper_recall=_rate(matched_shared, len(shared)),
        experiment_fact_recall=_rate(matched_experiments, len(experiments)),
        complete_arm_recall=_rate(complete_arms, len(arm_facts)),
        precision=_rate(correct_extracted, len(benchmark_extracted)),
        matched_gold_fact_count=len(matched_ids),
        total_gold_fact_count=len(gold_facts),
        matched_shared_fact_count=matched_shared,
        total_shared_fact_count=len(shared),
        matched_experiment_fact_count=matched_experiments,
        total_experiment_fact_count=len(experiments),
        complete_arm_count=complete_arms,
        total_arm_count=len(arm_facts),
        correct_extracted_fact_count=correct_extracted,
        extracted_benchmark_fact_count=len(benchmark_extracted),
        duplicate_extracted_fact_count=duplicates,
        unsupported_invention_count=unsupported,
        wrong_arm_link_count=wrong_links,
        missing_gold_ids=missing,
        per_recipient_context_recall={
            context: _rate(
                sum(fact["gold_id"] in matched_ids for fact in facts),
                len(facts),
            )
            for context, facts in sorted(context_facts.items())
        },
    )
