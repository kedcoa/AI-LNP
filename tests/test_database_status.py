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
            paper_id, formulation_name, composition_raw, composition_basis,
            chemical_formulation_total, lnp_molar_ratio
        ) VALUES (?, 'LNP-A', 'A:B:C:D = 50:10:38.5:1.5', 'mol%',
                  'A-B-C-D', '50:10:38.5:1.5')
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
            paper_id, formulation_id, cell_type, intended_target_cell,
            species, in_vitro_in_vivo,
            payload_type, payload_name, dose, dose_unit, route, timepoint,
            timepoint_unit, assay
        ) VALUES (?, ?, 'hepatocyte', 'hepatocyte', 'mouse', 'in_vivo', 'mRNA', 'test mRNA',
                  1.0, 'mg/kg', 'intravenous', 24, 'hours', 'ELISA')
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


def test_general_completeness_requires_every_approved_mandatory_field(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        "UPDATE experiment SET route=NULL,timepoint=NULL WHERE experiment_id=?",
        (experiment_id,),
    )
    connection.execute(
        "UPDATE formulation SET lnp_molar_ratio=NULL WHERE formulation_id=(SELECT formulation_id FROM experiment WHERE experiment_id=?)",
        (experiment_id,),
    )

    status = evaluate_arm_status(connection, experiment_id)
    nearest = evaluate_eligibility(connection, experiment_id, "nearest_neighbor")

    assert status.completeness_status == "incomplete"
    assert {"lnp_molar_ratio", "route", "timepoint"} <= set(status.missing_fields)
    assert nearest.eligible is False
    assert {"lnp_molar_ratio", "route", "timepoint"} <= set(nearest.reasons)


def test_organ_destination_satisfies_delivery_without_intended_target_cell(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """UPDATE experiment
           SET cell_type='not_reported', intended_target_cell=NULL,
               target_or_recipient_organ='liver',
               observed_transfected_cell='hepatocyte'
           WHERE experiment_id=?""",
        (experiment_id,),
    )

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "complete"
    assert "cell_type" not in result.missing_fields
    assert "delivery_destination" not in result.missing_fields


def test_observed_cell_alone_does_not_satisfy_delivery_destination(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """UPDATE experiment
           SET cell_type='not_reported', intended_target_cell=NULL,
               target_or_recipient_organ=NULL, tissue_or_organ=NULL,
               observed_transfected_cell='hepatocyte'
           WHERE experiment_id=?""",
        (experiment_id,),
    )

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "incomplete"
    assert "delivery_destination" in result.missing_fields


def test_missing_value_outcome_does_not_satisfy_general_completeness(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """UPDATE outcome
           SET outcome_value=NULL, qualitative_outcome=NULL, value_status='missing'
           WHERE experiment_id=?""",
        (experiment_id,),
    )

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "incomplete"
    assert "outcome" in result.missing_fields


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


def test_cached_conflict_without_current_relational_support_is_recomputed(
    arm_database,
) -> None:
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

    assert result.completeness_status == "complete"
    assert result.verification_status == "manually_verified"


def test_resolved_field_conflict_recomputes_to_complete(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """
        INSERT INTO field_verification (
            experiment_id, field_name, verification_status, notes, verified_at
        ) VALUES (?, 'species', 'conflict', 'mouse and rat both supported',
                  '2026-08-06T10:00:00Z')
        """,
        (experiment_id,),
    )
    assert evaluate_arm_status(
        connection, experiment_id
    ).completeness_status == "conflict"

    connection.execute(
        """
        INSERT INTO field_verification (
            experiment_id, field_name, verification_status, notes, verified_at
        ) VALUES (?, 'species', 'manually_verified', 'resolved to mouse',
                  '2026-08-06T11:00:00Z')
        """,
        (experiment_id,),
    )

    result = evaluate_arm_status(connection, experiment_id)

    assert result.completeness_status == "complete"
    assert result.verification_status == "manually_verified"


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


def test_eligibility_records_the_coherent_outcome_rules_version(
    arm_database,
) -> None:
    connection, experiment_id = arm_database

    result = evaluate_eligibility(
        connection, experiment_id, "nearest_neighbor"
    )

    assert result.rules_version == "working-evidence-v3"


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


def test_outcome_without_usable_value_is_not_eligible(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """
        UPDATE outcome
        SET outcome_value = NULL,
            qualitative_outcome = NULL,
            value_status = 'missing'
        WHERE experiment_id = ?
        """,
        (experiment_id,),
    )

    result = evaluate_eligibility(
        connection, experiment_id, "nearest_neighbor"
    )

    assert result.eligible is False
    assert "usable_outcome" in result.reasons


