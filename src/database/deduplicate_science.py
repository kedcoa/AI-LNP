"""Deterministic canonical-row deduplication with provenance reassignment."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DeduplicationResult:
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


def deduplicate_science(connection: sqlite3.Connection) -> DeduplicationResult:
    """Merge exact scientific duplicates without deleting source occurrences."""

    tables = _tables(connection)
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
        source_occurrence_count=component_occurrences,
        canonical_component_count=component_occurrences - removed_components,
        duplicate_components_removed=removed_components,
        evidence_occurrence_count=evidence_occurrences,
        canonical_evidence_count=evidence_occurrences - removed_evidence,
        duplicate_evidence_removed=removed_evidence,
    )


__all__ = ["DeduplicationResult", "deduplicate_science"]
