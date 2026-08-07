from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.database.import_bundle import _IMPORT_SCHEMA
from src.database.status import RULES_VERSION
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
    component_id = connection.execute(
        """
        INSERT INTO chemical_component (
            formulation_id, component_name_reported, component_role, molar_percentage, percentage_unit
        ) VALUES (?, 'Lipid A', 'ionizable_lipid', 50, 'mol%')
        """,
        (formulation_id,),
    ).lastrowid
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
    formulation_evidence = connection.execute(
        """
        INSERT INTO evidence (
            paper_id, field_name, evidence_text, evidence_location_type,
            extraction_method, extraction_confidence
        ) VALUES (?, 'composition_raw', 'The formulation ratio was 50:10:38.5:1.5.',
                  'table', 'structured_table', 'high')
        """, (first_paper,)
    ).lastrowid
    component_evidence = connection.execute(
        """
        INSERT INTO evidence (
            paper_id, field_name, evidence_text, evidence_location_type,
            extraction_method, extraction_confidence
        ) VALUES (?, 'component_name_reported', 'Lipid A was the ionizable lipid.',
                  'methods', 'text_extraction', 'high')
        """, (first_paper,)
    ).lastrowid
    for entity_type, entity_id, field_name, evidence_id, status, key, note in (
        ('arm', ready_arm, 'payload_name', auto_evidence, 'automatically_validated', 'payload', 'first'),
        ('arm', ready_arm, 'payload_name', auto_evidence, 'automatically_validated', 'payload', 'duplicate excerpt'),
        ('outcome', outcome_id, 'outcome_value', manual_evidence, 'manually_verified', 'outcome', 'manual'),
        ('arm', ready_arm, 'species', foreign_evidence, 'manually_verified', 'foreign', 'invalid ownership'),
        ('formulation', formulation_id, 'composition_raw', formulation_evidence, 'automatically_validated', 'formulation', 'formulation link'),
        ('component', component_id, 'component_name_reported', component_evidence, 'automatically_validated', 'component', 'component link'),
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
            ) VALUES (?, ?, ?, '[]', ?, ?)
            ON CONFLICT(experiment_id, profile) DO UPDATE SET
                eligible=excluded.eligible, evaluated_at=excluded.evaluated_at
            """,
            (ready_arm, profile, eligible, RULES_VERSION, evaluated_at),
        )
    connection.execute(
        """
        INSERT INTO import_review (
            paper_id, natural_key, arm_id, reason_code, review_status, review_tag,
            field_name, notes, evidence_ids_json, content_sha256
        ) VALUES (?, 'target-cell', ?, 'automatic_resolution_required', 'incomplete',
                  'Needs automatic resolution', 'cell_type', 'Resolve target cell', '[]', ?)
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
    from src.database.paths import CANONICAL_AUTHORITATIVE_DATABASE
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
    assert dashboard.automatically_validated_usable_facts == 3
    assert dashboard.manually_verified_usable_facts == 1
    assert dashboard.usable_field_facts == 4


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
    assert first.row_counts.evidence_excerpts == 4
    assert first.row_counts.usable_field_facts == 4
    assert first.row_counts.open_review_items == 1
    assert first.row_counts.review_history_revisions == 2
    assert summaries[1].row_counts.evidence_excerpts == 1


