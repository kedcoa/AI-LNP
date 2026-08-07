from __future__ import annotations

import sqlite3

from src.database.deduplicate_science import deduplicate_science
from src.init_db import initialize_database


def test_component_deduplication_keeps_source_occurrence_count(tmp_path) -> None:
    database = initialize_database(tmp_path / "dedup.db")
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys=ON")
    paper_id = connection.execute(
        "INSERT INTO paper (source_paper_id,title,source_type,retrieval_date,import_status) "
        "VALUES ('P1','P1','test','2026-08-07','needs_review')"
    ).lastrowid
    formulation_id = connection.execute(
        "INSERT INTO formulation (paper_id,formulation_name) VALUES (?, 'LNP')",
        (paper_id,),
    ).lastrowid
    for _ in range(3):
        connection.execute(
            "INSERT INTO chemical_component "
            "(formulation_id,component_name_reported,component_role,amount_value,amount_unit) "
            "VALUES (?, 'DSPC', 'helper_lipid', 10, 'mol%')",
            (formulation_id,),
        )
    connection.commit()

    result = deduplicate_science(connection)

    assert result.canonical_component_count == 1
    assert result.source_occurrence_count == 3
    assert connection.execute(
        "SELECT count(*) FROM chemical_component"
    ).fetchone() == (1,)


def test_same_administration_cell_subgroups_merge_into_one_arm(tmp_path) -> None:
    database = initialize_database(tmp_path / "arm-dedup.db")
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys=ON")
    paper_id = connection.execute(
        "INSERT INTO paper (source_paper_id,title,source_type,retrieval_date,import_status) "
        "VALUES ('NP-002','NP-002','test','2026-08-07','needs_review')"
    ).lastrowid
    formulation_id = connection.execute(
        "INSERT INTO formulation (paper_id,formulation_name) VALUES (?, 'MC3 LNP')",
        (paper_id,),
    ).lastrowid
    arm_ids = []
    for cell_type in ("hepatocyte", "kupffer_cell", "lsec"):
        arm_ids.append(int(connection.execute(
            """INSERT INTO experiment (
                   paper_id,formulation_id,cell_type,species,disease_model,
                   in_vitro_in_vivo,payload_type,payload_name,dose,dose_unit,
                   route,timepoint,timepoint_unit
               ) VALUES (?,? ,?,'mouse','Ai14 reporter mice','in_vivo','mRNA',
                         'Cre mRNA',1.0,'mg/kg','intravenous',24,'hours')""",
            (paper_id, formulation_id, cell_type),
        ).lastrowid))
    for index, experiment_id in enumerate(arm_ids):
        outcome_id = connection.execute(
            """INSERT INTO outcome (
                   experiment_id,endpoint_family,endpoint_name,
                   qualitative_outcome,value_status
               ) VALUES (?,'functional_expression',?,?,'qualitative_only')""",
            (experiment_id, f"cell outcome {index}", f"result for cell {index}"),
        ).lastrowid
        connection.execute(
            """INSERT INTO evidence (
                   paper_id,experiment_id,outcome_id,field_name,evidence_text,
                   evidence_location_type,extraction_method,
                   extraction_confidence,evidence_review_status
               ) VALUES (?,?,?,'qualitative_outcome',?,'results','text_extraction',
                         'high','automatically_validated')""",
            (paper_id, experiment_id, outcome_id, f"evidence {index}"),
        )
    connection.commit()

    result = deduplicate_science(connection)

    assert result.source_arm_count == 3
    assert result.canonical_arm_count == 1
    assert result.duplicate_arms_removed == 2
    assert connection.execute("SELECT count(*) FROM experiment").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM outcome").fetchone() == (3,)
    assert connection.execute(
        "SELECT count(DISTINCT experiment_id) FROM outcome"
    ).fetchone() == (1,)
    observed = connection.execute(
        "SELECT observed_transfected_cell FROM experiment"
    ).fetchone()[0]
    assert observed == "hepatocyte; kupffer_cell; lsec"
    connection.close()
