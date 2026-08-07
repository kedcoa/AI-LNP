"""Deterministic arm-status and downstream eligibility evaluation."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from src.database.target_scope import has_supported_delivery_destination


CompletenessStatus = Literal["complete", "incomplete", "conflict", "quarantined"]
EligibilityProfile = Literal["nearest_neighbor", "comet"]

RULES_VERSION = "working-evidence-v3"

BASE_REQUIRED_FIELDS = (
    "species",
    "payload_name",
    "dose",
    "route",
    "timepoint",
)
PROFILE_REQUIRED_FIELDS = {
    "nearest_neighbor": (
        "formulation_id",
        "payload_type",
        "species",
        "in_vitro_in_vivo",
    ),
    "comet": (
        "formulation_id",
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
    return _accepted_entity_correction(
        connection, "arm", experiment_id, field_name
    )


def _accepted_entity_correction(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    field_name: str,
) -> str | None:
    row = connection.execute(
        """
        SELECT current.corrected_value
        FROM review_revision AS current
        WHERE (current.entity_type = ? OR (? = 'arm' AND current.entity_type = 'experiment'))
          AND coalesce(current.entity_id, current.experiment_id) = ?
          AND current.field_name = ?
          AND current.decision = 'accepted'
          AND length(trim(current.evidence_excerpt)) > 0
          AND length(trim(current.evidence_location)) > 0
          AND NOT EXISTS (
              SELECT 1
              FROM review_revision AS later
              WHERE later.supersedes_review_revision_id = current.review_revision_id
          )
        ORDER BY current.review_revision_id DESC
        LIMIT 1
        """,
        (entity_type, entity_type, entity_id, field_name),
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


def _latest_entity_action(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    field_name: str,
) -> str | None:
    row = connection.execute(
        """SELECT review_action FROM review_revision
           WHERE entity_type = ? AND entity_id = ? AND field_name = ?
           ORDER BY review_revision_id DESC LIMIT 1""",
        (entity_type, entity_id, field_name),
    ).fetchone()
    return row[0] if row is not None else None


def _has_canonical_outcome_evidence(
    connection: sqlite3.Connection, outcome_id: int, status: str
) -> bool:
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'import_field_evidence'"
    ).fetchone() is None:
        return False
    return connection.execute(
        """SELECT 1 FROM import_field_evidence AS link
           JOIN evidence
             ON evidence.evidence_id = link.evidence_id
           WHERE link.entity_type = 'outcome' AND link.entity_id = ?
             AND link.verification_status = ?
             AND NOT EXISTS (
                 SELECT 1 FROM import_field_evidence AS later
                 WHERE later.paper_id = link.paper_id
                   AND later.entity_type = link.entity_type
                   AND later.entity_id = link.entity_id
                   AND later.field_name = link.field_name
                   AND later.evidence_id = link.evidence_id
                   AND later.import_field_evidence_id > link.import_field_evidence_id
             )
             AND (
                 (
                     ? = 'automatically_validated'
                     AND evidence.evidence_review_status NOT IN (
                         'rejected','conflict','ambiguous'
                     )
                 )
                 OR
                 evidence.evidence_review_status = 'manually_verified'
                 OR (
                     json_extract(
                         link.content_json, '$.review_revision_id'
                     ) IS NOT NULL
                     AND EXISTS (
                         SELECT 1 FROM review_revision AS revision
                         WHERE revision.review_revision_id = json_extract(
                                   link.content_json, '$.review_revision_id'
                               )
                           AND revision.decision = 'accepted'
                           AND NOT EXISTS (
                               SELECT 1
                               FROM review_revision AS later_revision
                               WHERE later_revision.supersedes_review_revision_id =
                                     revision.review_revision_id
                           )
                     )
                 )
             )
           LIMIT 1""",
        (outcome_id, status, status),
    ).fetchone() is not None


def _has_value(
    connection: sqlite3.Connection,
    experiment: sqlite3.Row,
    field_name: str,
) -> bool:
    value = experiment[field_name]
    if value is not None:
        if not isinstance(value, str):
            return True
        normalized = value.strip().casefold().replace(" ", "_")
        if normalized and normalized not in {
            "na", "n/a", "none", "not_reported", "unknown"
        }:
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
            SELECT missing.field_name
            FROM missing_field AS missing
            WHERE missing.experiment_id = ?
              AND (
                  missing.resolved_by_review_revision_id IS NULL
                  OR NOT EXISTS (
                      SELECT 1
                      FROM review_revision AS active
                      WHERE (
                            (active.entity_type IN ('arm', 'experiment')
                             AND coalesce(active.entity_id, active.experiment_id) = missing.experiment_id
                             AND active.field_name = missing.field_name)
                            OR (active.entity_type = 'formulation' AND active.entity_id = (
                                SELECT formulation_id FROM experiment
                                WHERE experiment_id = missing.experiment_id
                            ) AND active.field_name = missing.field_name)
                            OR (active.entity_type = 'outcome'
                                AND active.experiment_id = missing.experiment_id
                                AND missing.field_name = 'outcome:' || active.entity_id || ':' || active.field_name)
                        )
                        AND active.decision = 'accepted'
                        AND NOT EXISTS (
                            SELECT 1
                            FROM review_revision AS later
                            WHERE later.supersedes_review_revision_id = active.review_revision_id
                        )
                  )
              )
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


def _usable_outcomes(
    connection: sqlite3.Connection,
    experiment_id: int,
) -> list[dict[str, object]]:
    previous_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        outcomes = connection.execute(
            """
            SELECT outcome.*,
                   EXISTS (
                       SELECT 1
                       FROM evidence
                       WHERE evidence.experiment_id = outcome.experiment_id
                         AND evidence.outcome_id = outcome.outcome_id
                         AND evidence.evidence_review_status IN (
                             'automatically_validated', 'manually_verified'
                         )
                   ) AS has_accepted_evidence,
                   EXISTS (
                       SELECT 1
                       FROM evidence
                       WHERE evidence.experiment_id = outcome.experiment_id
                         AND evidence.outcome_id = outcome.outcome_id
                         AND evidence.evidence_review_status = 'manually_verified'
                   ) AS has_manually_verified_evidence
            FROM outcome
            WHERE outcome.experiment_id = ?
            ORDER BY outcome.outcome_id
            """,
            (experiment_id,),
        ).fetchall()
    finally:
        connection.row_factory = previous_factory

    usable: list[dict[str, object]] = []
    for source_outcome in outcomes:
        outcome = dict(source_outcome)
        outcome_id = int(outcome["outcome_id"])
        if _has_canonical_outcome_evidence(
            connection, outcome_id, "automatically_validated"
        ) or _has_canonical_outcome_evidence(
            connection, outcome_id, "manually_verified"
        ):
            outcome["has_accepted_evidence"] = 1
        if _has_canonical_outcome_evidence(
            connection, outcome_id, "manually_verified"
        ):
            outcome["has_manually_verified_evidence"] = 1
        for field_name in (
            "endpoint_family", "endpoint_name", "outcome_value", "outcome_unit",
            "normalization_basis", "uncertainty_value", "uncertainty_type",
            "qualitative_outcome", "value_status",
        ):
            correction = _accepted_entity_correction(
                connection, "outcome", outcome_id, field_name
            )
            if correction is not None:
                outcome[field_name] = correction
        if any(
            _latest_entity_action(connection, "outcome", outcome_id, field_name)
            in {"not_reported", "wrong_arm"}
            for field_name in ("outcome_value", "qualitative_outcome", "value_status")
        ):
            continue
        value = outcome["outcome_value"]
        numeric_result = False
        if outcome["value_status"] in {"reported", "normalized"}:
            try:
                numeric_result = value is not None and math.isfinite(float(value))
            except (TypeError, ValueError):
                numeric_result = False
        qualitative_result = (
            outcome["value_status"] == "qualitative_only"
            and bool((outcome["qualitative_outcome"] or "").strip())
        )
        if numeric_result or qualitative_result:
            usable.append(outcome)
    return usable


def _evidence_statuses(
    connection: sqlite3.Connection,
    experiment_id: int,
) -> tuple[str, ...]:
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='import_field_evidence'"
    ).fetchone() is None:
        return tuple(
            row[0] for row in connection.execute(
                "SELECT evidence_review_status FROM evidence "
                "WHERE experiment_id=? ORDER BY evidence_id", (experiment_id,)
            )
        )
    return tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT evidence_review_status AS status, evidence_id AS ordering
            FROM evidence
            WHERE experiment_id = ?
            UNION ALL
            SELECT CASE
                     WHEN link.verification_status IN (
                       'automatically_validated','manually_verified'
                     ) THEN link.verification_status
                     ELSE evidence.evidence_review_status
                   END AS status,
                   evidence.evidence_id AS ordering
            FROM import_field_evidence AS link
            JOIN evidence USING(evidence_id)
            WHERE (link.entity_type='arm' AND link.entity_id=?)
               OR (link.entity_type='outcome' AND link.entity_id IN (
                    SELECT outcome_id FROM outcome WHERE experiment_id=?
               ))
            ORDER BY ordering
            """,
            (experiment_id, experiment_id, experiment_id),
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
            SELECT current.verification_status
            FROM field_verification AS current
            WHERE current.experiment_id = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM field_verification AS later
                  WHERE later.experiment_id = current.experiment_id
                    AND later.field_name = current.field_name
                    AND later.field_verification_id > current.field_verification_id
              )
            ORDER BY current.field_verification_id
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
    missing = _unresolved_missing_fields(connection, experiment_id)
    if has_supported_delivery_destination(connection, experiment_id):
        missing.discard("cell_type")
        missing.discard("delivery_destination")
    else:
        missing.add("delivery_destination")
    missing.update(
        field_name
        for field_name in BASE_REQUIRED_FIELDS
        if not _has_value(connection, experiment, field_name)
    )
    formulation = connection.execute(
        """
        SELECT chemical_formulation_total,lnp_molar_ratio
        FROM formulation WHERE formulation_id=?
        """,
        (experiment["formulation_id"],),
    ).fetchone()
    for field_name, index in (
        ("chemical_formulation_total", 0),
        ("lnp_molar_ratio", 1),
    ):
        corrected = _accepted_entity_correction(
            connection, "formulation", experiment["formulation_id"], field_name
        )
        stored_value = formulation[index] if formulation is not None else None
        if not str(corrected or stored_value or "").strip():
            missing.add(field_name)
    outcomes = _linked_outcomes(connection, experiment_id)
    if not outcomes or not _usable_outcomes(connection, experiment_id):
        missing.add("outcome")

    evidence_statuses = _evidence_statuses(connection, experiment_id)
    if not evidence_statuses:
        missing.add("evidence")
    statuses = evidence_statuses + _field_statuses(connection, experiment_id)
    verification = _verification_status(statuses)

    if quarantine_reason:
        status: CompletenessStatus = "quarantined"
        verification = "rejected"
    elif "conflict" in statuses:
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
        WHERE arm_assessment.completeness_status IS NOT excluded.completeness_status
           OR arm_assessment.missing_fields_json IS NOT excluded.missing_fields_json
           OR arm_assessment.verification_status IS NOT excluded.verification_status
           OR arm_assessment.quarantine_reason IS NOT excluded.quarantine_reason
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
    if has_supported_delivery_destination(connection, experiment_id):
        reasons.discard("cell_type")
        reasons.discard("delivery_destination")
    else:
        reasons.add("delivery_destination")
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
    formulation_name = (
        _accepted_entity_correction(
            connection, "formulation", experiment["formulation_id"], "formulation_name"
        )
        or (formulation[0] if formulation is not None else None)
    )
    composition_raw = (
        _accepted_entity_correction(
            connection, "formulation", experiment["formulation_id"], "composition_raw"
        )
        or (formulation[1] if formulation is not None else None)
    )
    if not (formulation_name or "").strip():
        reasons.add("formulation_identity")
    component_count = connection.execute(
        "SELECT COUNT(*) FROM chemical_component WHERE formulation_id = ?",
        (experiment["formulation_id"],),
    ).fetchone()[0]
    if not (composition_raw or "").strip() and component_count == 0:
        reasons.add("formulation_composition")

    outcomes = _linked_outcomes(connection, experiment_id)
    usable_outcomes = _usable_outcomes(connection, experiment_id)
    accepted_outcomes = [
        outcome for outcome in usable_outcomes if outcome["has_accepted_evidence"]
    ]
    if not outcomes:
        reasons.add("outcome")
    elif not usable_outcomes:
        reasons.add("usable_outcome")
    if not accepted_outcomes:
        reasons.add("accepted_evidence")
    if profile == "comet" and accepted_outcomes:
        if not any(
            (row["outcome_unit"] or "").strip() for row in accepted_outcomes
        ):
            reasons.add("outcome_unit")
        if not any(
            (row["normalization_basis"] or "").strip()
            for row in accepted_outcomes
        ):
            reasons.add("normalization_basis")
        coherent_outcomes = [
            row
            for row in accepted_outcomes
            if (row["outcome_unit"] or "").strip()
            and (row["normalization_basis"] or "").strip()
        ]
        if not coherent_outcomes:
            reasons.add("coherent_outcome")
        elif not any(
            row["has_manually_verified_evidence"] for row in coherent_outcomes
        ):
            reasons.add("manually_verified_evidence")

    if not _evidence_statuses(connection, experiment_id):
        reasons.add("evidence")
    return reasons