def test_workspace_includes_linked_outcomes_and_service_configured_access_links(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    from src.ui.review_service import load_arm_workspace, paper_access_links

    local_full_text = tmp_path / 'P-001.pdf'
    local_full_text.write_text('fixture full text', encoding='utf-8')
    from src.ui import review_service
    monkeypatch.setattr(review_service, 'authoritative_database_path', lambda: review_database)
    monkeypatch.setenv('AI_LNP_LOCAL_FULL_TEXT_DIR', str(tmp_path))
    monkeypatch.setenv('AI_LNP_INSTITUTIONAL_LIBRARY_URL', 'https://library.example/search')

    workspace = load_arm_workspace(1)
    links = paper_access_links(workspace.paper)

    assert workspace.outcomes[0].endpoint_name == 'Luciferase'
    assert workspace.outcomes[0].value == '12'
    assert links.local_full_text_url == local_full_text.as_uri()
    assert links.institutional_library_url == 'https://library.example/search'


def test_dashboard_ignores_eligibility_from_an_obsolete_rules_version(
    monkeypatch: pytest.MonkeyPatch, review_database: Path
) -> None:
    from src import ui
    from src.ui.review_service import load_dashboard

    connection = sqlite3.connect(review_database)
    connection.execute("UPDATE eligibility_result SET rules_version = 'obsolete-rules'")
    connection.commit()
    connection.close()
    monkeypatch.setattr(ui.review_service, 'authoritative_database_path', lambda: review_database)

    dashboard = load_dashboard()

    assert dashboard.nearest_neighbor_ready_arms == 0
    assert dashboard.comet_ready_arms == 0


def test_review_arms_follow_the_specified_review_priority(
    monkeypatch: pytest.MonkeyPatch, review_database: Path
) -> None:
    from src import ui
    from src.ui.review_service import list_review_arms

    monkeypatch.setattr(ui.review_service, 'authoritative_database_path', lambda: review_database)

    connection = sqlite3.connect(review_database)
    extra_arms = [
        connection.execute(
            "INSERT INTO experiment (paper_id, formulation_id, cell_type, payload_type) VALUES (1, 1, 'hepatocyte', 'mRNA')"
        ).lastrowid
        for _ in range(4)
    ]
    connection.executemany(
        """INSERT INTO arm_assessment (
            experiment_id, completeness_status, missing_fields_json, verification_status, updated_at
        ) VALUES (?, ?, ?, ?, '2026-08-06T12:00:00Z')""",
        [
            (1, 'complete', '[]', 'unreviewed'),
            (2, 'conflict', '[]', 'conflict'),
                (extra_arms[0], 'incomplete', '[]', 'unreviewed'),
            (extra_arms[1], 'incomplete', '[]', 'unreviewed'),
            (extra_arms[2], 'incomplete', '["species", "assay", "dose"]', 'unreviewed'),
        ],
    )
    for arm_id, status, tag, key in (
            (extra_arms[1], 'incomplete', 'Needs automatic resolution', 'target_cell_confirmation'),
        (extra_arms[2], 'blocked', 'Source file unavailable', 'blocked'),
        (extra_arms[3], 'quarantined', 'Source file unavailable', 'quarantined'),
    ):
        connection.execute(
            """INSERT INTO import_review (
                paper_id, natural_key, arm_id, reason_code, review_status, review_tag,
                evidence_ids_json, content_sha256
            ) VALUES (1, ?, ?, ?, ?, ?, '[]', ?)""",
            (key, arm_id, key, status, tag, _hash(key)),
            )
    connection.executemany(
        """INSERT INTO eligibility_result (
            experiment_id, profile, eligible, reasons_json, rules_version, evaluated_at
        ) VALUES (?, 'comet', 0, ?, ?, '2026-08-06T12:00:00Z')""",
        [
            (extra_arms[0], '["normalization_basis"]', RULES_VERSION),
            (2, '["dose"]', RULES_VERSION),
            (extra_arms[2], '["dose"]', RULES_VERSION),
            (extra_arms[3], '["dose", "route"]', RULES_VERSION),
        ],
    )
    connection.commit()
    connection.close()
    arms = list_review_arms()

    assert {arm.experiment_id: arm.review_reason_code for arm in arms}[extra_arms[1]] == 'target_cell_confirmation'
    assert arms[1].experiment_id == extra_arms[0]
    assert [arm.experiment_id for arm in arms] == [
        1, extra_arms[0], extra_arms[1], 2, extra_arms[2], extra_arms[3]
    ]


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
    assert [evidence.evidence_id for evidence in workspace.evidence] == [1, 2, 4, 5]
    assert [revision.corrected_value for revision in workspace.history] == [
        'Luciferase mRNA', 'mRNA-LUC'
    ]


def _write_readiness(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
):
    """Create the external, verified backup capability needed by write tests."""

    from src import ui
    from src.ui.review_service import prepare_writes

    monkeypatch.setattr(ui.review_service, 'authoritative_database_path', lambda: review_database)
    readiness = prepare_writes(tmp_path / 'review-backups')
    assert readiness.ready is True
    assert readiness.backup_path is not None
    return readiness


def _workspace_token(experiment_id: int) -> str:
    from src.ui.review_service import load_arm_workspace

    return load_arm_workspace(experiment_id).state_token


def test_prepare_writes_requires_a_current_schema_and_verified_external_backup(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """A broken safety preflight must never return a capability for writes."""

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)

    assert readiness.database_path == review_database
    assert readiness.schema_version == 6
    assert readiness.backup_path.parent == (tmp_path / 'review-backups').resolve()
    assert readiness.backup_sha256

    connection = sqlite3.connect(review_database)
    connection.execute('DELETE FROM schema_migration WHERE version = 3')
    connection.commit()
    connection.close()
    from src.ui.review_service import prepare_writes

    unsafe = prepare_writes(tmp_path / 'review-backups')

    assert unsafe.ready is False
    assert 'schema' in (unsafe.failure_reason or '').lower()


def test_corrected_decision_is_append_only_and_keeps_source_evidence_unchanged(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Replacing a correction must not replace either source extraction or evidence."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    original_evidence = sqlite3.connect(review_database).execute(
        'SELECT evidence_text, evidence_review_status FROM evidence WHERE evidence_id = 1'
    ).fetchone()
    result = apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='correct',
        corrected_value='LUC-mRNA', evidence_id=1, reviewer='reviewer-b',
        reviewer_notes='The methods section uses the canonical payload name.',
        expected_review_revision_id=2, expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))

    workspace = load_arm_workspace(1)
    connection = sqlite3.connect(review_database)
    history = connection.execute(
        'SELECT decision, corrected_value, supersedes_review_revision_id FROM review_revision '
        'WHERE experiment_id = 1 ORDER BY review_revision_id'
    ).fetchall()
    source_value = connection.execute(
        'SELECT payload_name FROM experiment WHERE experiment_id = 1'
    ).fetchone()[0]
    evidence = connection.execute(
        'SELECT evidence_text, evidence_review_status FROM evidence WHERE evidence_id = 1'
    ).fetchone()
    connection.close()

    assert result.review_revision_id == 3
    assert workspace.fields[9].value == 'LUC-mRNA'
    assert source_value == 'Luciferase'
    assert evidence == original_evidence
    assert history[-1] == ('accepted', 'LUC-mRNA', 2)


