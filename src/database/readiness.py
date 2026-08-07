"""Live, user-facing arm usability derived from canonical SQLite state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.database.status import (
    eligibility_reasons,
    evaluate_arm_status,
    evaluate_eligibility,
)


PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "config/database/readiness_profiles_v3.json"
)


@dataclass(frozen=True)
class ReadinessSummary:
    general_usable: bool
    nearest_neighbor_ready: bool
    comet_ready: bool
    nearest_neighbor_blockers: tuple[str, ...]
    comet_blockers: tuple[str, ...]
    queue_label: str
    rules_version: str


def _profiles() -> dict[str, object]:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _nonblank(value: object) -> bool:
    return value is not None and (
        not isinstance(value, str) or bool(value.strip())
    )


def _active_correction(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    field_name: str,
) -> tuple[str, str] | None:
    row = connection.execute(
        """
        SELECT corrected_value, coalesce(review_action, 'accepted')
        FROM review_revision AS current
        WHERE current.entity_type = ?
          AND coalesce(current.entity_id, current.experiment_id) = ?
          AND current.field_name = ?
          AND current.decision = 'accepted'
          AND NOT EXISTS (
              SELECT 1 FROM review_revision AS later
              WHERE later.supersedes_review_revision_id =
                    current.review_revision_id
          )
        ORDER BY current.review_revision_id DESC
        LIMIT 1
        """,
        (entity_type, entity_id, field_name),
    ).fetchone()
    return None if row is None else (str(row[0]), str(row[1]))


def _field_available(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: int,
    row: sqlite3.Row,
    field_name: str,
) -> bool:
    if field_name == "components":
        return connection.execute(
            "SELECT 1 FROM chemical_component WHERE formulation_id=? LIMIT 1",
            (entity_id,),
        ).fetchone() is not None
    correction = _active_correction(
        connection, entity_type, entity_id, field_name
    )
    if correction is not None:
        corrected_value, action = correction
        if action == "not_applicable":
            return True
        if _nonblank(corrected_value):
            return True
    return field_name in row.keys() and _nonblank(row[field_name])


def _has_evidence(connection: sqlite3.Connection, experiment_id: int) -> bool:
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='import_field_evidence'"
    ).fetchone() is None:
        return connection.execute(
            "SELECT 1 FROM evidence WHERE experiment_id=? "
            "AND length(trim(coalesce(evidence_text,'')))>0 "
            "AND evidence_review_status NOT IN ('rejected','conflict','ambiguous') LIMIT 1",
            (experiment_id,),
        ).fetchone() is not None
    return connection.execute(
        """
        SELECT 1
        FROM evidence
        WHERE length(trim(coalesce(evidence_text, ''))) > 0
          AND evidence_review_status NOT IN ('rejected', 'conflict', 'ambiguous')
          AND (
            experiment_id = ?
            OR evidence_id IN (
              SELECT link.evidence_id
              FROM import_field_evidence AS link
              WHERE (link.entity_type='arm' AND link.entity_id=?)
                 OR (link.entity_type='outcome' AND link.entity_id IN (
                      SELECT outcome_id FROM outcome WHERE experiment_id=?
                 ))
            )
          )
        LIMIT 1
        """,
        (experiment_id, experiment_id, experiment_id),
    ).fetchone() is not None


def _configured_comet_blockers(
    connection: sqlite3.Connection, experiment_id: int
) -> set[str]:
    previous = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        arm = connection.execute(
            "SELECT * FROM experiment WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
        if arm is None:
            raise KeyError(f"Unknown experiment_id: {experiment_id}")
        formulation_id = int(arm["formulation_id"])
        formulation = connection.execute(
            "SELECT * FROM formulation WHERE formulation_id=?",
            (formulation_id,),
        ).fetchone()
    finally:
        connection.row_factory = previous
    if formulation is None:
        return {"formulation_identity", "formulation_composition", "lnp_molar_ratio"}
    comet = _profiles()["comet"]
    blockers = {
        field_name
        for field_name in comet["arm_required"]
        if not _field_available(
            connection,
            entity_type="arm",
            entity_id=experiment_id,
            row=arm,
            field_name=field_name,
        )
    }
    blockers.update(
        field_name
        for field_name in comet["formulation_required"]
        if not _field_available(
            connection,
            entity_type="formulation",
            entity_id=formulation_id,
            row=formulation,
            field_name=field_name,
        )
    )
    for group in comet["arm_one_of"]:
        if not any(
            _field_available(
                connection,
                entity_type="arm",
                entity_id=experiment_id,
                row=arm,
                field_name=field_name,
            )
            for field_name in group["fields"]
        ):
            blockers.add(str(group["reason"]))
    for group in comet["formulation_one_of"]:
        if not any(
            _field_available(
                connection,
                entity_type="formulation",
                entity_id=formulation_id,
                row=formulation,
                field_name=field_name,
            )
            for field_name in group["fields"]
        ):
            blockers.add(str(group["reason"]))
    return blockers


def evaluate_readiness(
    connection: sqlite3.Connection, experiment_id: int
) -> ReadinessSummary:
    """Return independent general, nearest-neighbor, and COMET readiness."""

    status = evaluate_arm_status(connection, experiment_id)
    nearest = evaluate_eligibility(connection, experiment_id, "nearest_neighbor")
    comet_blockers = set(eligibility_reasons(connection, experiment_id, "comet"))
    comet_blockers.update(_configured_comet_blockers(connection, experiment_id))
    general_usable = (
        status.completeness_status == "complete"
        and _has_evidence(connection, experiment_id)
    )
    if status.completeness_status == "conflict":
        queue_label = "conflict"
    elif status.completeness_status == "quarantined":
        queue_label = "quarantined"
    elif not comet_blockers:
        queue_label = "comet_ready"
    elif (
        status.completeness_status == "incomplete"
        and _has_evidence(connection, experiment_id)
        and len(comet_blockers)
        <= int(_profiles()["comet"]["max_blockers_for_almost_ready"])
    ):
        queue_label = "almost_comet_ready"
    else:
        queue_label = "comet_gap"
    result = ReadinessSummary(
        general_usable=general_usable,
        nearest_neighbor_ready=nearest.eligible,
        comet_ready=not comet_blockers,
        nearest_neighbor_blockers=nearest.reasons,
        comet_blockers=tuple(sorted(comet_blockers)),
        queue_label=queue_label,
        rules_version=str(_profiles()["version"]),
    )
    connection.execute(
        """
        INSERT INTO eligibility_result (
            experiment_id,profile,eligible,reasons_json,rules_version,evaluated_at
        ) VALUES (?,'comet',?,?,?,?)
        ON CONFLICT(experiment_id,profile) DO UPDATE SET
            eligible=excluded.eligible,
            reasons_json=excluded.reasons_json,
            rules_version=excluded.rules_version,
            evaluated_at=excluded.evaluated_at
        WHERE eligibility_result.eligible IS NOT excluded.eligible
           OR eligibility_result.reasons_json IS NOT excluded.reasons_json
           OR eligibility_result.rules_version IS NOT excluded.rules_version
        """,
        (
            experiment_id,
            int(result.comet_ready),
            json.dumps(result.comet_blockers),
            result.rules_version,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    connection.execute(
        "UPDATE arm_assessment SET comet_eligible=? WHERE experiment_id=?",
        (int(result.comet_ready), experiment_id),
    )
    return result


__all__ = ["ReadinessSummary", "evaluate_readiness"]