def test_experiment_evidence_must_link_to_the_usable_outcome(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        "UPDATE evidence SET outcome_id = NULL WHERE experiment_id = ?",
        (experiment_id,),
    )

    result = evaluate_eligibility(
        connection, experiment_id, "nearest_neighbor"
    )

    assert result.eligible is False
    assert "accepted_evidence" in result.reasons


def test_usable_value_and_accepted_evidence_cannot_be_split_across_outcomes(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    unsupported_outcome_id = connection.execute(
        "SELECT outcome_id FROM outcome WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchone()[0]
    valueless_outcome_id = connection.execute(
        """
        INSERT INTO outcome (
            experiment_id, endpoint_family, endpoint_name,
            value_status
        ) VALUES (?, 'uptake', 'secondary endpoint', 'missing')
        """,
        (experiment_id,),
    ).lastrowid
    connection.execute(
        "UPDATE evidence SET outcome_id = ? WHERE outcome_id = ?",
        (valueless_outcome_id, unsupported_outcome_id),
    )

    result = evaluate_eligibility(
        connection, experiment_id, "nearest_neighbor"
    )

    assert result.eligible is False
    assert "accepted_evidence" in result.reasons


def test_supported_qualitative_outcome_is_similarity_eligible(
    arm_database,
) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        """
        UPDATE outcome
        SET outcome_value = NULL,
            outcome_unit = NULL,
            normalization_basis = NULL,
            qualitative_outcome = 'Expression increased relative to control.',
            value_status = 'qualitative_only'
        WHERE experiment_id = ?
        """,
        (experiment_id,),
    )

    result = evaluate_eligibility(
        connection, experiment_id, "nearest_neighbor"
    )

    assert result.eligible is True
    assert result.reasons == ()


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


def test_accepted_correction_can_be_retracted_append_only(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        "UPDATE experiment SET dose = NULL WHERE experiment_id = ?",
        (experiment_id,),
    )
    accepted_id = connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, corrected_value, evidence_excerpt,
            evidence_location, reviewer, reviewed_at
        ) VALUES (?, 'dose', '0.75', 'Animals received 0.75 mg/kg.',
                  'methods, p. 3', 'reviewer-a', '2026-08-06T11:00:00Z')
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
        (experiment_id, accepted_id),
    )
    assert evaluate_eligibility(connection, experiment_id, "comet").eligible is True

    connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, corrected_value, evidence_excerpt,
            evidence_location, reviewer, decision, supersedes_review_revision_id,
            reviewed_at
        ) VALUES (?, 'dose', '0.75', 'Correction was assigned to the wrong arm.',
                  'human review record', 'reviewer-b', 'rejected', ?,
                  '2026-08-06T12:00:00Z')
        """,
        (experiment_id, accepted_id),
    )

    result = evaluate_eligibility(connection, experiment_id, "comet")

    assert result.eligible is False
    assert "dose" in result.reasons
    assert connection.execute(
        "SELECT corrected_value FROM review_revision ORDER BY review_revision_id"
    ).fetchall() == [("0.75",), ("0.75",)]


def test_accepted_correction_can_be_superseded_append_only(arm_database) -> None:
    connection, experiment_id = arm_database
    connection.execute(
        "UPDATE experiment SET dose = NULL WHERE experiment_id = ?",
        (experiment_id,),
    )
    accepted_id = connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, corrected_value, evidence_excerpt,
            evidence_location, reviewer, reviewed_at
        ) VALUES (?, 'dose', '0.75', 'Animals received 0.75 mg/kg.',
                  'methods, p. 3', 'reviewer-a', '2026-08-06T11:00:00Z')
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
        (experiment_id, accepted_id),
    )

    connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, corrected_value, evidence_excerpt,
            evidence_location, reviewer, supersedes_review_revision_id,
            reviewed_at
        ) VALUES (?, 'dose', '0.50', 'The corrected dose was 0.50 mg/kg.',
                  'methods, p. 3', 'reviewer-b', ?, '2026-08-06T12:00:00Z')
        """,
        (experiment_id, accepted_id),
    )

    assert evaluate_eligibility(connection, experiment_id, "comet").eligible is True
    replacement_id = connection.execute(
        "SELECT MAX(review_revision_id) FROM review_revision"
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, corrected_value, evidence_excerpt,
            evidence_location, reviewer, supersedes_review_revision_id,
            reviewed_at
        ) VALUES (?, 'dose', 'not-a-dose', 'The value requires another review.',
                  'methods, p. 3', 'reviewer-c', ?, '2026-08-06T13:00:00Z')
        """,
        (experiment_id, replacement_id),
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