def evaluate_eligibility(
    connection: sqlite3.Connection,
    experiment_id: int,
    profile: EligibilityProfile,
) -> EligibilityResult:
    """Evaluate and store deterministic nearest-neighbor or COMET eligibility."""

    reasons = set(eligibility_reasons(connection, experiment_id, profile))

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
        WHERE eligibility_result.eligible IS NOT excluded.eligible
           OR eligibility_result.reasons_json IS NOT excluded.reasons_json
           OR eligibility_result.rules_version IS NOT excluded.rules_version
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
        f"UPDATE arm_assessment SET {column} = ? "
        f"WHERE experiment_id = ? AND {column} IS NOT ?",
        (int(result.eligible), experiment_id, int(result.eligible)),
    )
    return result


def eligibility_reasons(
    connection: sqlite3.Connection,
    experiment_id: int,
    profile: EligibilityProfile,
) -> tuple[str, ...]:
    """Calculate profile blockers without updating cached eligibility rows."""

    if profile not in PROFILE_REQUIRED_FIELDS:
        raise ValueError(f"Unknown eligibility profile: {profile}")
    experiment = _row(connection, experiment_id)
    status = evaluate_arm_status(connection, experiment_id)
    reasons = _profile_reasons(connection, experiment, profile)
    if status.completeness_status == "incomplete":
        reasons.update(status.missing_fields)
    if status.completeness_status in {"conflict", "quarantined"}:
        reasons.add(status.completeness_status)
    if profile == "comet" and status.verification_status != "manually_verified":
        reasons.add("manually_verified")
    return tuple(sorted(reasons))
