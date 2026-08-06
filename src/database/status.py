"""Deterministic arm-status and downstream eligibility evaluation."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


CompletenessStatus = Literal["complete", "incomplete", "conflict", "quarantined"]
EligibilityProfile = Literal["nearest_neighbor", "comet"]

RULES_VERSION = "working-evidence-v1"

BASE_REQUIRED_FIELDS = ("formulation_id", "cell_type", "payload_type")
PROFILE_REQUIRED_FIELDS = {
    "nearest_neighbor": (
        "formulation_id",
        "cell_type",
        "payload_type",
        "species",
        "in_vitro_in_vivo",
    ),
    "comet": (
        "formulation_id",
        "cell_type",
        "payload_type",
        "species",
        "in_vitro_in_vivo",
        "dose",
        "dose_unit",
        "assay",
    ),
}


@dataclass(frozen=True)
class ArmStatusResult:
    completeness_status: CompletenessStatus
    missing_fields: tuple[str, ...]
    verification_status: str
    quarantine_reason: str | None = None

    @property
    def status(self) -> CompletenessStatus:
        return self.completeness_status


@dataclass(frozen=True)
class EligibilityResult:
    profile: EligibilityProfile
    eligible: bool
    reasons: tuple[str, ...]
    rules_version: str = RULES_VERSION


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(connection: sqlite3.Connection, experiment_id: int) -> sqlite3.Row:
    previous_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        result = connection.execute(
            "SELECT * FROM experiment WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
    finally:
        connection.row_factory = previous_factory
    if result is None:
        raise KeyError(f"Unknown experiment_id: {experiment_id}")
    return result


def _accepted_correction(
    connection: sqlite3.Connection,
    experiment_id: int,
    field_name: str,
) -> str | None:
    row = connection.execute(
        """
        SELECT corrected_value
        FROM review_revision
        WHERE experiment_id = ?
          AND field_name = ?
          AND decision = 'accepted'
          AND length(trim(evidence_excerpt)) > 0
          AND length(trim(evidence_location)) > 0
        ORDER BY review_revision_id DESC
        LIMIT 1
        """,
        (experiment_id, field_name),
    ).fetchone()
    if row is None:
        return None
    value = row[0]
    if field_name in {"dose", "timepoint"}:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric_value) or numeric_value < 0:
            return None
    return value


def _has_value(
    connection: sqlite3.Connection,
    experiment: sqlite3.Row,
    field_name: str,
) -> bool:
    value = experiment[field_name]
    if value is not None and (not isinstance(value, str) or value.strip()):
        return True
    return _accepted_correction(
        connection, experiment["experiment_id"], field_name
    ) is not None


def _unresolved_missing_fields(
    connection: sqlite3.Connection,
    experiment_id: int,
) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            """
            SELECT field_name
            FROM missing_field
            WHERE experiment_id = ?
              AND resolved_by_review_revision_id IS NULL
            """,
            (experiment_id,),
        )
    }


def _linked_outcomes(
    connection: sqlite3.Connection,
    experiment_id: int,
) -> list[sqlite3.Row]:
    previous_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            "SELECT * FROM outcome WHERE experiment_id = ? ORDER BY outcome_id",
            (experiment_id,),
        ).fetchall()
    finally:
        connection.row_factory = previous_factory


def _evidence_statuses(
    connection: sqlite3.Connection,
    experiment_id: int,
) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT evidence_review_status
            FROM evidence
            WHERE experiment_id = ?
            ORDER BY evidence_id
            """,
            (experiment_id,),
        )
    )


