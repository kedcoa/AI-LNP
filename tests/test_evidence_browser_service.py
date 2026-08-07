from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from src.init_db import initialize_database
from src.database.import_bundle import _IMPORT_SCHEMA


@pytest.fixture
def evidence_browser_database(tmp_path: Path) -> Path:
    database = tmp_path / "browser.db"
    initialize_database(database)
    local_html = tmp_path / "paper.html"
    local_html.write_text("<html>paper</html>", encoding="utf-8")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(_IMPORT_SCHEMA)
        connection.execute(
            """
            INSERT INTO paper (
                source_paper_id,pmid,pmcid,doi,title,source_type,source_url,
                retrieval_date,full_text_status,screening_status,import_status
            ) VALUES ('P-001','123','PMC123','10.1000/test','Evidence paper','json',
                      'https://example.org/source','2026-08-07','open_full_text',
                      'include','ready_with_missing_fields')
            """
        )
        connection.execute(
            """
            INSERT INTO paper (
                source_paper_id,title,source_type,retrieval_date,full_text_status,
                screening_status,import_status
            ) VALUES ('P-002','Screening paper','manifest','2026-08-07',
                      'abstract_only','exclude','screening_only')
            """
        )
        connection.execute(
            """
            INSERT INTO formulation (
                paper_id,formulation_name,chemical_formulation_total,
                lnp_molar_ratio,composition_basis
            ) VALUES (1,'LNP-A','ION-DSPC-CHOL-PEG','50:10:38.5:1.5','molar_ratio')
            """
        )
        connection.execute(
            "INSERT INTO formulation (paper_id,formulation_name) VALUES (1,'LNP-B')"
        )
        component_ids: dict[str, int] = {}
        for role, name, position in (
            ("ionizable_lipid", "ION", 1),
            ("helper_lipid", "DSPC", 2),
            ("cholesterol", "cholesterol", 3),
            ("peg_lipid", "PEG", 4),
            ("targeting_ligand", "antibody", 5),
        ):
            component_ids[role] = int(connection.execute(
                """
                INSERT INTO chemical_component (
                    formulation_id,component_name_reported,component_role,
                    component_review_status,composition_position
                ) VALUES (1,?,?, 'automatically_normalized',?)
                """,
                (name, role, position),
            ).lastrowid)
        connection.execute(
            """
            INSERT INTO chemical_component (
                formulation_id,component_name_reported,component_role,
                component_review_status,composition_position
            ) VALUES (2,'ION-2','ionizable_lipid','automatically_normalized',1)
            """
        )
        arm_one = int(connection.execute(
            """
            INSERT INTO experiment (
                paper_id,formulation_id,cell_type,tissue_or_organ,species,
                disease_model,in_vitro_in_vivo,payload_type,payload_name,
                dose,dose_unit,route,timepoint,timepoint_unit,assay
            ) VALUES (1,1,'hepatocyte','liver','Mus musculus','healthy',
                      'in_vivo','mRNA','Luc mRNA',1.5,'mg/kg','intravenous',
                      24,'hours','luminescence')
            """
        ).lastrowid)
        arm_two = int(connection.execute(
            """
            INSERT INTO experiment (
                paper_id,formulation_id,cell_type,species,in_vitro_in_vivo,
                payload_type,payload_name,dose,dose_unit
            ) VALUES (1,1,'kupffer_cell','Mus musculus','in_vivo','mRNA',
                      'Luc mRNA',2.0,'mg/kg')
            """
        ).lastrowid)
        outcome_id = int(connection.execute(
            """
            INSERT INTO outcome (
                experiment_id,endpoint_family,endpoint_name,outcome_value,
                outcome_unit,normalization_basis,value_status
            ) VALUES (?, 'functional_expression','Luciferase expression',42.0,
                      'RLU','per mg protein','reported')
            """,
            (arm_one,),
        ).lastrowid)

        def evidence(field: str, text: str, *, experiment_id: int | None = None,
                     outcome: int | None = None) -> int:
            return int(connection.execute(
                """
                INSERT INTO evidence (
                    paper_id,experiment_id,outcome_id,field_name,evidence_text,
                    evidence_location_type,section_name,extraction_method,
                    extraction_confidence,evidence_review_status
                ) VALUES (1,?,?,?,?, 'methods','Methods','text_extraction',
                          'high','unreviewed')
                """,
                (experiment_id, outcome, field, text),
            ).lastrowid)

        formulation_evidence = evidence("formulation_name", "LNP-A evidence")
        helper_evidence = evidence("component_name_reported", "DSPC evidence")
        dose_evidence = evidence("dose", "Dose evidence", experiment_id=arm_one)
        outcome_evidence = evidence(
            "outcome_value", "Outcome evidence", experiment_id=arm_one,
            outcome=outcome_id,
        )

        def field_link(entity_type: str, entity_id: int, field: str, evidence_id: int,
                       key: str) -> None:
            content = json.dumps({"key": key}, sort_keys=True)
            connection.execute(
                """
                INSERT INTO import_field_evidence (
                    paper_id,entity_type,entity_id,field_name,evidence_id,
                    verification_status,notes,natural_key,content_sha256,content_json
                ) VALUES (1,?,?,?,?, 'automatically_validated','fixture',?,?,?)
                """,
                (
                    entity_type, entity_id, field, evidence_id, key,
                    hashlib.sha256(content.encode()).hexdigest(), content,
                ),
            )

        field_link("formulation", 1, "formulation_name", formulation_evidence, "form-name")
        field_link("component", component_ids["helper_lipid"], "component_name_reported", helper_evidence, "helper")
        field_link("arm", arm_one, "dose", dose_evidence, "dose")
        field_link("outcome", outcome_id, "outcome_value", outcome_evidence, "outcome")

        for arm_id, missing, status, nn, comet in (
            (arm_one, [], "automatically_validated", 1, 0),
            (arm_two, ["timepoint"], "automatically_validated", 0, 0),
        ):
            connection.execute(
                """
                INSERT INTO arm_assessment (
                    experiment_id,completeness_status,missing_fields_json,
                    verification_status,nearest_neighbor_eligible,comet_eligible,
                    updated_at
                ) VALUES (?,? ,?,?,?,?,'2026-08-07T00:00:00Z')
                """,
                (
                    arm_id, "complete" if not missing else "incomplete",
                    json.dumps(missing), status, nn, comet,
                ),
            )
            for profile, eligible, reasons in (
                ("nearest_neighbor", nn, [] if nn else missing),
                ("comet", comet, ["manually_verified"] if not comet else []),
            ):
                connection.execute(
                    """
                    INSERT INTO eligibility_result (
                        experiment_id,profile,eligible,reasons_json,rules_version,evaluated_at
                    ) VALUES (?,?,?,?, 'working-evidence-v2','2026-08-07T00:00:00Z')
                    """,
                    (arm_id, profile, eligible, json.dumps(reasons)),
                )
        review_content = json.dumps({"reason": "missing_timepoint"})
        connection.execute(
            """
            INSERT INTO import_review (
                paper_id,natural_key,arm_id,reason_code,review_status,review_tag,
                field_name,notes,evidence_ids_json,content_sha256
            ) VALUES (1,'missing-timepoint',?,'missing_timepoint','incomplete',
                      'Needs automatic resolution','timepoint','No timepoint linked','[]',?)
            """,
            (arm_two, hashlib.sha256(review_content.encode()).hexdigest()),
        )
        connection.execute(
            """
            INSERT INTO source_artifact (
                paper_id,logical_path,sha256,role,schema_family,validation_status,
                contributes_facts,contributes_evidence
            ) VALUES (1,? ,?,'full_text','html','validated',1,1)
            """,
            (str(local_html), hashlib.sha256(local_html.read_bytes()).hexdigest()),
        )
        connection.commit()
    return database


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_browser_service_preserves_formulation_grain_and_evidence(
    monkeypatch: pytest.MonkeyPatch, evidence_browser_database: Path,
) -> None:
    from src.ui import evidence_browser_service as service

    monkeypatch.setattr(service, "browser_database_path", lambda: evidence_browser_database)
    before = _hash(evidence_browser_database)
    papers = service.list_browser_papers()
    view = service.load_paper_browser(papers[0].paper_id)
    after = _hash(evidence_browser_database)

    assert service.FORMULATION_COLUMNS == (
        "lnp_name", "chemical_formulation_total", "lnp_molar_ratio",
        "ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid", "others",
    )
    assert [paper.source_paper_id for paper in papers] == ["P-001", "P-002"]
    assert len(view.formulations) == 2
    assert len(view.formulations[0].arms) == 2
    assert view.formulations[0].cells["helper_lipid"].display_value == "DSPC"
    assert view.formulations[1].cells["lnp_molar_ratio"].display_value == "NA"
    assert view.formulations[0].cells["helper_lipid"].evidence[0].text == "DSPC evidence"
    assert view.formulations[0].arms[0].fields["dose"].evidence[0].text == "Dose evidence"
    assert view.formulations[0].arms[0].outcomes[0].fields["outcome_value"].evidence[0].text == "Outcome evidence"
    assert view.formulations[0].arms[1].issues[0].reason_code == "missing_timepoint"
    assert view.paper.links["DOI / publisher"] == "https://doi.org/10.1000/test"
    assert before == after


