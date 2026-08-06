from __future__ import annotations

import importlib
import json
import math
from pathlib import Path
import sqlite3

import pytest

from src.database.status import evaluate_arm_status, evaluate_eligibility
from src.init_db import initialize_database


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "database"
    / "import_bundle"
    / "valid_bundle.json"
)


def _contracts():
    return importlib.import_module("src.database.import_contracts")


def _load_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _load_bundle(payload: dict | None = None):
    contracts = _contracts()
    return contracts.ImportBundle.from_dict(payload or _load_payload())


def test_valid_normalized_bundle_loads_from_plain_data() -> None:
    bundle = _load_bundle()

    assert bundle.paper.source_paper_id == "GP-002"
    assert bundle.outcomes[0].outcome_value == 12.0
    assert bundle.field_evidence_links[0].evidence_ids == ("E-1",)


def test_contract_rejects_cross_paper_records() -> None:
    payload = _load_payload()
    payload["outcomes"][0]["paper_id"] = "GP-999"

    with pytest.raises(ValueError, match="cross-paper"):
        _load_bundle(payload)


def test_contract_rejects_unknown_relationship_and_evidence_ids() -> None:
    payload = _load_payload()
    payload["components"][0]["formulation_id"] = "F-unknown"

    with pytest.raises(ValueError, match="unknown formulation"):
        _load_bundle(payload)

    payload = _load_payload()
    payload["field_evidence_links"][0]["evidence_ids"] = ["E-unknown"]

    with pytest.raises(ValueError, match="unknown evidence"):
        _load_bundle(payload)


@pytest.mark.parametrize("sha256", ["", "abc", "g" * 64])
def test_contract_rejects_missing_or_malformed_source_hash(sha256: str) -> None:
    payload = _load_payload()
    payload["artifacts"][0]["sha256"] = sha256

    with pytest.raises(ValueError, match="SHA-256"):
        _load_bundle(payload)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("formulations", "np_ratio", -1),
        ("components", "molar_percentage", 101),
        ("arms", "dose", math.inf),
        ("arms", "timepoint", "tomorrow"),
        ("outcomes", "outcome_value", math.nan),
        ("outcomes", "uncertainty_value", -0.1),
    ],
)
def test_contract_rejects_malformed_scientific_numeric_values(
    section: str,
    field: str,
    value: object,
) -> None:
    payload = _load_payload()
    payload[section][0][field] = value

    with pytest.raises(ValueError, match=field):
        _load_bundle(payload)


@pytest.mark.parametrize(
    "source_kind",
    [
        "raw_provider_response",
        "provider_response",
        "model_output",
        "llm_response",
        "codex_generated",
        "unknown_blob",
    ],
)
def test_contract_rejects_unsupported_evidence_source_kind(
    source_kind: str,
) -> None:
    payload = _load_payload()
    payload["artifacts"][0]["source_kind"] = source_kind

    with pytest.raises(ValueError, match="unsupported source kind"):
        _load_bundle(payload)


def test_contract_rejects_scientific_value_without_evidence_link() -> None:
    payload = _load_payload()
    payload["field_evidence_links"] = [
        row
        for row in payload["field_evidence_links"]
        if not (
            row["entity_type"] == "outcome"
            and row["field_name"] == "outcome_value"
        )
    ]

    with pytest.raises(ValueError, match="unsupported outcome field"):
        _load_bundle(payload)


@pytest.mark.parametrize(
    ("entity_type", "field_name"),
    [
        ("formulation", "composition_raw"),
        ("component", "molar_percentage"),
        ("arm", "dose"),
        ("outcome", "endpoint_name"),
    ],
)
def test_contract_requires_evidence_for_each_populated_scientific_field(
    entity_type: str,
    field_name: str,
) -> None:
    payload = _load_payload()
    payload["field_evidence_links"] = [
        row
        for row in payload["field_evidence_links"]
        if not (
            row["entity_type"] == entity_type
            and row["field_name"] == field_name
        )
    ]

    with pytest.raises(ValueError, match=f"unsupported {entity_type} field"):
        _load_bundle(payload)