def test_formulation_field_correction_reads_the_formulation_entity_not_experiment(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Formulation fields are reviewable overlays even though they are not experiment columns."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    result = apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='composition_ratio', decision='correct',
        corrected_value='50:10:38:2', evidence_id=4, reviewer='reviewer-b',
        reviewer_notes='Table 1 provides the corrected molar ratio.', expected_review_revision_id=2,
        expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))

    fields = {field.name: field.value for field in load_arm_workspace(1).fields}
    assert result.review_revision_id == 3
    assert fields['composition_ratio'] == '50:10:38:2'


def test_formulation_correction_is_active_for_every_arm_sharing_the_entity(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """An entity correction must not disappear when a sibling arm is selected."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, list_review_arms, load_arm_workspace

    connection = sqlite3.connect(review_database)
    connection.execute('UPDATE formulation SET formulation_name = NULL WHERE formulation_id = 1')
    connection.execute(
        """INSERT INTO missing_field (experiment_id, field_name, reason, recorded_at)
           VALUES (2, 'formulation_name', 'not extracted', '2026-08-06T09:00:00Z')"""
    )
    connection.commit()
    connection.close()
    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='formulation', decision='correct',
        corrected_value='LNP-A reviewed', evidence_id=4, reviewer='reviewer-b',
        reviewer_notes='The table identifies the shared formulation.', expected_review_revision_id=2,
        expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))

    sibling_fields = {field.name: field.value for field in load_arm_workspace(2).fields}
    sibling_arm = next(arm for arm in list_review_arms() if arm.experiment_id == 2)
    sibling_assessment = sqlite3.connect(review_database).execute(
        'SELECT missing_fields_json FROM arm_assessment WHERE experiment_id = 2'
    ).fetchone()
    sibling_comet_reasons = json.loads(sqlite3.connect(review_database).execute(
        "SELECT reasons_json FROM eligibility_result WHERE experiment_id = 2 AND profile = 'comet'"
    ).fetchone()[0])

    assert sibling_fields['formulation'] == 'LNP-A reviewed'
    assert sibling_arm.formulation == 'LNP-A reviewed'
    assert sibling_assessment is not None
    assert 'formulation_name' not in json.loads(sibling_assessment[0])
    assert 'formulation_identity' not in sibling_comet_reasons


def test_correction_resolves_a_not_reported_missing_state_without_leaving_a_blocker(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """A later supported value must be able to resolve a prior not-reported conclusion."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    initial_token = _workspace_token(1)
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='dose', decision='not_reported', reviewer='reviewer-b',
        reviewer_notes='No dose was found in the initially reviewed source.', expected_review_revision_id=2,
        expected_state_token=initial_token, write_readiness=readiness,
    ))
    connection = sqlite3.connect(review_database)
    dose_evidence = connection.execute(
        """INSERT INTO evidence (
               paper_id, experiment_id, field_name, evidence_text, evidence_location_type,
               extraction_method, extraction_confidence
           ) VALUES (1, 1, 'dose', 'Animals received 0.75 mg/kg.', 'methods', 'manual', 'high')"""
    ).lastrowid
    connection.commit()
    connection.close()
    workspace = load_arm_workspace(1)

    result = apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='dose', decision='correct', corrected_value='0.75',
        evidence_id=dose_evidence, reviewer='reviewer-c',
        reviewer_notes='A later source review found the dosing statement.',
        expected_review_revision_id=max(item.review_revision_id for item in workspace.history),
        expected_state_token=workspace.state_token,
        write_readiness=readiness,
    ))

    assert result.review_revision_id == 4
    assert 'dose' not in result.arm_status.missing_fields


