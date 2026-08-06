from __future__ import annotations

import sqlite3

import pytest

from src.database.status import evaluate_arm_status, evaluate_eligibility
from src.init_db import initialize_database


@pytest.fixture
def arm_database(tmp_path):
    path = tmp_path / "status.db"
    initialize_database(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    paper_id = connection.execute(
        """
        INSERT INTO paper (
            source_paper_id, title, source_type, retrieval_date,
            screening_status, import_status
        ) VALUES ('TEST-001', 'Status fixture', 'fixture', '2026-08-06', 'include', 'ready')
        """
    ).lastrowid
    formulation_id = connection.execute(
        """
        INSERT INTO formulation (
            paper_id, formulation_name, composition_raw, composition_basis
        ) VALUES (?, 'LNP-A', 'A:B:C:D = 50:10:38.5:1.5', 'mol%')
        """,
        (paper_id,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO chemical_component (
            formulation_id, component_name_reported, component_role,
            molar_percentage, percentage_unit
        ) VALUES (?, 'A', 'ionizable_lipid', 50.0, 'mol%')
        """,
        (formulation_id,),
    )
    experiment_id = connection.execute(
        """
        INSERT INTO experiment (
            paper_id, formulation_id, cell_type, species, in_vitro_in_vivo,
            payload_type, dose, dose_unit, assay
        ) VALUES (?, ?, 'hepatocyte', 'mouse', 'in_vivo', 'mRNA', 1.0, 'mg/kg', 'ELISA')
        """,
        (paper_id, formulation_id),
    ).lastrowid
    outcome_id = connection.execute(
        """
        INSERT INTO outcome (
            experiment_id, endpoint_family, endpoint_name, outcome_value,
            outcome_unit, normalization_basis, value_status
        ) VALUES (?, 'functional_expression', 'protein expression', 12.0, 'ng/mL', 'total protein', 'reported')
        """,
        (experiment_id,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO evidence (
            paper_id, experiment_id, outcome_id, field_name, evidence_text,
            evidence_location_type, extraction_method, extraction_confidence,
            evidence_review_status
        ) VALUES (?, ?, ?, 'outcome_value', 'Expression was 12 ng/mL.',
                  'results', 'manual', 'high', 'manually_verified')
        """,
        (paper_id, experiment_id, outcome_id),
    )
    connection.commit()
    try:
        yield connection, experiment_id
    finally:
        connection.close()


def test_complete_arm_has_supported_required_relationships(arm_database) -> None:
    connection, experiment_id = arm_database

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "complete"
    assert result.missing_fields == ()
    assert result.verification_status == "manually_verified"


def test_missing_field_makes_arm_incomplete(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """
        INSERT INTO missing_field (experiment_id, field_name, reason, recorded_at)
        VALUES (?, 'payload_type', 'source does not state payload', '2026-08-06T10:00:00Z')
        """,
        (experiment_id,),
    )

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "incomplete"
    assert result.missing_fields == ("payload_type",)


def test_conflict_takes_precedence_over_incomplete(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """
        INSERT INTO missing_field (experiment_id, field_name, reason, recorded_at)
        VALUES (?, 'dose', 'not reported', '2026-08-06T10:00:00Z')
        """,
        (experiment_id,),
    )
    connection.execute(
        """
        INSERT INTO field_verification (
            experiment_id, field_name, verification_status, notes, verified_at
        ) VALUES (?, 'species', 'conflict', 'mouse and rat both supported', '2026-08-06T10:01:00Z')
        """,
        (experiment_id,),
    )

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "conflict"
    assert result.verification_status == "conflict"


def test_persisted_relation_conflict_is_not_silently_cleared(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """
        INSERT INTO arm_assessment (
            experiment_id, completeness_status, missing_fields_json,
            verification_status, updated_at
        ) VALUES (?, 'conflict', '[]', 'conflict', '2026-08-06T10:00:00Z')
        """,
        (experiment_id,),
    )

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "conflict"
    assert result.verification_status == "conflict"


def test_explicit_quarantine_takes_highest_precedence(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """
        INSERT INTO arm_assessment (
            experiment_id, completeness_status, missing_fields_json,
            verification_status, quarantine_reason, updated_at
        ) VALUES (?, 'quarantined', '[]', 'rejected',
                  'formulation-arm relation is unsafe', '2026-08-06T10:00:00Z')
        """,
        (experiment_id,),
    )

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "quarantined"
    assert result.quarantine_reason == "formulation-arm relation is unsafe"


def test_nearest_neighbor_and_comet_have_distinct_evidence_gates(
    arm_database,
) -> None:
    connection, experiment_id = arm_database

    nearest = evaluate_eligibility(connection, experiment_id, "nearest_neighbor")
    comet = evaluate_eligibility(connection, experiment_id, "comet")

    assert nearest.eligible is True
    assert nearest.reasons == ()
    assert comet.eligible is True
    assert comet.reasons == ()


def test_ambiguous_evidence_is_not_similarity_eligible(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """
        UPDATE evidence
        SET evidence_review_status = 'ambiguous'
        WHERE experiment_id = ?
        """,
        (experiment_id,),
    )

    nearest = evaluate_eligibility(connection, experiment_id, "nearest_neighbor")

    assert nearest.eligible is False
    assert "accepted_evidence" in nearest.reasons


def test_evidence_backed_human_correction_changes_comet_eligibility(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        "UPDATE experiment SET dose = NULL WHERE experiment_id = ?",
        (experiment_id,),
    )
    connection.execute(
        """
        INSERT INTO missing_field (
            experiment_id, field_name, reason, recorded_at
        ) VALUES (?, 'dose', 'not extracted', '2026-08-06T10:00:00Z')
        """,
        (experiment_id,),
    )

    before = evaluate_eligibility(connection, experiment_id, "comet")
    assert before.eligible is False
    assert before.reasons == ("dose",)

    connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, previous_value, corrected_value,
            evidence_excerpt, evidence_location, reviewer, reviewed_at
        ) VALUES (?, 'dose', NULL, '0.75', 'Animals received 0.75 mg/kg.',
                  'methods, p. 3', 'human-reviewer', '2026-08-06T11:00:00Z')
        """,
        (experiment_id,),
    )
    connection.execute(
        """
        UPDATE missing_field
        SET resolved_by_review_revision_id = last_insert_rowid(),
            resolved_at = '2026-08-06T11:00:00Z'
        WHERE experiment_id = ? AND field_name = 'dose'
        """,
        (experiment_id,),
    )

    after = evaluate_eligibility(connection, experiment_id, "comet")

    assert after.eligible is True
    assert after.reasons == ()
    assert connection.execute(
        "SELECT eligible FROM eligibility_result WHERE experiment_id = ? AND profile = 'comet'",
        (experiment_id,),
    ).fetchone() == (1,)


def test_correction_without_evidence_cannot_be_recorded(arm_database) -> None:
    connection, experiment_id = arm_database

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO review_revision (
                experiment_id, field_name, corrected_value,
                evidence_excerpt, evidence_location, reviewer, reviewed_at
            ) VALUES (?, 'dose', '0.75', '', '', 'human-reviewer', '2026-08-06T11:00:00Z')
            """,
            (experiment_id,),
        )