def test_contract_rejects_outcome_evidence_without_arm_scope() -> None:
    payload = _load_payload()
    payload["evidence"][0].pop("arm_id")

    with pytest.raises(ValueError, match="outcome evidence requires arm"):
        _load_bundle(payload)


def test_contract_rejects_review_state_that_leaves_arm_eligible() -> None:
    payload = _load_payload()
    payload["reviews"] = [
        {
            "record_id": "R-1",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "arm_id": "A-1",
            "evidence_ids": ["E-1"],
            "reason_code": "outcome_link_unclear",
            "status": "quarantined",
        }
    ]

    with pytest.raises(ValueError, match="review state contradicts arm"):
        _load_bundle(payload)


def test_contract_rejects_targeted_blocked_review_for_eligible_arm() -> None:
    payload = _load_payload()
    payload["reviews"] = [
        {
            "record_id": "R-1",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "arm_id": "A-1",
            "evidence_ids": ["E-1"],
            "reason_code": "source_file_unavailable",
            "status": "blocked",
        }
    ]

    with pytest.raises(ValueError, match="blocked review targets eligible arm"):
        _load_bundle(payload)


def test_contract_requires_durable_quarantine_for_targeted_blocked_review() -> None:
    payload = _load_payload()
    payload["arms"][0].update(
        nearest_neighbor_eligible=False,
        comet_eligible=False,
    )
    payload["reviews"] = [
        {
            "record_id": "R-1",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "arm_id": "A-1",
            "evidence_ids": ["E-1"],
            "reason_code": "source_file_unavailable",
            "status": "blocked",
        }
    ]

    with pytest.raises(ValueError, match="blocked review requires quarantined arm"):
        _load_bundle(payload)


def test_screening_manifest_cannot_support_scientific_evidence() -> None:
    payload = _load_payload()
    payload["artifacts"][0]["source_kind"] = "screening_manifest"

    with pytest.raises(ValueError, match="unsupported evidence source kind"):
        _load_bundle(payload)


def test_contract_requires_accepted_evidence_for_eligible_arm() -> None:
    payload = _load_payload()
    payload["evidence"][0]["verification_status"] = "unreviewed"

    with pytest.raises(ValueError, match="eligible arm requires accepted evidence"):
        _load_bundle(payload)


def test_contract_requires_accepted_field_link_for_eligible_arm() -> None:
    payload = _load_payload()
    for link in payload["field_evidence_links"]:
        if link["entity_type"] == "arm" and link["field_name"] == "dose":
            link["verification_status"] = "ambiguous"

    with pytest.raises(ValueError, match="eligible arm requires accepted field evidence"):
        _load_bundle(payload)


def test_contract_requires_accepted_outcome_evidence_for_eligible_arm() -> None:
    payload = _load_payload()
    payload["outcomes"] = []
    payload["evidence"][0]["outcome_id"] = None
    payload["evidence"][0]["field_name"] = "dose"
    payload["field_evidence_links"] = [
        link
        for link in payload["field_evidence_links"]
        if link["entity_type"] != "outcome"
    ]

    with pytest.raises(
        ValueError,
        match="eligible arm requires accepted outcome evidence",
    ):
        _load_bundle(payload)


def test_contract_rejects_automatic_evidence_for_persisted_eligibility() -> None:
    payload = _load_payload()
    payload["evidence"][0]["verification_status"] = "automatically_validated"
    payload["arms"][0].update(
        verification_status="automatically_validated",
        comet_eligible=False,
    )
    for link in payload["field_evidence_links"]:
        link["verification_status"] = "automatically_validated"

    with pytest.raises(ValueError, match="core schema cannot persist accepted automatic evidence"):
        _load_bundle(payload)