def test_pasted_evidence_correction_is_stored_and_recalculates_comet_v3(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    from src.ui.review_service import ReviewDecision, apply_review_decision

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    result = apply_review_decision(ReviewDecision(
        experiment_id=2,
        field_name='species',
        decision='correct',
        corrected_value='mouse',
        evidence_excerpt='Experiments were performed in C57BL/6 mice.',
        evidence_location='Methods, page 4',
        reviewer='reviewer-c',
        reviewer_notes='Copied directly from the paper.',
        expected_review_revision_id=0,
        expected_state_token=_workspace_token(2),
        write_readiness=readiness,
    ))

    connection = sqlite3.connect(review_database)
    evidence = connection.execute(
        "SELECT evidence_text,section_name FROM evidence "
        "WHERE experiment_id=2 ORDER BY evidence_id DESC LIMIT 1"
    ).fetchone()
    connection.close()
    assert evidence == ('Experiments were performed in C57BL/6 mice.', 'Methods, page 4')
    assert result.review_revision_id is not None
    assert result.comet.rules_version == 'working-evidence-v3'


def test_list_comet_gap_arms_returns_only_small_comet_gap_queue(
    monkeypatch: pytest.MonkeyPatch, review_database: Path
) -> None:
    from src.ui import review_service

    with sqlite3.connect(review_database) as connection:
        connection.execute(
            """INSERT INTO eligibility_result (
                   experiment_id,profile,eligible,reasons_json,rules_version,evaluated_at
               ) VALUES (2,'comet',0,'[\"species\",\"dose\"]',
                         'readiness-profiles/v3','2026-08-07T00:00:00Z')
               ON CONFLICT(experiment_id,profile) DO UPDATE SET
                 eligible=0,reasons_json=excluded.reasons_json,
                 rules_version=excluded.rules_version,evaluated_at=excluded.evaluated_at"""
        )
        connection.commit()
    monkeypatch.setattr(review_service, 'authoritative_database_path', lambda: review_database)

    gaps = review_service.list_comet_gap_arms()

    assert [arm.experiment_id for arm in gaps] == [2]
    assert gaps[0].comet_blockers == ('species', 'dose')


def test_accept_decision_marks_linked_evidence_manually_verified(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Accepting an extracted value records a human-verification event."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_dashboard

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    result = apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='accept', evidence_id=1,
        reviewer='reviewer-b', reviewer_notes='The excerpt supports the extracted value.',
        expected_review_revision_id=2, expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))
    connection = sqlite3.connect(review_database)
    verification = connection.execute(
        'SELECT verification_status FROM field_verification WHERE experiment_id = 1 '
        "AND field_name = 'payload_name' ORDER BY field_verification_id DESC LIMIT 1"
    ).fetchone()[0]
    connection.close()

    assert result.decision == 'accept'
    assert result.review_revision_id is not None
    assert verification == 'manually_verified'
    assert result.nearest_neighbor.eligible is True
    assert result.comet.eligible is False
    assert 'lnp_molar_ratio' in result.comet.reasons
    dashboard = load_dashboard()
    assert dashboard.automatically_validated_usable_facts == 2
    assert dashboard.manually_verified_usable_facts == 2