def test_browser_service_keeps_screening_only_paper_visible_and_empty(
    monkeypatch: pytest.MonkeyPatch, evidence_browser_database: Path,
) -> None:
    from src.ui import evidence_browser_service as service

    monkeypatch.setattr(service, "browser_database_path", lambda: evidence_browser_database)
    paper = service.list_browser_papers()[1]
    view = service.load_paper_browser(paper.paper_id)

    assert paper.import_status == "screening_only"
    assert view.formulations == ()
    assert view.counts.formulations == 0


def test_browser_service_rejects_unknown_paper_without_writing(
    monkeypatch: pytest.MonkeyPatch, evidence_browser_database: Path,
) -> None:
    from src.ui import evidence_browser_service as service

    monkeypatch.setattr(service, "browser_database_path", lambda: evidence_browser_database)
    before = _hash(evidence_browser_database)
    with pytest.raises(KeyError, match="unknown paper"):
        service.load_paper_browser(999)
    assert _hash(evidence_browser_database) == before


def test_default_browser_paper_skips_screening_only_empty_paper() -> None:
    from src.ui import evidence_browser_service as service

    empty_counts = service.BrowserCounts(0, 0, 0, 0, 0, 0)
    rich_counts = service.BrowserCounts(1, 4, 2, 3, 8, 0)
    empty = service.BrowserPaper(
        1, "GP-001", "Screening only", "unknown", "screening_only", {}, empty_counts
    )
    rich = service.BrowserPaper(
        2, "GP-002", "Extracted", "available", "imported", {}, rich_counts
    )

    assert service.default_browser_paper_id((empty, rich)) == 2