def test_quarantine_review_rejects_unscoped_evidence() -> None:
    payload = _load_payload()
    payload["arms"][0].update(
        completeness_status="quarantined",
        verification_status="rejected",
        nearest_neighbor_eligible=False,
        comet_eligible=False,
        quarantine_reason="Relationship unresolved.",
    )
    payload["reviews"] = [
        {
            "record_id": "R-1",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "evidence_ids": ["E-1"],
            "reason_code": "outcome_link_unclear",
            "status": "quarantined",
        }
    ]

    with pytest.raises(ValueError, match="quarantined review requires arm or outcome scope"):
        _load_bundle(payload)


def test_outcome_review_rejects_arm_only_evidence() -> None:
    payload = _load_payload()
    payload["arms"][0].update(
        completeness_status="quarantined",
        verification_status="rejected",
        nearest_neighbor_eligible=False,
        comet_eligible=False,
        quarantine_reason="Outcome relationship unresolved.",
    )
    payload["evidence"][0]["outcome_id"] = None
    payload["reviews"] = [
        {
            "record_id": "R-1",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "outcome_id": "O-1",
            "evidence_ids": ["E-1"],
            "reason_code": "outcome_link_unclear",
            "status": "quarantined",
        }
    ]

    with pytest.raises(ValueError, match="review evidence is outside outcome scope"):
        _load_bundle(payload)


def test_contract_rejects_unsafe_eligibility_state() -> None:
    payload = _load_payload()
    payload["arms"][0]["completeness_status"] = "conflict"

    with pytest.raises(ValueError, match="unsafe eligibility"):
        _load_bundle(payload)

    payload = _load_payload()
    payload["arms"][0]["verification_status"] = "automatically_validated"

    with pytest.raises(ValueError, match="COMET eligibility"):
        _load_bundle(payload)


def test_contract_rejects_scientific_rows_for_screening_only_paper() -> None:
    payload = _load_payload()
    payload["paper"]["screening_status"] = "exclude"
    payload["paper"]["import_status"] = "screening_only"

    with pytest.raises(ValueError, match="screening-only"):
        _load_bundle(payload)


def test_contract_requires_review_record_for_each_unsafe_arm() -> None:
    payload = _load_payload()
    payload["arms"][0].update(
        completeness_status="incomplete",
        nearest_neighbor_eligible=False,
        comet_eligible=False,
    )

    with pytest.raises(ValueError, match="review record"):
        _load_bundle(payload)


def _connection(tmp_path: Path) -> sqlite3.Connection:
    database_path = tmp_path / "import-test.db"
    initialize_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _import_bundle(connection: sqlite3.Connection, bundle):
    module = importlib.import_module("src.database.import_bundle")
    return module.import_bundle(connection, bundle)