@pytest.mark.parametrize(
    ('decision', 'verification_status'),
    [('not_reported', 'rejected'), ('unresolved', 'ambiguous')],
)
def test_nonfinal_field_decisions_preserve_value_and_leave_an_explicit_missing_record(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path,
    decision: str, verification_status: str,
) -> None:
    """Not-reported and unresolved are explicit blockers, never synthetic values."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='dose', decision=decision, reviewer='reviewer-b',
        reviewer_notes='The dosing detail cannot be supported by the reviewed source.',
        expected_review_revision_id=2, expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))
    connection = sqlite3.connect(review_database)
    value = connection.execute('SELECT dose FROM experiment WHERE experiment_id = 1').fetchone()[0]
    missing = connection.execute(
        "SELECT resolved_by_review_revision_id FROM missing_field WHERE experiment_id = 1 AND field_name = 'dose'"
    ).fetchone()
    verification = connection.execute(
        "SELECT verification_status FROM field_verification WHERE experiment_id = 1 AND field_name = 'dose' "
        'ORDER BY field_verification_id DESC LIMIT 1'
    ).fetchone()[0]
    history = connection.execute(
        "SELECT corrected_value, reviewer_notes FROM review_revision WHERE experiment_id = 1 AND field_name = 'dose'"
    ).fetchall()
    connection.close()

    assert value == 1
    assert missing == (None,)
    assert verification == verification_status
    assert len(history) == 1
    assert history[0][1] == 'The dosing detail cannot be supported by the reviewed source.'
    assert {field.name: field.value for field in load_arm_workspace(1).fields}['dose'] == '1.0'


@pytest.mark.parametrize('decision', ['accept', 'correct', 'not_reported', 'reject', 'wrong_arm', 'unresolved'])
def test_every_submitted_action_appends_complete_immutable_history(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path, decision: str
) -> None:
    """No final review action may exist only in mutable verification or queue state."""

    from src.ui.review_service import ReviewDecision, apply_review_decision

    connection = sqlite3.connect(review_database)
    foreign_arm_evidence = connection.execute(
        """INSERT INTO evidence (
               paper_id, experiment_id, field_name, evidence_text, evidence_location_type,
               extraction_method, extraction_confidence
           ) VALUES (1, 2, 'payload_name', 'Arm 2 used siRNA.', 'methods', 'manual', 'high')"""
    ).lastrowid
    original_evidence = connection.execute(
        """INSERT INTO evidence (
               paper_id, experiment_id, field_name, evidence_text, evidence_location_type,
               extraction_method, extraction_confidence
           ) VALUES (1, 1, 'dose', 'The dose statement is disputed.', 'methods', 'manual', 'high')"""
    ).lastrowid
    connection.commit()
    connection.close()
    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    evidence_id = {
        'accept': 1, 'correct': 1, 'reject': original_evidence,
        'wrong_arm': foreign_arm_evidence,
    }.get(decision)
    field_name = 'payload_name' if decision in {'accept', 'correct', 'wrong_arm'} else 'dose'

    result = apply_review_decision(ReviewDecision(
        experiment_id=1, field_name=field_name, decision=decision,
        corrected_value='LUC mRNA' if decision == 'correct' else None,
        evidence_id=evidence_id, reviewer='reviewer-history',
        reviewer_notes=f'History for {decision}.', expected_review_revision_id=2,
        expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))

    connection = sqlite3.connect(review_database)
    row = connection.execute(
        """SELECT review_action, entity_type, entity_id, field_name, evidence_id,
                  reviewer, reviewer_notes, reviewed_at
           FROM review_revision WHERE review_revision_id = ?""",
        (result.review_revision_id,),
    ).fetchone()
    connection.close()

    assert result.review_revision_id is not None
    assert row[:4] == (decision, 'arm', 1, field_name)
    assert row[4] == evidence_id
    assert row[5] == 'reviewer-history'
    assert row[6] == f'History for {decision}.'
    assert row[7]


def test_rejected_correction_supersedes_the_active_history_without_deleting_it(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """A rejection retracts an accepted correction by appending a linked revision."""

    from src.ui.review_service import ReviewDecision, apply_review_decision

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    result = apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='reject', reviewer='reviewer-b',
        reviewer_notes='The correction is not supported by the cited source.',
        expected_review_revision_id=2, expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))
    connection = sqlite3.connect(review_database)
    revisions = connection.execute(
        'SELECT decision, supersedes_review_revision_id FROM review_revision WHERE experiment_id = 1 '
        'ORDER BY review_revision_id'
    ).fetchall()
    connection.close()

    assert result.review_revision_id is not None
    assert revisions[-1] == ('rejected', 2)
    assert len(revisions) == 3


def test_rejecting_an_active_correction_removes_its_canonical_fact_from_metrics(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """A superseded evidence link must not remain a usable manually verified fact."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_dashboard, load_arm_workspace

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='accept', evidence_id=1,
        reviewer='reviewer-b', reviewer_notes='The excerpt supports this payload.',
        expected_review_revision_id=2, expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))
    assert load_dashboard().manually_verified_usable_facts == 2
    workspace = load_arm_workspace(1)
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='reject', reviewer='reviewer-c',
        reviewer_notes='The accepted payload claim is unsupported.', expected_review_revision_id=3,
        expected_state_token=workspace.state_token, write_readiness=readiness,
    ))

    assert load_dashboard().manually_verified_usable_facts == 1