def _field_statuses(
    connection: sqlite3.Connection,
    experiment_id: int,
) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT verification_status
            FROM field_verification
            WHERE experiment_id = ?
            ORDER BY field_verification_id
            """,
            (experiment_id,),
        )
    )


def _verification_status(statuses: tuple[str, ...]) -> str:
    if "conflict" in statuses:
        return "conflict"
    if "rejected" in statuses:
        return "rejected"
    if "ambiguous" in statuses:
        return "ambiguous"
    if statuses and all(status == "manually_verified" for status in statuses):
        return "manually_verified"
    if "manually_verified" in statuses:
        return "manually_verified"
    if "automatically_validated" in statuses:
        return "automatically_validated"
    return "unreviewed"


def evaluate_arm_status(
    connection: sqlite3.Connection,
    experiment_id: int,
) -> ArmStatusResult:
    """Evaluate and persist the arm's fixed-schema status.

    Explicit quarantine state has the highest precedence, then supported
    conflicts, then unresolved or structurally missing fields.
    """

    experiment = _row(connection, experiment_id)
    stored = connection.execute(
        """
        SELECT completeness_status, verification_status, quarantine_reason
        FROM arm_assessment
        WHERE experiment_id = ?
        """,
        (experiment_id,),
    ).fetchone()
    quarantine_reason = (
        stored[2]
        if stored is not None and stored[0] == "quarantined"
        else None
    )
    stored_conflict = (
        stored is not None
        and (stored[0] == "conflict" or stored[1] == "conflict")
    )

    missing = _unresolved_missing_fields(connection, experiment_id)
    missing.update(
        field_name
        for field_name in BASE_REQUIRED_FIELDS
        if not _has_value(connection, experiment, field_name)
    )
    outcomes = _linked_outcomes(connection, experiment_id)
    if not outcomes:
        missing.add("outcome")

    evidence_statuses = _evidence_statuses(connection, experiment_id)
    if not evidence_statuses:
        missing.add("evidence")
    statuses = evidence_statuses + _field_statuses(connection, experiment_id)
    verification = _verification_status(statuses)

    if quarantine_reason:
        status: CompletenessStatus = "quarantined"
        verification = "rejected"
    elif stored_conflict or "conflict" in statuses:
        status = "conflict"
        verification = "conflict"
    elif missing:
        status = "incomplete"
    else:
        status = "complete"

    result = ArmStatusResult(
        completeness_status=status,
        missing_fields=tuple(sorted(missing)),
        verification_status=verification,
        quarantine_reason=quarantine_reason,
    )
    connection.execute(
        """
        INSERT INTO arm_assessment (
            experiment_id, completeness_status, missing_fields_json,
            verification_status, quarantine_reason, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(experiment_id) DO UPDATE SET
            completeness_status = excluded.completeness_status,
            missing_fields_json = excluded.missing_fields_json,
            verification_status = excluded.verification_status,
            quarantine_reason = excluded.quarantine_reason,
            updated_at = excluded.updated_at
        """,
        (
            experiment_id,
            result.completeness_status,
            json.dumps(result.missing_fields),
            result.verification_status,
            result.quarantine_reason,
            _utc_now(),
        ),
    )
    return result


def _profile_reasons(
    connection: sqlite3.Connection,
    experiment: sqlite3.Row,
    profile: EligibilityProfile,
) -> set[str]:
    experiment_id = experiment["experiment_id"]
    reasons = _unresolved_missing_fields(connection, experiment_id)
    reasons.update(
        field_name
        for field_name in PROFILE_REQUIRED_FIELDS[profile]
        if not _has_value(connection, experiment, field_name)
    )

    formulation = connection.execute(
        """
        SELECT formulation_name, composition_raw
        FROM formulation
        WHERE formulation_id = ?
        """,
        (experiment["formulation_id"],),
    ).fetchone()
    if formulation is None or not (formulation[0] or "").strip():
        reasons.add("formulation_identity")
    component_count = connection.execute(
        "SELECT COUNT(*) FROM chemical_component WHERE formulation_id = ?",
        (experiment["formulation_id"],),
    ).fetchone()[0]
    if formulation is None or (
        not (formulation[1] or "").strip() and component_count == 0
    ):
        reasons.add("formulation_composition")

    outcomes = _linked_outcomes(connection, experiment_id)
    if not outcomes:
        reasons.add("outcome")
    elif profile == "comet":
        if not any((row["outcome_unit"] or "").strip() for row in outcomes):
            reasons.add("outcome_unit")
        if not any((row["normalization_basis"] or "").strip() for row in outcomes):
            reasons.add("normalization_basis")

    evidence_statuses = _evidence_statuses(connection, experiment_id)
    if not evidence_statuses:
        reasons.add("evidence")
    elif any(
        status not in {"automatically_validated", "manually_verified"}
        for status in evidence_statuses
    ):
        reasons.add("accepted_evidence")
    elif profile == "comet" and not all(
        status == "manually_verified" for status in evidence_statuses
    ):
        reasons.add("manually_verified_evidence")
    return reasons


def evaluate_eligibility(
    connection: sqlite3.Connection,
    experiment_id: int,
    profile: EligibilityProfile,
) -> EligibilityResult:
    """Evaluate and store deterministic nearest-neighbor or COMET eligibility."""

    if profile not in PROFILE_REQUIRED_FIELDS:
        raise ValueError(f"Unknown eligibility profile: {profile}")
    experiment = _row(connection, experiment_id)
    status = evaluate_arm_status(connection, experiment_id)
    reasons = _profile_reasons(connection, experiment, profile)
    if status.completeness_status in {"conflict", "quarantined"}:
        reasons.add(status.completeness_status)
    if profile == "comet" and status.verification_status != "manually_verified":
        reasons.add("manually_verified")

    result = EligibilityResult(
        profile=profile,
        eligible=not reasons,
        reasons=tuple(sorted(reasons)),
    )
    connection.execute(
        """
        INSERT INTO eligibility_result (
            experiment_id, profile, eligible, reasons_json,
            rules_version, evaluated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(experiment_id, profile) DO UPDATE SET
            eligible = excluded.eligible,
            reasons_json = excluded.reasons_json,
            rules_version = excluded.rules_version,
            evaluated_at = excluded.evaluated_at
        """,
        (
            experiment_id,
            profile,
            int(result.eligible),
            json.dumps(result.reasons),
            result.rules_version,
            _utc_now(),
        ),
    )
    column = (
        "nearest_neighbor_eligible"
        if profile == "nearest_neighbor"
        else "comet_eligible"
    )
    connection.execute(
        f"UPDATE arm_assessment SET {column} = ? WHERE experiment_id = ?",
        (int(result.eligible), experiment_id),
    )
    return result
