from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.database.import_bundle import _IMPORT_SCHEMA
from src.init_db import initialize_database


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def review_database(tmp_path: Path) -> Path:
    path = tmp_path / "review.db"
    initialize_database(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_IMPORT_SCHEMA)
    first_paper = connection.execute(
        """
        INSERT INTO paper (
            source_paper_id, pmid, pmcid, doi, title, source_type,
            source_url, retrieval_date, screening_status, import_status
        ) VALUES (
            'P-001', '123', 'PMC123', '10.1/example', 'First paper', 'fixture',
            'https://publisher.example/paper', '2026-08-06', 'include', 'ready'
        )
        """
    ).lastrowid
    second_paper = connection.execute(
        """
        INSERT INTO paper (
            source_paper_id, title, source_type, retrieval_date,
            screening_status, import_status
        ) VALUES ('P-002', 'Second paper', 'fixture', '2026-08-06', 'include', 'ready')
        """
    ).lastrowid
    formulation_id = connection.execute(
        """
        INSERT INTO formulation (paper_id, formulation_name, composition_raw, composition_basis)
        VALUES (?, 'LNP-A', '50:10:38.5:1.5', 'mol%')
        """,
        (first_paper,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO chemical_component (
            formulation_id, component_name_reported, component_role, molar_percentage, percentage_unit
        ) VALUES (?, 'Lipid A', 'ionizable_lipid', 50, 'mol%')
        """,
        (formulation_id,),
    )
    ready_arm = connection.execute(
        """
        INSERT INTO experiment (
            paper_id, formulation_id, cell_type, species, in_vitro_in_vivo,
            payload_type, payload_name, dose, dose_unit, route, timepoint,
            timepoint_unit, assay
        ) VALUES (?, ?, 'hepatocyte', 'mouse', 'in_vivo', 'mRNA', 'Luciferase',
                  1, 'mg/kg', 'iv', 24, 'h', 'ELISA')
        """,
        (first_paper, formulation_id),
    ).lastrowid
    incomplete_arm = connection.execute(
        """
        INSERT INTO experiment (paper_id, formulation_id, cell_type, payload_type)
        VALUES (?, ?, 'kupffer_cell', 'siRNA')
        """,
        (first_paper, formulation_id),
    ).lastrowid
    outcome_id = connection.execute(
        """
        INSERT INTO outcome (
            experiment_id, endpoint_family, endpoint_name, outcome_value,
            outcome_unit, normalization_basis, value_status
        ) VALUES (?, 'functional_expression', 'Luciferase', 12, 'ng/mL', 'total protein', 'reported')
        """,
        (ready_arm,),
    ).lastrowid
    auto_evidence = connection.execute(
        """
        INSERT INTO evidence (
            paper_id, experiment_id, outcome_id, field_name, evidence_text,
            evidence_location_type, section_name, page_number, extraction_method,
            extraction_confidence, evidence_review_status
        ) VALUES (?, ?, ?, 'payload_name', 'Luciferase mRNA was dosed.', 'methods',
                  'Methods', '3', 'text_extraction', 'high', 'unreviewed')
        """,
        (first_paper, ready_arm, outcome_id),
    ).lastrowid
    manual_evidence = connection.execute(
        """
        INSERT INTO evidence (
            paper_id, experiment_id, outcome_id, field_name, evidence_text,
            evidence_location_type, section_name, figure_number, extraction_method,
            extraction_confidence, evidence_review_status
        ) VALUES (?, ?, ?, 'outcome_value', 'Expression reached 12 ng/mL.', 'figure',
                  'Results', '2', 'vision', 'medium', 'manually_verified')
        """,
        (first_paper, ready_arm, outcome_id),
    ).lastrowid
    foreign_evidence = connection.execute(
        """
        INSERT INTO evidence (
            paper_id, field_name, evidence_text, evidence_location_type,
            extraction_method, extraction_confidence
        ) VALUES (?, 'species', 'Foreign paper evidence.', 'methods', 'manual', 'high')
        """,
        (second_paper,),
    ).lastrowid
    for entity_type, entity_id, field_name, evidence_id, status, key, note in (
        ('arm', ready_arm, 'payload_name', auto_evidence, 'automatically_validated', 'payload', 'first'),
        ('arm', ready_arm, 'payload_name', auto_evidence, 'automatically_validated', 'payload', 'duplicate excerpt'),
        ('outcome', outcome_id, 'outcome_value', manual_evidence, 'manually_verified', 'outcome', 'manual'),
        ('arm', ready_arm, 'species', foreign_evidence, 'manually_verified', 'foreign', 'invalid ownership'),
    ):
        content = json.dumps({'status': status, 'key': key, 'note': note}, sort_keys=True)
        connection.execute(
            """
            INSERT INTO import_field_evidence (
                paper_id, entity_type, entity_id, field_name, evidence_id,
                verification_status, natural_key, content_sha256, content_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (first_paper, entity_type, entity_id, field_name, evidence_id, status,
             key, _hash(content), content),
        )
    for profile, eligible, evaluated_at in (
        ('nearest_neighbor', 0, '2026-08-06T08:00:00Z'),
        ('nearest_neighbor', 1, '2026-08-06T09:00:00Z'),
        ('comet', 1, '2026-08-06T09:00:00Z'),
    ):
        connection.execute(
            """
            INSERT INTO eligibility_result (
                experiment_id, profile, eligible, reasons_json, rules_version, evaluated_at
            ) VALUES (?, ?, ?, '[]', 'test-v1', ?)
            ON CONFLICT(experiment_id, profile) DO UPDATE SET
                eligible=excluded.eligible, evaluated_at=excluded.evaluated_at
            """,
            (ready_arm, profile, eligible, evaluated_at),
        )
    connection.execute(
        """
        INSERT INTO import_review (
            paper_id, natural_key, arm_id, reason_code, review_status, review_tag,
            field_name, notes, evidence_ids_json, content_sha256
        ) VALUES (?, 'target-cell', ?, 'target_cell_confirmation', 'incomplete',
                  'Needs human verification', 'cell_type', 'Confirm target cell', '[]', ?)
        """,
        (first_paper, incomplete_arm, _hash('target-cell')),
    )
    first_revision = connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, previous_value, corrected_value, evidence_excerpt,
            evidence_location, reviewer, decision, reviewer_notes, reviewed_at
        ) VALUES (?, 'payload_name', 'Luciferase', 'mRNA-LUC', 'Luciferase mRNA was dosed.',
                  'Methods p. 3', 'reviewer', 'accepted', 'Corrected name', '2026-08-06T10:00:00Z')
        """,
        (ready_arm,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO review_revision (
            experiment_id, field_name, previous_value, corrected_value, evidence_excerpt,
            evidence_location, reviewer, decision, supersedes_review_revision_id,
            reviewer_notes, reviewed_at
        ) VALUES (?, 'payload_name', 'mRNA-LUC', 'Luciferase mRNA', 'Luciferase mRNA was dosed.',
                  'Methods p. 3', 'reviewer', 'accepted', ?, 'Final correction', '2026-08-06T11:00:00Z')
        """,
        (ready_arm, first_revision),
    )
    connection.commit()
    connection.close()
    return path