def test_rejecting_original_evidence_needs_no_prior_accepted_correction(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Unsupported original extraction can be rejected without manufacturing a correction."""

    from src.ui.review_service import ReviewDecision, apply_review_decision

    connection = sqlite3.connect(review_database)
    evidence_id = connection.execute(
        """INSERT INTO evidence (
               paper_id, experiment_id, field_name, evidence_text, evidence_location_type,
               extraction_method, extraction_confidence
           ) VALUES (1, 2, 'payload_name', 'This evidence is unsupported.', 'methods', 'manual', 'high')"""
    ).lastrowid
    connection.commit()
    connection.close()
    readiness = _write_readiness(monkeypatch, review_database, tmp_path)

    result = apply_review_decision(ReviewDecision(
        experiment_id=2, field_name='payload_name', decision='reject', evidence_id=evidence_id,
        reviewer='reviewer-b', reviewer_notes='This excerpt does not support the field.',
        expected_review_revision_id=0, expected_state_token=_workspace_token(2), write_readiness=readiness,
    ))
    connection = sqlite3.connect(review_database)
    verification = connection.execute(
        "SELECT verification_status FROM field_verification WHERE experiment_id = 2 AND field_name = 'payload_name'"
    ).fetchone()[0]
    missing = connection.execute(
        "SELECT reason FROM missing_field WHERE experiment_id = 2 AND field_name = 'payload_name'"
    ).fetchone()[0]
    preserved = connection.execute('SELECT evidence_text FROM evidence WHERE evidence_id = ?', (evidence_id,)).fetchone()[0]
    connection.close()

    assert result.review_revision_id is not None
    assert verification == 'rejected'
    assert missing == 'rejected during human review'
    assert preserved == 'This evidence is unsupported.'


def test_rejecting_original_canonical_evidence_removes_it_from_usable_fact_metrics(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """A rejected source link must supersede its prior automatic usable-fact status."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_dashboard

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    assert load_dashboard().automatically_validated_usable_facts == 3
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='composition_ratio', decision='reject', evidence_id=4,
        reviewer='reviewer-b', reviewer_notes='The table excerpt does not support this ratio.',
        expected_review_revision_id=2, expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))

    dashboard = load_dashboard()
    assert dashboard.automatically_validated_usable_facts == 2
    assert dashboard.manually_verified_usable_facts == 1


@pytest.mark.parametrize(
    'sql',
    [
        "UPDATE experiment SET dose = 0.5 WHERE experiment_id = 1",
        "UPDATE evidence SET evidence_text = 'Changed evidence.' WHERE evidence_id = 1",
    ],
)
def test_stale_token_detects_scientific_or_evidence_changes(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path, sql: str
) -> None:
    """A browser token must bind the scientific values and selected evidence it reviewed."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    token = load_arm_workspace(1).state_token
    connection = sqlite3.connect(review_database)
    connection.execute(sql)
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match='stale'):
        apply_review_decision(ReviewDecision(
            experiment_id=1, field_name='payload_name', decision='accept', evidence_id=1,
            reviewer='reviewer-b', reviewer_notes='Submit the stale workspace.',
            expected_review_revision_id=2, expected_state_token=token, write_readiness=readiness,
        ))


def test_wrong_arm_marks_same_paper_foreign_arm_evidence_conflicted(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Evidence from another arm can be quarantined without moving the evidence row."""

    from src.ui.review_service import ReviewDecision, apply_review_decision

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    result = apply_review_decision(ReviewDecision(
        experiment_id=2, field_name='payload_name', decision='wrong_arm', evidence_id=1,
        reviewer='reviewer-b', reviewer_notes='This excerpt describes experimental arm 1.',
        expected_review_revision_id=0, expected_state_token=_workspace_token(2), write_readiness=readiness,
    ))
    connection = sqlite3.connect(review_database)
    review = connection.execute(
        "SELECT review_status, reason_code FROM import_review WHERE arm_id = 2 ORDER BY import_review_id DESC LIMIT 1"
    ).fetchone()
    evidence_arm = connection.execute('SELECT experiment_id FROM evidence WHERE evidence_id = 1').fetchone()[0]
    connection.close()

    assert result.review_revision_id is not None
    assert review == ('conflict', 'wrong_arm_evidence')
    assert evidence_arm == 1


