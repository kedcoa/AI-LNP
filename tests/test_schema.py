from pathlib import Path
import sqlite3
import sys 
import pytest

from src.init_db import initialize_database


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    """Create an isolated database for each test."""

    test_database = tmp_path / "test_lnp_evidence.db"
    initialize_database(test_database)
    return test_database

def test_complete_synthetic_record(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        paper_id = connection.execute(
            """
            INSERT INTO paper (
                title,
                source_type,
                retrieval_date,
                full_text_status,
                screening_status,
                screening_reason
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Synthetic schema test paper",
                "synthetic_test",
                "2026-07-21",
                "abstract_only",
                "include",
                "Synthetic record used only for automated testing.",
            ),
        ).lastrowid

        formulation_id = connection.execute(
            """
            INSERT INTO formulation (
                paper_id,
                formulation_name,
                composition_raw,
                composition_basis,
                np_ratio,
                formulation_notes,
                formulation_review_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                "Synthetic-LNP-01",
                "Component A:B:C:D = 50:10:38.5:1.5",
                "mol%",
                6.0,
                "Synthetic record; not scientific evidence.",
                "manually_verified",
            ),
        ).lastrowid

        components = [
            (
                formulation_id,
                "Component A",
                "Component A",
                "ionizable_lipid",
                50.0,
                "mol%",
                "unreviewed",
            ),
            (
                formulation_id,
                "Component B",
                "Component B",
                "helper_lipid",
                10.0,
                "mol%",
                "unreviewed",
            ),
            (
                formulation_id,
                "Component C",
                "Component C",
                "cholesterol",
                38.5,
                "mol%",
                "unreviewed",
            ),
            (
                formulation_id,
                "Component D",
                "Component D",
                "peg_lipid",
                1.5,
                "mol%",
                "unreviewed",
            ),
        ]

        connection.executemany(
            """
            INSERT INTO chemical_component (
                formulation_id,
                component_name_reported,
                component_name_normalized,
                component_role,
                molar_percentage,
                percentage_unit,
                component_review_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            components,
        )

        experiment_id = connection.execute(
            """
            INSERT INTO experiment (
                paper_id,
                formulation_id,
                cell_type,
                cell_source,
                species,
                in_vitro_in_vivo,
                payload_type,
                reporter,
                dose,
                dose_unit,
                timepoint,
                timepoint_unit,
                assay,
                comparator_type,
                comparator_description
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                formulation_id,
                "hepatocyte",
                "synthetic cell model",
                "human",
                "in_vitro",
                "mRNA",
                "luciferase",
                1.0,
                "microgram/mL",
                24.0,
                "hours",
                "synthetic expression assay",
                "untreated_control",
                "Untreated cells",
            ),
        ).lastrowid

        efficacy_outcome_id = connection.execute(
            """
            INSERT INTO outcome (
                experiment_id,
                endpoint_family,
                endpoint_name,
                outcome_value,
                outcome_unit,
                normalization_basis,
                uncertainty_value,
                uncertainty_type,
                value_status,
                outcome_notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                "functional_expression",
                "synthetic expression measurement",
                100.0,
                "arbitrary units",
                "untreated cells",
                5.0,
                "sd",
                "reported",
                "Synthetic test value; not reported literature.",
            ),
        ).lastrowid

        viability_outcome_id = connection.execute(
            """
            INSERT INTO outcome (
                experiment_id,
                endpoint_family,
                endpoint_name,
                outcome_value,
                outcome_unit,
                normalization_basis,
                uncertainty_value,
                uncertainty_type,
                value_status,
                outcome_notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                "viability",
                "synthetic viability measurement",
                90.0,
                "% of untreated control",
                "untreated cells",
                3.0,
                "sd",
                "reported",
                "Synthetic test value; not reported literature.",
            ),
        ).lastrowid

        evidence_rows = [
            (
                paper_id,
                experiment_id,
                efficacy_outcome_id,
                "outcome_value",
                "Synthetic evidence for the expression outcome.",
                "results",
                "manual",
                "high",
                "manually_verified",
            ),
            (
                paper_id,
                experiment_id,
                viability_outcome_id,
                "outcome_value",
                "Synthetic evidence for the viability outcome.",
                "results",
                "manual",
                "high",
                "manually_verified",
            ),
        ]

        connection.executemany(
            """
            INSERT INTO evidence (
                paper_id,
                experiment_id,
                outcome_id,
                field_name,
                evidence_text,
                evidence_location_type,
                extraction_method,
                extraction_confidence,
                evidence_review_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            evidence_rows,
        )

        connection.commit()

        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "paper",
                "formulation",
                "chemical_component",
                "experiment",
                "outcome",
                "evidence",
            )
        }

        assert counts == {
            "paper": 1,
            "formulation": 1,
            "chemical_component": 4,
            "experiment": 1,
            "outcome": 2,
            "evidence": 2,
        }

                # Confirm that SQLite created every expected identifier.
        assert paper_id is not None
        assert formulation_id is not None
        assert experiment_id is not None
        assert efficacy_outcome_id is not None
        assert viability_outcome_id is not None

        # Efficacy and viability must be separate outcome records.
        assert efficacy_outcome_id != viability_outcome_id

        # Both outcomes must belong to the same experiment.
        linked_outcomes = connection.execute(
            """
            SELECT outcome_id, experiment_id, endpoint_family
            FROM outcome
            ORDER BY outcome_id
            """
        ).fetchall()

        assert linked_outcomes == [
            (
                efficacy_outcome_id,
                experiment_id,
                "functional_expression",
            ),
            (
                viability_outcome_id,
                experiment_id,
                "viability",
            ),
        ]

        # Each outcome must have its own supporting evidence record.
        evidence_links = connection.execute(
            """
            SELECT outcome_id
            FROM evidence
            ORDER BY outcome_id
            """
        ).fetchall()

        assert evidence_links == [
            (efficacy_outcome_id,),
            (viability_outcome_id,),
        ]

        # The complete synthetic formulation should total 100 mol%.
        composition_total = connection.execute(
            """
            SELECT SUM(molar_percentage)
            FROM chemical_component
            WHERE formulation_id = ?
            """,
            (formulation_id,),
        ).fetchone()[0]

        assert composition_total == pytest.approx(100.0)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from init_db import initialize_database


EXPECTED_TABLES = {
    "paper",
    "formulation",
    "chemical_component",
    "experiment",
    "outcome",
    "evidence",
    "schema_migration",
    "record_source",
    "missing_field",
    "field_verification",
    "arm_assessment",
    "review_revision",
    "screening_event",
    "eligibility_result",
    "source_artifact",
    "source_fact",
    "source_fact_evidence",
    "fact_projection",
}


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "test_lnp_evidence.db"
    initialize_database(path)
    return path


def test_expected_tables_exist(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        actual_tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

    assert EXPECTED_TABLES.issubset(actual_tables)


def test_working_database_columns_are_available(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        paper_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(paper)")
        }
        assessment_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(arm_assessment)")
        }
        formulation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(formulation)")
        }
        component_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(chemical_component)")
        }

    assert {"source_paper_id", "import_status"} <= paper_columns
    assert {
        "completeness_status",
        "missing_fields_json",
        "verification_status",
        "nearest_neighbor_eligible",
        "comet_eligible",
        "quarantine_reason",
    } <= assessment_columns
    assert {"chemical_formulation_total", "lnp_molar_ratio"} <= formulation_columns
    assert {
        "amount_value",
        "amount_unit",
        "amount_raw",
        "composition_position",
    } <= component_columns


def test_experiment_has_compact_contract_columns(database_path: Path) -> None:
    expected = {
        "tissue_or_organ",
        "disease_model",
        "payload_encoded_product",
        "payload_molecular_target",
    }
    with sqlite3.connect(database_path) as connection:
        actual = {
            row[1]
            for row in connection.execute("PRAGMA table_info(experiment)")
        }
    assert expected.issubset(actual)


def test_existing_database_receives_additive_experiment_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy_lnp_evidence.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE experiment (
                experiment_id INTEGER PRIMARY KEY,
                paper_id INTEGER NOT NULL,
                formulation_id INTEGER NOT NULL,
                cell_type TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO experiment (
                experiment_id, paper_id, formulation_id, cell_type
            )
            VALUES (1, 1, 1, 'hepatocyte')
            """
        )

    initialize_database(path)

    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(experiment)")
        }
        retained = connection.execute(
            "SELECT experiment_id, cell_type FROM experiment"
        ).fetchall()

    assert {
        "tissue_or_organ",
        "disease_model",
        "payload_encoded_product",
        "payload_molecular_target",
    }.issubset(columns)
    assert retained == [(1, "hepatocyte")]


