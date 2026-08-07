"""Deterministic canonical-row deduplication with provenance reassignment."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DeduplicationResult:
    source_arm_count: int
    canonical_arm_count: int
    duplicate_arms_removed: int
    source_occurrence_count: int
    canonical_component_count: int
    duplicate_components_removed: int
    evidence_occurrence_count: int
    canonical_evidence_count: int
    duplicate_evidence_removed: int


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _species(value: object) -> str:
    normalized = _text(value)
    if any(token in normalized for token in ("mouse", "mice", "mus musculus")):
        return "mouse"
    return normalized


def _time_unit(value: object) -> str:
    normalized = _text(value)
    normalized = normalized.replace("after injection", "").strip()
    return normalized.rstrip("s")


def _model_identity(species: object, disease_model: object) -> str:
    combined = f"{_text(species)} {_text(disease_model)}"
    if "ai14" in combined:
        return "ai14 reporter mouse"
    return _text(disease_model)


def _combined(values: list[object]) -> str | None:
    seen: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen and normalized != "not_reported":
            seen.append(normalized)
    return "; ".join(seen) or None


def _merge_arm_dependencies(
    connection: sqlite3.Connection,
    tables: set[str],
    keep: int,
    duplicate: int,
) -> None:
    connection.execute(
        "UPDATE outcome SET experiment_id=? WHERE experiment_id=?",
        (keep, duplicate),
    )
    connection.execute(
        "UPDATE evidence SET experiment_id=? WHERE experiment_id=?",
        (keep, duplicate),
    )
    if "field_verification" in tables:
        connection.execute(
            "UPDATE field_verification SET experiment_id=? WHERE experiment_id=?",
            (keep, duplicate),
        )
    if "missing_field" in tables:
        connection.execute(
            "UPDATE missing_field SET experiment_id=? WHERE experiment_id=?",
            (keep, duplicate),
        )
    if "import_field_evidence" in tables:
        connection.execute(
            "UPDATE OR IGNORE import_field_evidence SET entity_id=? "
            "WHERE entity_type='arm' AND entity_id=?",
            (keep, duplicate),
        )
        connection.execute(
            "DELETE FROM import_field_evidence "
            "WHERE entity_type='arm' AND entity_id=?",
            (duplicate,),
        )
    if "record_source" in tables:
        connection.execute(
            "UPDATE record_source SET entity_id=? "
            "WHERE entity_type='experiment' AND entity_id=?",
            (keep, duplicate),
        )
    if "import_record_identity" in tables:
        connection.execute(
            "UPDATE OR IGNORE import_record_identity SET entity_id=? "
            "WHERE entity_type='experiment' AND entity_id=?",
            (keep, duplicate),
        )
        connection.execute(
            "DELETE FROM import_record_identity "
            "WHERE entity_type='experiment' AND entity_id=?",
            (duplicate,),
        )
    if "fact_projection" in tables:
        connection.execute(
            "UPDATE OR IGNORE fact_projection SET entity_id=? "
            "WHERE entity_type IN ('arm','experiment') AND entity_id=?",
            (keep, duplicate),
        )
        connection.execute(
            "DELETE FROM fact_projection "
            "WHERE entity_type IN ('arm','experiment') AND entity_id=?",
            (duplicate,),
        )
    if "arm_assessment" in tables:
        connection.execute(
            "DELETE FROM arm_assessment WHERE experiment_id=?", (duplicate,)
        )
    if "eligibility_result" in tables:
        connection.execute(
            "DELETE FROM eligibility_result WHERE experiment_id=?", (duplicate,)
        )


def _deduplicate_arms(
    connection: sqlite3.Connection, tables: set[str]
) -> tuple[int, int]:
    rows = connection.execute(
        """SELECT experiment_id,paper_id,formulation_id,payload_type,payload_name,
                  species,disease_model,in_vitro_in_vivo,dose,dose_unit,route,
                  timepoint,timepoint_unit,protocol_reference,
                  intended_target_cell,target_or_recipient_organ,
                  observed_transfected_cell,cell_type
           FROM experiment ORDER BY experiment_id"""
    ).fetchall()
    canonical: dict[tuple[object, ...], int] = {}
    observed_by_keep: dict[int, list[object]] = {}
    organs_by_keep: dict[int, list[object]] = {}
    removed = 0
    for row in rows:
        experiment_id = int(row[0])
        key = (
            row[1], row[2], _text(row[4] or row[3]), _species(row[5]),
            _model_identity(row[5], row[6]), _text(row[7]), row[8],
            _text(row[9]), _text(row[10]), row[11], _time_unit(row[12]),
            _text(row[14]),
        )
        keep = canonical.get(key)
        observed = row[16] or row[17]
        if keep is None:
            canonical[key] = experiment_id
            observed_by_keep[experiment_id] = [observed]
            organs_by_keep[experiment_id] = [row[15]]
            continue
        if "review_revision" in tables and connection.execute(
            """SELECT 1 FROM review_revision
               WHERE experiment_id=? OR (
                   entity_type IN ('arm','experiment') AND entity_id=?
               ) LIMIT 1""",
            (experiment_id, experiment_id),
        ).fetchone() is not None:
            continue
        observed_by_keep[keep].append(observed)
        organs_by_keep[keep].append(row[15])
        _merge_arm_dependencies(connection, tables, keep, experiment_id)
        connection.execute("DELETE FROM experiment WHERE experiment_id=?", (experiment_id,))
        removed += 1
    for keep, observed_values in observed_by_keep.items():
        if not connection.execute(
            "SELECT 1 FROM experiment WHERE experiment_id=?", (keep,)
        ).fetchone():
            continue
        observed = _combined(observed_values)
        organ = _combined(organs_by_keep[keep])
        connection.execute(
            """UPDATE experiment
               SET observed_transfected_cell=?,target_or_recipient_organ=?,
                   cell_type=CASE WHEN instr(coalesce(?,''),';')>0
                                  THEN 'other' ELSE cell_type END
               WHERE experiment_id=?""",
            (observed, organ, observed, keep),
        )
    return len(rows), removed


def deduplicate_science(connection: sqlite3.Connection) -> DeduplicationResult:
    """Merge exact scientific duplicates without deleting source occurrences."""

    tables = _tables(connection)
    arm_occurrences, removed_arms = _deduplicate_arms(connection, tables)
    component_rows = connection.execute(
        """
        SELECT component_id, formulation_id, component_name_reported,
               component_name_normalized, component_role, molar_percentage,
               percentage_unit, amount_value, amount_unit, amount_raw
        FROM chemical_component ORDER BY component_id
        """
    ).fetchall()
    component_occurrences = len(component_rows)
    components: dict[tuple[object, ...], int] = {}
    removed_components = 0
    for row in component_rows:
        component_id = int(row[0])
        key = (
            row[1], _text(row[3] or row[2]), _text(row[4]), row[5],
            _text(row[6]), row[7], _text(row[8]), _text(row[9]),
        )
        keep = components.get(key)
        if keep is None:
            components[key] = component_id
            continue
        if "record_source" in tables:
            connection.execute(
                "UPDATE record_source SET entity_id=? "
                "WHERE entity_type='chemical_component' AND entity_id=?",
                (keep, component_id),
            )
        if "import_record_identity" in tables:
            connection.execute(
                "UPDATE import_record_identity SET entity_id=? "
                "WHERE entity_type='chemical_component' AND entity_id=?",
                (keep, component_id),
            )
        if "import_field_evidence" in tables:
            connection.execute(
                "UPDATE import_field_evidence SET entity_id=? "
                "WHERE entity_type='component' AND entity_id=?",
                (keep, component_id),
            )
        connection.execute(
            "DELETE FROM chemical_component WHERE component_id=?", (component_id,)
        )
        removed_components += 1

    evidence_rows = connection.execute(
        """
        SELECT evidence_id, paper_id, experiment_id, outcome_id, evidence_text,
               evidence_location_type, section_name, page_number, table_number,
               figure_number, supplement_identifier
        FROM evidence ORDER BY evidence_id
        """
    ).fetchall()
    evidence_occurrences = len(evidence_rows)
    evidence: dict[tuple[object, ...], int] = {}
    removed_evidence = 0
    for row in evidence_rows:
        evidence_id = int(row[0])
        key = tuple(row[1:4]) + tuple(_text(value) for value in row[4:])
        keep = evidence.get(key)
        if keep is None:
            evidence[key] = evidence_id
            continue
        if "import_field_evidence" in tables:
            connection.execute(
                "UPDATE OR IGNORE import_field_evidence SET evidence_id=? "
                "WHERE evidence_id=?", (keep, evidence_id)
            )
            connection.execute(
                "DELETE FROM import_field_evidence WHERE evidence_id=?",
                (evidence_id,),
            )
        if "record_source" in tables:
            connection.execute(
                "UPDATE record_source SET entity_id=? "
                "WHERE entity_type='evidence' AND entity_id=?",
                (keep, evidence_id),
            )
        if "import_record_identity" in tables:
            connection.execute(
                "UPDATE import_record_identity SET entity_id=? "
                "WHERE entity_type='evidence' AND entity_id=?",
                (keep, evidence_id),
            )
        if "review_revision" in tables:
            connection.execute(
                "UPDATE review_revision SET evidence_id=? WHERE evidence_id=?",
                (keep, evidence_id),
            )
        if "field_verification" in tables:
            connection.execute(
                "UPDATE field_verification SET evidence_id=? WHERE evidence_id=?",
                (keep, evidence_id),
            )
        if "source_fact_evidence" in tables:
            connection.execute(
                "UPDATE source_fact_evidence SET evidence_id=? WHERE evidence_id=?",
                (keep, evidence_id),
            )
        connection.execute("DELETE FROM evidence WHERE evidence_id=?", (evidence_id,))
        removed_evidence += 1

    connection.commit()
    return DeduplicationResult(
        source_arm_count=arm_occurrences,
        canonical_arm_count=arm_occurrences - removed_arms,
        duplicate_arms_removed=removed_arms,
        source_occurrence_count=component_occurrences,
        canonical_component_count=component_occurrences - removed_components,
        duplicate_components_removed=removed_components,
        evidence_occurrence_count=evidence_occurrences,
        canonical_evidence_count=evidence_occurrences - removed_evidence,
        duplicate_evidence_removed=removed_evidence,
    )


__all__ = ["DeduplicationResult", "deduplicate_science"]