def test_wrong_arm_retracts_an_active_correction_with_an_immutable_rejected_revision(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """A wrong-arm finding against an active correction must be auditable as a retraction."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace

    connection = sqlite3.connect(review_database)
    foreign_arm_evidence = connection.execute(
        """INSERT INTO evidence (
               paper_id, experiment_id, field_name, evidence_text, evidence_location_type,
               extraction_method, extraction_confidence
           ) VALUES (1, 2, 'payload_name', 'Arm 2 used a different payload.', 'methods', 'manual', 'high')"""
    ).lastrowid
    connection.commit()
    connection.close()
    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    foreign_candidate = next(
        item for item in load_arm_workspace(1).evidence
        if item.evidence_id == foreign_arm_evidence
    )
    assert foreign_candidate.experiment_id == 2

    result = apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='wrong_arm', evidence_id=foreign_arm_evidence,
        reviewer='reviewer-b', reviewer_notes='The correction was supported only by arm 2.',
        expected_review_revision_id=2, expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))
    connection = sqlite3.connect(review_database)
    revision = connection.execute(
        'SELECT decision, supersedes_review_revision_id, reviewer_notes FROM review_revision '
        'WHERE review_revision_id = ?', (result.review_revision_id,)
    ).fetchone()
    connection.close()

    assert result.decision == 'wrong_arm'
    assert revision == ('rejected', 2, 'The correction was supported only by arm 2.')


def test_stale_cross_paper_and_failing_decisions_roll_back_without_partial_history(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Bad submissions must not leave a revision, verification, or eligibility side effect."""

    from src.ui.review_service import ReviewDecision, apply_review_decision

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    initial_token = _workspace_token(1)
    accepted = ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='accept', evidence_id=1,
        reviewer='reviewer-b', reviewer_notes='Source checked.', expected_review_revision_id=2,
        expected_state_token=initial_token, write_readiness=readiness,
    )
    apply_review_decision(accepted)
    stale = ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='correct', corrected_value='stale', evidence_id=1,
        reviewer='reviewer-c', reviewer_notes='This browser state is stale.', expected_review_revision_id=2,
        expected_state_token=initial_token, write_readiness=readiness,
    )
    with pytest.raises(ValueError, match='stale'):
        apply_review_decision(stale)
    cross_paper = ReviewDecision(
        experiment_id=1, field_name='species', decision='correct', corrected_value='mouse', evidence_id=3,
        reviewer='reviewer-c', reviewer_notes='This must reject foreign-paper evidence.',
        expected_review_revision_id=3, expected_state_token=_workspace_token(1), write_readiness=readiness,
    )
    with pytest.raises(ValueError, match='same paper'):
        apply_review_decision(cross_paper)

    connection = sqlite3.connect(review_database)
    assert connection.execute('SELECT count(*) FROM review_revision WHERE experiment_id = 1').fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM field_verification WHERE field_name = 'species'").fetchone()[0] == 0
    connection.close()


