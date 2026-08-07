from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.readiness import evaluate_readiness
from src.init_db import initialize_database


@pytest.fixture
def readiness_database(tmp_path: Path):
    path = tmp_path / "readiness.db"
    initialize_database(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    paper_id = connection.execute(
        """
        INSERT INTO paper (
            source_paper_id,title,source_type,retrieval_date,
            screening_status,import_status
        ) VALUES ('READY-1','Readiness fixture','fixture','2026-08-07','include','ready')
        """
    ).lastrowid
    formulation_id = connection.execute(
        """
        INSERT INTO formulation (
            paper_id,formulation_name,chemical_formulation_total,
            lnp_molar_ratio,composition_raw,composition_basis
        ) VALUES (?, 'LNP-A', 'A-B-C-D', '50:10:38.5:1.5',
                  'A:B:C:D = 50:10:38.5:1.5', 'molar_ratio')
        """,
        (paper_id,),
    ).lastrowid
    experiment_id = connection.execute(
        """
        INSERT INTO experiment (
            paper_id,formulation_id,cell_type,cell_source,species,disease_model,
            in_vitro_in_vivo,payload_type,payload_name,payload_encoded_product,
            dose,dose_unit,assay
        ) VALUES (?,?,'hepatocyte','mouse hepatocytes','Mus musculus','healthy mouse',
                  'in_vivo','mRNA','eGFP mRNA','eGFP',10,'ug','IHC')
        """,
        (paper_id, formulation_id),
    ).lastrowid
    outcome_id = connection.execute(
        """
        INSERT INTO outcome (
            experiment_id,endpoint_family,endpoint_name,outcome_value,
            outcome_unit,normalization_basis,value_status
        ) VALUES (?,'functional_expression','eGFP-positive cells',80,'percent',
                  'total hepatocytes','reported')
        """,
        (experiment_id,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO evidence (
            paper_id,experiment_id,outcome_id,field_name,evidence_text,
            evidence_location_type,extraction_method,extraction_confidence,
            evidence_review_status
        ) VALUES (?,?,?,'outcome_value','80% of hepatocytes were eGFP positive.',
                  'results','text_extraction','high','manually_verified')
        """,
        (paper_id, experiment_id, outcome_id),
    )
    connection.commit()
    try:
        yield connection, experiment_id, formulation_id
    finally:
        connection.close()


def test_evidence_backed_arm_is_general_usable_without_blanket_review(
    readiness_database,
) -> None:
    connection, experiment_id, _ = readiness_database

    result = evaluate_readiness(connection, experiment_id)

    assert result.general_usable is True
    assert "human review" not in result.queue_label


def test_missing_formulation_ratio_is_visible_comet_blocker(
    readiness_database,
) -> None:
    connection, experiment_id, formulation_id = readiness_database
    connection.execute(
        "UPDATE formulation SET lnp_molar_ratio=NULL WHERE formulation_id=?",
        (formulation_id,),
    )

    result = evaluate_readiness(connection, experiment_id)

    assert result.comet_ready is False
    assert "lnp_molar_ratio" in result.comet_blockers
    assert result.queue_label == "almost_comet_ready"
    stored = connection.execute(
        "SELECT eligible,rules_version FROM eligibility_result "
        "WHERE experiment_id=? AND profile='comet'",
        (experiment_id,),
    ).fetchone()
    assert stored == (0, "working-evidence-v3")


def test_conflict_is_not_labeled_almost_comet_ready(readiness_database) -> None:
    connection, experiment_id, _ = readiness_database
    connection.execute(
        """
        INSERT INTO field_verification (
            experiment_id,field_name,verification_status,notes,verified_at
        ) VALUES (?,'species','conflict','mouse and rat both supported','2026-08-07')
        """,
        (experiment_id,),
    )

    result = evaluate_readiness(connection, experiment_id)

    assert result.queue_label == "conflict"
    assert result.general_usable is False


def test_not_applicable_field_does_not_block_comet(readiness_database) -> None:
    connection, experiment_id, _ = readiness_database
    connection.execute(
        "UPDATE experiment SET payload_encoded_product=NULL WHERE experiment_id=?",
        (experiment_id,),
    )
    connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id,entity_type,entity_id,field_name,previous_value,
            corrected_value,evidence_excerpt,evidence_location,reviewer,
            decision,reviewer_notes,reviewed_at,review_action
        ) VALUES (?,'arm',?,'payload_encoded_product',NULL,'not applicable',
                  'The payload is siRNA and encodes no product.','Methods','tester',
                  'accepted','not applicable for siRNA','2026-08-07','accept')
        """,
        (experiment_id, experiment_id),
    )

    result = evaluate_readiness(connection, experiment_id)

    assert "payload_encoded_product_or_molecular_target" not in result.comet_blockers