def test_compact_contract_fields_round_trip_through_experiment_table(
    database_path: Path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        paper_id = connection.execute(
            """
            INSERT INTO paper (
                title, source_type, retrieval_date, screening_status
            )
            VALUES ('Migration test', 'synthetic_test', '2026-07-27', 'include')
            """
        ).lastrowid
        formulation_id = connection.execute(
            """
            INSERT INTO formulation (paper_id, formulation_name)
            VALUES (?, 'LNP-1')
            """,
            (paper_id,),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO experiment (
                paper_id,
                formulation_id,
                cell_type,
                tissue_or_organ,
                disease_model,
                payload_encoded_product,
                payload_molecular_target
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                formulation_id,
                "hsc",
                "liver",
                "liver fibrosis",
                "FAP-CAR",
                "FAP",
            ),
        )
        stored = connection.execute(
            """
            SELECT
                tissue_or_organ,
                disease_model,
                payload_encoded_product,
                payload_molecular_target
            FROM experiment
            """
        ).fetchone()

    assert stored == ("liver", "liver fibrosis", "FAP-CAR", "FAP")


def test_foreign_keys_are_enforced(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO formulation (
                    paper_id,
                    formulation_name,
                    formulation_review_status
                )
                VALUES (?, ?, ?)
                """,
                (999999, "Invalid formulation", "unreviewed"),
            )


def test_invalid_cell_type_is_rejected(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        paper_id = connection.execute(
            """
            INSERT INTO paper (
                title,
                source_type,
                retrieval_date,
                screening_status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "Test paper",
                "test",
                "2026-07-21",
                "include",
            ),
        ).lastrowid

        formulation_id = connection.execute(
            """
            INSERT INTO formulation (
                paper_id,
                formulation_name,
                formulation_review_status
            )
            VALUES (?, ?, ?)
            """,
            (
                paper_id,
                "Test formulation",
                "unreviewed",
            ),
        ).lastrowid

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO experiment (
                    paper_id,
                    formulation_id,
                    cell_type
                )
                VALUES (?, ?, ?)
                """,
                (
                    paper_id,
                    formulation_id,
                    "brain_cell",
                ),
            )


def test_viability_uses_outcome_table(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        outcome_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(outcome)"
            )
        }

    assert "outcome_value" in outcome_columns
    assert "outcome_unit" in outcome_columns
    assert "viability_value" not in outcome_columns
    assert "viability_unit" not in outcome_columns


def test_removed_fields_are_absent(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        component_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(chemical_component)"
            )
        }

        outcome_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(outcome)"
            )
        }

    assert "canonical_smiles" not in component_columns
    assert "zeta_potential" not in component_columns
    assert "outcome_direction" not in outcome_columns


def test_numeric_or_qualitative_outcome_is_required(
    database_path: Path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        paper_id = connection.execute(
            """
            INSERT INTO paper (
                title,
                source_type,
                retrieval_date,
                screening_status
            )
            VALUES (?, ?, ?, ?)
            """,
            ("Test paper", "test", "2026-07-21", "include"),
        ).lastrowid

        formulation_id = connection.execute(
            """
            INSERT INTO formulation (
                paper_id,
                formulation_name,
                formulation_review_status
            )
            VALUES (?, ?, ?)
            """,
            (paper_id, "Test formulation", "unreviewed"),
        ).lastrowid

        experiment_id = connection.execute(
            """
            INSERT INTO experiment (
                paper_id,
                formulation_id,
                cell_type
            )
            VALUES (?, ?, ?)
            """,
            (paper_id, formulation_id, "hepatocyte"),
        ).lastrowid

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO outcome (
                    experiment_id,
                    endpoint_family,
                    endpoint_name,
                    value_status
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    "viability",
                    "cell viability",
                    "reported",
                ),
            )


from validators import validate_complete_percentage_composition


def test_complete_percentage_composition_passes() -> None:
    assert validate_complete_percentage_composition(
        [50.0, 10.0, 38.5, 1.5],
        composition_basis="mol%",
        composition_is_complete=True,
    )


def test_invalid_complete_percentage_composition_fails() -> None:
    assert not validate_complete_percentage_composition(
        [50.0, 10.0, 20.0, 1.5],
        composition_basis="mol%",
        composition_is_complete=True,
    )


def test_incomplete_composition_is_not_forced_to_total_100() -> None:
    assert validate_complete_percentage_composition(
        [50.0, None],
        composition_basis="mol%",
        composition_is_complete=False,
    )