def test_unresolved_decision_advances_the_workspace_token_and_rejects_a_stale_repeat(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Every final action, including unresolved, must invalidate the submitted workspace state."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    token = load_arm_workspace(1).state_token
    request = ReviewDecision(
        experiment_id=1, field_name='dose', decision='unresolved', reviewer='reviewer-b',
        reviewer_notes='The source does not settle the dosing value.', expected_review_revision_id=2,
        expected_state_token=token, write_readiness=readiness,
    )

    apply_review_decision(request)
    with pytest.raises(ValueError, match='stale'):
        apply_review_decision(request)


def test_not_reported_and_wrong_arm_invalidate_prior_canonical_fact_status(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Terminal negative actions must remove the selected fact from usable metrics."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace, load_dashboard

    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    assert load_dashboard().automatically_validated_usable_facts == 3
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='composition_ratio', decision='not_reported',
        reviewer='reviewer-b', reviewer_notes='The ratio is not reported in the source.',
        expected_review_revision_id=2, expected_state_token=_workspace_token(1), write_readiness=readiness,
    ))
    assert load_dashboard().automatically_validated_usable_facts == 2

    unresolved_workspace = load_arm_workspace(1)
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='composition_ratio', decision='unresolved',
        reviewer='reviewer-b', reviewer_notes='A second review still found no usable ratio.',
        expected_review_revision_id=max(
            item.review_revision_id for item in unresolved_workspace.history
        ), expected_state_token=unresolved_workspace.state_token, write_readiness=readiness,
    ))
    assert load_dashboard().automatically_validated_usable_facts == 2

    connection = sqlite3.connect(review_database)
    foreign_arm_evidence = connection.execute(
        """INSERT INTO evidence (
               paper_id, experiment_id, field_name, evidence_text, evidence_location_type,
               extraction_method, extraction_confidence
           ) VALUES (1, 2, 'payload_name', 'Arm 2 used this payload.', 'methods', 'manual', 'high')"""
    ).lastrowid
    connection.commit()
    connection.close()
    workspace = load_arm_workspace(1)
    apply_review_decision(ReviewDecision(
        experiment_id=1, field_name='payload_name', decision='wrong_arm', evidence_id=foreign_arm_evidence,
        reviewer='reviewer-c', reviewer_notes='The payload excerpt belongs to arm 2.',
        expected_review_revision_id=max(item.review_revision_id for item in workspace.history),
        expected_state_token=workspace.state_token, write_readiness=readiness,
    ))
    assert load_dashboard().automatically_validated_usable_facts == 1


def test_outcome_fields_are_reviewable_with_owned_evidence_and_history(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    """Outcome values use the same evidence-owned immutable review path as arm fields."""

    from src.ui.review_service import ReviewDecision, apply_review_decision, load_arm_workspace

    connection = sqlite3.connect(review_database)
    connection.execute("UPDATE evidence SET evidence_review_status = 'unreviewed' WHERE evidence_id = 2")
    connection.execute("DELETE FROM import_field_evidence WHERE entity_type = 'outcome' AND entity_id = 1")
    connection.commit()
    connection.close()
    readiness = _write_readiness(monkeypatch, review_database, tmp_path)
    workspace = load_arm_workspace(1)
    outcome_field = next(field for field in workspace.fields if field.name == 'outcome:1:outcome_value')
    assert outcome_field.value == '12'
    assert outcome_field.entity_type == 'outcome'
    assert outcome_field.entity_id == 1
    assert any(item.evidence_id == 2 and item.field_name == 'outcome_value' for item in workspace.evidence)

    not_reported_result = apply_review_decision(ReviewDecision(
        experiment_id=1, entity_type='outcome', entity_id=1, field_name='outcome_value',
        decision='not_reported', reviewer='reviewer-outcome',
        reviewer_notes='The first pass could not confirm the plotted value.',
        expected_review_revision_id=2, expected_state_token=workspace.state_token,
        write_readiness=readiness,
    ))
    connection = sqlite3.connect(review_database)
    assert connection.execute(
        "SELECT field_name FROM missing_field WHERE experiment_id = 1 ORDER BY missing_field_id DESC LIMIT 1"
    ).fetchone() == ('outcome:1:outcome_value',)
    connection.close()
    assert not_reported_result.comet.eligible is False
    assert 'usable_outcome' in not_reported_result.comet.reasons
    workspace = load_arm_workspace(1)
    result = apply_review_decision(ReviewDecision(
        experiment_id=1, entity_type='outcome', entity_id=1, field_name='outcome_value',
        decision='correct', corrected_value='14', evidence_id=2, reviewer='reviewer-outcome',
        reviewer_notes='Figure 2 supports 14 ng/mL.',
        expected_review_revision_id=max(item.review_revision_id for item in workspace.history),
        expected_state_token=workspace.state_token, write_readiness=readiness,
    ))

    revised = load_arm_workspace(1)
    corrected = next(field for field in revised.fields if field.name == 'outcome:1:outcome_value')
    history = next(item for item in revised.history if item.review_revision_id == result.review_revision_id)
    source_value = sqlite3.connect(review_database).execute(
        'SELECT outcome_value FROM outcome WHERE outcome_id = 1'
    ).fetchone()[0]

    assert corrected.value == '14'
    assert source_value == 12
    assert (history.entity_type, history.entity_id, history.field_name) == ('outcome', 1, 'outcome_value')
    assert result.comet.eligible is False
    assert 'usable_outcome' not in result.comet.reasons
    assert 'lnp_molar_ratio' in result.comet.reasons