def test_import_is_idempotent_and_preserves_evidence_provenance(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    bundle = _load_bundle()
    try:
        first = _import_bundle(connection, bundle)
        second = _import_bundle(connection, bundle)

        assert first.inserted == 6
        assert first.unchanged == 0
        assert second.inserted == 0
        assert second.unchanged == 6
        assert connection.execute("SELECT COUNT(*) FROM paper").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM outcome").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone() == (1,)
        assert connection.execute(
            "SELECT evidence_text, evidence_location_type FROM evidence"
        ).fetchone() == ("Expression was 12 ng/mL.", "results")
        assert connection.execute(
            """
            SELECT artifact_path, artifact_sha256, pipeline_name, pipeline_version
            FROM record_source
            WHERE entity_type = 'evidence'
            """
        ).fetchone() == (
            "data/staging/GP-002/accepted_graph.json",
            "a" * 64,
            "fulltext-rag-evidence-graph",
            "v4",
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM import_field_evidence"
        ).fetchone() == (19,)
    finally:
        connection.close()


def test_import_rolls_back_the_whole_paper_on_late_failure(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    connection.execute(
        """
        CREATE TRIGGER reject_fixture_evidence
        BEFORE INSERT ON evidence
        BEGIN
            SELECT RAISE(ABORT, 'forced late import failure');
        END
        """
    )
    connection.commit()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="forced late"):
            _import_bundle(connection, _load_bundle())

        for table in (
            "paper",
            "formulation",
            "chemical_component",
            "experiment",
            "outcome",
            "evidence",
            "record_source",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone() == (0,)
    finally:
        connection.close()


def test_failed_paper_does_not_undo_previously_imported_paper(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    first_bundle = _load_bundle()
    second_payload = _load_payload()
    second_payload["paper"]["source_paper_id"] = "GP-004"
    for section in (
        "formulations",
        "components",
        "arms",
        "outcomes",
        "evidence",
        "field_evidence_links",
    ):
        for row in second_payload[section]:
            row["paper_id"] = "GP-004"
    second_payload["evidence"][0]["evidence_text"] = "Reject this paper."
    second_bundle = _load_bundle(second_payload)
    try:
        _import_bundle(connection, first_bundle)
        connection.execute(
            """
            CREATE TRIGGER reject_second_paper
            BEFORE INSERT ON evidence
            WHEN NEW.evidence_text = 'Reject this paper.'
            BEGIN
                SELECT RAISE(ABORT, 'second paper failed');
            END
            """
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="second paper failed"):
            _import_bundle(connection, second_bundle)

        assert connection.execute(
            "SELECT source_paper_id FROM paper ORDER BY source_paper_id"
        ).fetchall() == [("GP-002",)]
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone() == (1,)
    finally:
        connection.close()


def test_changed_content_with_same_natural_key_is_retained_as_conflict(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    changed = _load_payload()
    changed["outcomes"][0]["outcome_value"] = 13.0
    changed["evidence"][0]["evidence_text"] = "Expression was 13 ng/mL."
    try:
        _import_bundle(connection, _load_bundle())
        result = _import_bundle(connection, _load_bundle(changed))

        assert result.conflicts == 2
        assert result.review_tags == ("Conflicting outcome", "Needs human verification")
        assert connection.execute(
            "SELECT outcome_value FROM outcome ORDER BY outcome_id"
        ).fetchall() == [(12.0,), (13.0,)]
        assert connection.execute(
            "SELECT evidence_text FROM evidence ORDER BY evidence_id"
        ).fetchall() == [
            ("Expression was 12 ng/mL.",),
            ("Expression was 13 ng/mL.",),
        ]
        assert connection.execute(
            """
            SELECT completeness_status, verification_status,
                   nearest_neighbor_eligible, comet_eligible
            FROM arm_assessment
            """
        ).fetchone() == ("conflict", "conflict", 0, 0)

        repeated = _import_bundle(connection, _load_bundle(changed))
        assert repeated.inserted == 0
        assert repeated.unchanged == 6
        assert repeated.review_tags == (
            "Conflicting outcome",
            "Needs human verification",
        )
    finally:
        connection.close()


def test_changed_parent_identity_cascades_to_dependent_records(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    changed = _load_payload()
    changed["arms"][0]["dose"] = 2.0
    try:
        _import_bundle(connection, _load_bundle())
        result = _import_bundle(connection, _load_bundle(changed))

        assert result.conflicts == 3
        assert connection.execute(
            "SELECT experiment_id, dose FROM experiment ORDER BY experiment_id"
        ).fetchall() == [(1, 1.0), (2, 2.0)]
        assert connection.execute(
            "SELECT outcome_id, experiment_id FROM outcome ORDER BY outcome_id"
        ).fetchall() == [(1, 1), (2, 2)]
        assert connection.execute(
            """
            SELECT evidence_id, experiment_id, outcome_id
            FROM evidence ORDER BY evidence_id
            """
        ).fetchall() == [(1, 1, 1), (2, 2, 2)]
    finally:
        connection.close()


def test_evidence_only_conflict_survives_status_recalculation(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    changed = _load_payload()
    changed["evidence"][0]["evidence_text"] = "A conflicting excerpt."
    try:
        _import_bundle(connection, _load_bundle())
        _import_bundle(connection, _load_bundle(changed))
        experiment_id = connection.execute(
            "SELECT experiment_id FROM experiment"
        ).fetchone()[0]

        assert evaluate_arm_status(
            connection, experiment_id
        ).completeness_status == "conflict"
    finally:
        connection.close()


def test_automatic_evidence_mapping_is_explicit_and_ineligible(
    tmp_path: Path,
) -> None:
    payload = _load_payload()
    payload["evidence"][0]["verification_status"] = "automatically_validated"
    payload["arms"][0].update(
        verification_status="automatically_validated",
        nearest_neighbor_eligible=False,
        comet_eligible=False,
    )
    for link in payload["field_evidence_links"]:
        link["verification_status"] = "automatically_validated"
    connection = _connection(tmp_path)
    try:
        _import_bundle(connection, _load_bundle(payload))
        experiment_id = connection.execute(
            "SELECT experiment_id FROM experiment"
        ).fetchone()[0]

        assert connection.execute(
            "SELECT evidence_review_status, reviewer_notes FROM evidence"
        ).fetchone() == (
            "unreviewed",
            "Source verification status automatically_validated; "
            "stored as unreviewed because the core schema has no automatic state.",
        )
        assert evaluate_arm_status(
            connection, experiment_id
        ).verification_status == "automatically_validated"
        assert evaluate_eligibility(
            connection, experiment_id, "nearest_neighbor"
        ).eligible is False
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("notes", "A revised evidence-link interpretation."),
        ("verification_status", "automatically_validated"),
    ],
)
def test_changed_field_link_content_is_retained_as_conflict(
    tmp_path: Path,
    changed_field: str,
    changed_value: str,
) -> None:
    changed = _load_payload()
    for link in changed["field_evidence_links"]:
        if link["entity_type"] == "arm" and link["field_name"] == "dose":
            link[changed_field] = changed_value
    connection = _connection(tmp_path)
    try:
        _import_bundle(connection, _load_bundle())
        result = _import_bundle(connection, _load_bundle(changed))

        assert result.conflicts == 1
        assert connection.execute(
            """
            SELECT COUNT(*) FROM import_field_evidence
            WHERE entity_type = 'arm' AND field_name = 'dose'
            """
        ).fetchone() == (2,)
        assert connection.execute(
            """
            SELECT completeness_status, nearest_neighbor_eligible, comet_eligible
            FROM arm_assessment
            """
        ).fetchone() == ("conflict", 0, 0)
    finally:
        connection.close()


def _shift_surrogate_ids(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        INSERT INTO paper (
            paper_id, source_paper_id, title, source_type, retrieval_date,
            screening_status, import_status
        ) VALUES (100, 'OFFSET-100', 'Offset row', 'fixture', '2026-08-06',
                  'include', 'needs_review');
        INSERT INTO formulation (
            formulation_id, paper_id, formulation_name
        ) VALUES (100, 100, 'Offset formulation');
        INSERT INTO experiment (
            experiment_id, paper_id, formulation_id, cell_type
        ) VALUES (100, 100, 100, 'hepatocyte');
        INSERT INTO outcome (
            outcome_id, experiment_id, endpoint_family, endpoint_name,
            value_status
        ) VALUES (100, 100, 'other', 'offset outcome', 'missing');
        INSERT INTO evidence (
            evidence_id, paper_id, experiment_id, outcome_id, field_name,
            evidence_text, evidence_location_type, extraction_method,
            extraction_confidence
        ) VALUES (100, 100, 100, 100, 'offset', 'Offset evidence.',
                  'other', 'manual', 'high');
        """
    )
    connection.commit()


def test_field_link_natural_keys_are_stable_across_database_rebuilds(
    tmp_path: Path,
) -> None:
    first = _connection(tmp_path / "first")
    second = _connection(tmp_path / "second")
    try:
        _shift_surrogate_ids(second)
        _import_bundle(first, _load_bundle())
        _import_bundle(second, _load_bundle())

        first_keys = {
            row[0]
            for row in first.execute(
                "SELECT natural_key FROM import_field_evidence"
            )
        }
        second_keys = {
            row[0]
            for row in second.execute(
                "SELECT natural_key FROM import_field_evidence"
            )
        }
        assert first_keys == second_keys
        assert all("GP-002" in key and "E-1" in key for key in first_keys)
        assert first.execute(
            "SELECT experiment_id FROM experiment WHERE paper_id != 100"
        ).fetchone() == (1,)
        assert second.execute(
            "SELECT experiment_id FROM experiment WHERE paper_id != 100"
        ).fetchone() == (101,)
    finally:
        first.close()
        second.close()


def _replace_with_prior_field_evidence_schema(
    connection: sqlite3.Connection,
) -> None:
    connection.executescript(
        """
        ALTER TABLE import_field_evidence
            RENAME TO import_field_evidence_new;
        CREATE TABLE import_field_evidence (
            import_field_evidence_id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL CHECK (
                entity_type IN ('formulation', 'component', 'arm', 'outcome')
            ),
            entity_id INTEGER NOT NULL,
            field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
            evidence_id INTEGER NOT NULL,
            verification_status TEXT NOT NULL,
            notes TEXT,
            UNIQUE (
                paper_id, entity_type, entity_id, field_name,
                evidence_id, verification_status
            ),
            FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
                ON UPDATE CASCADE ON DELETE RESTRICT,
            FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
                ON UPDATE CASCADE ON DELETE RESTRICT
        );
        INSERT INTO import_field_evidence (
            import_field_evidence_id, paper_id, entity_type, entity_id,
            field_name, evidence_id, verification_status, notes
        )
        SELECT import_field_evidence_id, paper_id, entity_type, entity_id,
               field_name, evidence_id, verification_status, notes
        FROM import_field_evidence_new;
        DROP TABLE import_field_evidence_new;
        CREATE TABLE IF NOT EXISTS import_schema_migration (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        );
        DELETE FROM import_schema_migration;
        """
    )
    connection.commit()


def test_prior_field_link_schema_migrates_idempotently_without_data_loss(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    try:
        _import_bundle(connection, _load_bundle())
        _replace_with_prior_field_evidence_schema(connection)

        _import_bundle(connection, _load_bundle())
        _import_bundle(connection, _load_bundle())

        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(import_field_evidence)"
            )
        }
        assert {"natural_key", "content_sha256", "content_json"} <= columns
        assert connection.execute(
            "SELECT COUNT(*) FROM import_field_evidence"
        ).fetchone() == (19,)
        assert connection.execute(
            """
            SELECT version, name FROM import_schema_migration
            ORDER BY version
            """
        ).fetchall() == [
            (1, "stable_field_evidence_identity"),
            (2, "drop_legacy_field_evidence_uniqueness"),
        ]
        assert connection.execute(
            "SELECT COUNT(DISTINCT natural_key) FROM import_field_evidence"
        ).fetchone() == (19,)
        indexes = {
            row[1]: row[2]
            for row in connection.execute(
                "PRAGMA index_list(import_field_evidence)"
            ).fetchall()
        }
        assert indexes["idx_import_field_evidence_identity"] == 1
        foreign_keys = {
            (row[2], row[3], row[4], row[5], row[6])
            for row in connection.execute(
                "PRAGMA foreign_key_list(import_field_evidence)"
            ).fetchall()
        }
        assert foreign_keys == {
            ("paper", "paper_id", "paper_id", "CASCADE", "RESTRICT"),
            (
                "evidence",
                "evidence_id",
                "evidence_id",
                "CASCADE",
                "RESTRICT",
            ),
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_prior_field_link_schema_retains_notes_revision_as_conflict(
    tmp_path: Path,
) -> None:
    changed = _load_payload()
    for link in changed["field_evidence_links"]:
        if link["entity_type"] == "arm" and link["field_name"] == "dose":
            link["notes"] = "A revised evidence-link interpretation."
    connection = _connection(tmp_path)
    try:
        _import_bundle(connection, _load_bundle())
        _replace_with_prior_field_evidence_schema(connection)

        result = _import_bundle(connection, _load_bundle(changed))

        assert result.conflicts == 1
        assert connection.execute(
            """
            SELECT notes FROM import_field_evidence
            WHERE entity_type = 'arm' AND field_name = 'dose'
            ORDER BY import_field_evidence_id
            """
        ).fetchall() == [
            (None,),
            ("A revised evidence-link interpretation.",),
        ]
    finally:
        connection.close()


def test_screening_only_import_creates_no_scientific_rows(tmp_path: Path) -> None:
    payload = _load_payload()
    payload["paper"].update(
        screening_status="exclude",
        import_status="screening_only",
        screening_reason="Does not meet the evidence scope.",
    )
    for section in (
        "formulations",
        "components",
        "arms",
        "outcomes",
        "evidence",
        "field_evidence_links",
    ):
        payload[section] = []
    payload["reviews"] = [
        {
            "record_id": "R-1",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "reason_code": "source_file_unavailable",
            "status": "blocked",
            "notes": "No source-derived full text is available.",
        }
    ]
    connection = _connection(tmp_path)
    try:
        result = _import_bundle(connection, _load_bundle(payload))

        assert result.inserted == 1
        assert result.review_tags == ("Source file unavailable",)
        assert connection.execute(
            "SELECT screening_status, import_status FROM paper"
        ).fetchone() == ("exclude", "screening_only")
        for table in (
            "formulation",
            "chemical_component",
            "experiment",
            "outcome",
            "evidence",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone() == (0,)
    finally:
        connection.close()


def test_quarantine_and_plain_language_review_tag_are_persisted(
    tmp_path: Path,
) -> None:
    payload = _load_payload()
    payload["arms"][0].update(
        completeness_status="quarantined",
        verification_status="rejected",
        nearest_neighbor_eligible=False,
        comet_eligible=False,
        quarantine_reason="Outcome relationship could not be resolved.",
    )
    payload["reviews"] = [
        {
            "record_id": "R-1",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "arm_id": "A-1",
            "evidence_ids": ["E-1"],
            "reason_code": "outcome_link_unclear",
            "status": "quarantined",
            "notes": "Machine route outcome_relation_v12 could not decide.",
        }
    ]
    connection = _connection(tmp_path)
    try:
        result = _import_bundle(connection, _load_bundle(payload))

        assert result.quarantined == 1
        assert result.review_tags == ("Outcome link unclear",)
        assert connection.execute(
            """
            SELECT completeness_status, nearest_neighbor_eligible,
                   comet_eligible, quarantine_reason
            FROM arm_assessment
            """
        ).fetchone() == (
            "quarantined",
            0,
            0,
            "Outcome relationship could not be resolved.",
        )
        assert connection.execute(
            """
            SELECT reason_code, review_tag, artifact_path,
                   artifact_sha256, evidence_ids_json
            FROM import_review
            """
        ).fetchone() == (
            "outcome_link_unclear",
            "Outcome link unclear",
            "data/staging/GP-002/accepted_graph.json",
            "a" * 64,
            "[1]",
        )
    finally:
        connection.close()


def test_unknown_machine_reason_maps_to_human_verification_tag() -> None:
    module = importlib.import_module("src.database.review_tags")
    payload = _load_payload()
    payload["arms"][0].update(
        completeness_status="incomplete",
        nearest_neighbor_eligible=False,
        comet_eligible=False,
    )
    payload["reviews"] = [
        {
            "record_id": "R-1",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "arm_id": "A-1",
            "reason_code": "missing_dose",
            "status": "incomplete",
        },
        {
            "record_id": "R-2",
            "paper_id": "GP-002",
            "artifact_id": "accepted-graph",
            "arm_id": "A-1",
            "reason_code": "candidate_relation_v12_unknown_evidence_id",
            "status": "incomplete",
        },
    ]

    tags = module.derive_review_tags(_load_bundle(payload))

    assert tags == ("Missing dose", "Needs human verification")
    assert all("v12" not in tag and "candidate" not in tag for tag in tags)