def test_non_numeric_human_dose_does_not_change_comet_eligibility(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        "UPDATE experiment SET dose = NULL WHERE experiment_id = ?",
        (experiment_id,),
    )
    revision_id = connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, corrected_value,
            evidence_excerpt, evidence_location, reviewer, reviewed_at
        ) VALUES (?, 'dose', 'not-a-dose', 'Dose text was unclear.',
                  'methods, p. 3', 'human-reviewer', '2026-08-06T11:00:00Z')
        """,
        (experiment_id,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO missing_field (
            experiment_id, field_name, reason, recorded_at,
            resolved_by_review_revision_id, resolved_at
        ) VALUES (?, 'dose', 'not extracted', '2026-08-06T10:00:00Z', ?,
                  '2026-08-06T11:00:00Z')
        """,
        (experiment_id, revision_id),
    )

    result = evaluate_eligibility(connection, experiment_id, "comet")

    assert result.eligible is False
    assert "dose" in result.reasons


def test_unknown_experiment_and_profile_are_rejected(arm_database) -> None:
    connection, experiment_id = arm_database

    with pytest.raises(KeyError, match="Unknown experiment_id"):
        evaluate_arm_status(connection, 999999)
    with pytest.raises(ValueError, match="Unknown eligibility profile"):
        evaluate_eligibility(connection, experiment_id, "unsupported")