def test_authoritative_database_path_uses_common_checkout_resolver() -> None:
    from src.database.audit_current_database import CANONICAL_AUTHORITATIVE_DATABASE
    from src.ui.review_service import authoritative_database_path

    assert authoritative_database_path() == CANONICAL_AUTHORITATIVE_DATABASE


def test_dashboard_counts_latest_eligible_arms_and_deduplicated_usable_facts(
    monkeypatch: pytest.MonkeyPatch, review_database: Path
) -> None:
    from src import ui
    from src.ui.review_service import load_dashboard

    monkeypatch.setattr(ui.review_service, 'authoritative_database_path', lambda: review_database)

    dashboard = load_dashboard()

    assert dashboard.nearest_neighbor_ready_arms == 1
    assert dashboard.comet_ready_arms == 1
    assert dashboard.automatically_validated_usable_facts == 1
    assert dashboard.manually_verified_usable_facts == 1
    assert dashboard.usable_field_facts == 2


def test_paper_summaries_report_physical_rows_exactly(
    monkeypatch: pytest.MonkeyPatch, review_database: Path
) -> None:
    from src import ui
    from src.ui.review_service import list_paper_summaries

    monkeypatch.setattr(ui.review_service, 'authoritative_database_path', lambda: review_database)

    summaries = list_paper_summaries()

    first = summaries[0]
    assert first.source_paper_id == 'P-001'
    assert first.row_counts.formulations == 1
    assert first.row_counts.chemical_components == 1
    assert first.row_counts.experimental_arms == 2
    assert first.row_counts.outcomes == 1
    assert first.row_counts.evidence_excerpts == 2
    assert first.row_counts.usable_field_facts == 2
    assert first.row_counts.open_review_items == 1
    assert first.row_counts.review_history_revisions == 2
    assert summaries[1].row_counts.evidence_excerpts == 1


def test_review_arms_prioritize_near_complete_then_review_records(
    monkeypatch: pytest.MonkeyPatch, review_database: Path
) -> None:
    from src import ui
    from src.ui.review_service import list_review_arms

    monkeypatch.setattr(ui.review_service, 'authoritative_database_path', lambda: review_database)

    arms = list_review_arms()

    assert [arm.experiment_id for arm in arms] == [1, 2]
    assert arms[0].comet_eligible is True
    assert arms[1].review_reason == 'Needs human verification'


def test_arm_workspace_exposes_explicit_blanks_owned_evidence_and_history(
    monkeypatch: pytest.MonkeyPatch, review_database: Path
) -> None:
    from src import ui
    from src.ui.review_service import load_arm_workspace

    monkeypatch.setattr(ui.review_service, 'authoritative_database_path', lambda: review_database)

    workspace = load_arm_workspace(1)

    fields = {field.name: field for field in workspace.fields}
    assert fields['payload_name'].value == 'Luciferase mRNA'
    assert fields['delivery_cell'].value == ''
    assert fields['delivery_cell'].is_blank is True
    assert [evidence.evidence_id for evidence in workspace.evidence] == [1, 2]
    assert [revision.corrected_value for revision in workspace.history] == [
        'Luciferase mRNA', 'mRNA-LUC'
    ]