def test_combined_table_has_one_row_per_arm_and_stacked_outcomes(
    monkeypatch: pytest.MonkeyPatch, evidence_browser_database: Path,
) -> None:
    from src.ui import evidence_browser_service as service

    with sqlite3.connect(evidence_browser_database) as connection:
        connection.execute(
            """
            INSERT INTO outcome (
                experiment_id,endpoint_family,endpoint_name,qualitative_outcome,
                value_status
            ) VALUES (1,'toxicity','Tolerability','No toxicity observed','reported')
            """
        )
        connection.commit()
    monkeypatch.setattr(service, "browser_database_path", lambda: evidence_browser_database)

    rows = service.list_combined_arm_rows()

    assert len(rows) == 2
    arm = next(row for row in rows if len(row.outcomes) == 2)
    assert arm.outcomes[0].outcome_id != arm.outcomes[1].outcome_id
    assert "Luciferase expression" in arm.outcomes_display
    assert "Tolerability" in arm.outcomes_display
    assert tuple(arm.formulation) == service.FORMULATION_COLUMNS
    assert arm.formulation["lnp_molar_ratio"].display_value == "50:10:38.5:1.5"


def test_combined_table_keeps_missing_ratio_visible_with_comet_blocker(
    monkeypatch: pytest.MonkeyPatch, evidence_browser_database: Path,
) -> None:
    from src.ui import evidence_browser_service as service

    with sqlite3.connect(evidence_browser_database) as connection:
        connection.execute(
            "UPDATE experiment SET formulation_id=2 WHERE experiment_id=2"
        )
        connection.execute(
            "UPDATE eligibility_result SET reasons_json=? "
            "WHERE experiment_id=2 AND profile='comet'",
            (json.dumps(["lnp_molar_ratio"]),),
        )
        connection.commit()
    monkeypatch.setattr(service, "browser_database_path", lambda: evidence_browser_database)

    row = next(row for row in service.list_combined_arm_rows() if row.experiment_id == 2)
    assert row.formulation["lnp_molar_ratio"].display_value == "NA"
    assert "lnp_molar_ratio" in row.comet_blockers
