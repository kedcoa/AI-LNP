"""Transactional import of one normalized, evidence-preserving paper bundle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from src.database.import_contracts import (
    ArmRecord,
    ComponentRecord,
    EvidenceRecord,
    FormulationRecord,
    ImportBundle,
    OutcomeRecord,
    PaperRecord,
    ReviewRecord,
    SourceArtifactRecord,
)
from src.database.review_tags import derive_review_tags, review_tag_for_reason


_IMPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS import_record_identity (
    import_record_identity_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL CHECK (
        entity_type IN (
            'paper', 'formulation', 'chemical_component',
            'experiment', 'outcome', 'evidence'
        )
    ),
    natural_key TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    content_json TEXT NOT NULL CHECK (json_valid(content_json)),
    entity_id INTEGER NOT NULL,
    UNIQUE (paper_id, entity_type, natural_key, content_sha256),
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_import_record_natural_key
    ON import_record_identity(paper_id, entity_type, natural_key);

CREATE TABLE IF NOT EXISTS import_field_evidence (
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
    natural_key TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    content_json TEXT NOT NULL CHECK (json_valid(content_json)),
    UNIQUE (paper_id, natural_key, content_sha256),
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS import_review (
    import_review_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    natural_key TEXT NOT NULL,
    arm_id INTEGER,
    outcome_id INTEGER,
    reason_code TEXT NOT NULL CHECK (length(trim(reason_code)) > 0),
    review_status TEXT NOT NULL CHECK (
        review_status IN ('incomplete', 'conflict', 'quarantined', 'blocked')
    ),
    review_tag TEXT NOT NULL CHECK (
        review_tag IN (
            'Missing dose',
            'Missing formulation ratio',
            'Missing outcome value',
            'Missing evidence excerpt',
            'Source file unavailable',
            'Conflicting formulation',
            'Conflicting target cell',
            'Conflicting outcome',
            'Experiment link unclear',
            'Outcome link unclear',
            'Unsupported value',
            'Needs human verification'
        )
    ),
    field_name TEXT,
    notes TEXT,
    artifact_path TEXT,
    artifact_sha256 TEXT CHECK (
        artifact_sha256 IS NULL OR length(artifact_sha256) = 64
    ),
    evidence_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(evidence_ids_json)
    ),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    UNIQUE (paper_id, natural_key, content_sha256),
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (arm_id) REFERENCES experiment(experiment_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (outcome_id) REFERENCES outcome(outcome_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
"""

_IMPORT_SCHEMA_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS import_schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);
"""

_FIELD_EVIDENCE_LEGACY_UNIQUE_COLUMNS = (
    "paper_id",
    "entity_type",
    "entity_id",
    "field_name",
    "evidence_id",
    "verification_status",
)

_FIELD_EVIDENCE_REBUILD_SQL = """
CREATE TABLE import_field_evidence_migration_v2 (
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
    natural_key TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    content_json TEXT NOT NULL CHECK (json_valid(content_json)),
    UNIQUE (paper_id, natural_key, content_sha256),
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

INSERT INTO import_field_evidence_migration_v2 (
    import_field_evidence_id, paper_id, entity_type, entity_id,
    field_name, evidence_id, verification_status, notes,
    natural_key, content_sha256, content_json
)
SELECT import_field_evidence_id, paper_id, entity_type, entity_id,
       field_name, evidence_id, verification_status, notes,
       natural_key, content_sha256, content_json
FROM import_field_evidence;

DROP TABLE import_field_evidence;

ALTER TABLE import_field_evidence_migration_v2
    RENAME TO import_field_evidence;
"""


@dataclass(frozen=True)
class PaperImportResult:
    inserted: int
    unchanged: int
    conflicts: int
    quarantined: int
    review_tags: tuple[str, ...]


@dataclass
class _Counters:
    inserted: int = 0
    unchanged: int = 0
    conflicts: int = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    pending: list[str] = []
    for line in script.splitlines(keepends=True):
        pending.append(line)
        statement = "".join(pending)
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            pending.clear()
    if "".join(pending).strip():
        raise sqlite3.OperationalError("incomplete importer schema statement")


def _artifact(bundle: ImportBundle, artifact_id: str) -> SourceArtifactRecord:
    return next(row for row in bundle.artifacts if row.artifact_id == artifact_id)


def _field_link_natural_key(
    *,
    source_paper_id: str,
    entity_type: str,
    entity_local_key: str,
    entity_artifact_path: str,
    entity_artifact_sha256: str,
    evidence_local_key: str,
    evidence_artifact_path: str,
    evidence_artifact_sha256: str,
    field_name: str,
) -> str:
    return json.dumps(
        {
            "source_paper_id": source_paper_id,
            "entity": {
                "type": entity_type,
                "local_key": entity_local_key,
                "artifact_path": entity_artifact_path,
                "artifact_sha256": entity_artifact_sha256.lower(),
            },
            "evidence": {
                "local_key": evidence_local_key,
                "artifact_path": evidence_artifact_path,
                "artifact_sha256": evidence_artifact_sha256.lower(),
            },
            "field_name": field_name,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _database_record_identity(
    connection: sqlite3.Connection,
    *,
    paper_id: int,
    entity_type: str,
    entity_id: int,
) -> tuple[str, str, str]:
    identity_type = {
        "formulation": "formulation",
        "component": "chemical_component",
        "arm": "experiment",
        "outcome": "outcome",
        "evidence": "evidence",
    }[entity_type]
    row = connection.execute(
        """
        SELECT content_json
        FROM import_record_identity
        WHERE paper_id = ? AND entity_type = ? AND entity_id = ?
        ORDER BY import_record_identity_id
        LIMIT 1
        """,
        (paper_id, identity_type, entity_id),
    ).fetchone()
    if row is not None:
        content = json.loads(row[0])
        return (
            str(content["record"]["record_id"]),
            str(content["artifact"]["path"]),
            str(content["artifact"]["sha256"]),
        )
    source = connection.execute(
        """
        SELECT artifact_path, artifact_sha256
        FROM record_source
        WHERE paper_id = ? AND entity_type = ? AND entity_id = ?
        ORDER BY record_source_id
        LIMIT 1
        """,
        (paper_id, identity_type, entity_id),
    ).fetchone()
    if source is None:
        return (f"legacy-{entity_type}-{entity_id}", "legacy", "0" * 64)
    return (f"legacy-{entity_type}-{entity_id}", source[0], source[1])


def _has_unique_index(
    connection: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> bool:
    quoted_table_name = table_name.replace('"', '""')
    for index in connection.execute(
        f'PRAGMA index_list("{quoted_table_name}")'
    ).fetchall():
        if not index[2]:
            continue
        index_name = str(index[1]).replace('"', '""')
        index_columns = tuple(
            row[2]
            for row in connection.execute(
                f'PRAGMA index_info("{index_name}")'
            ).fetchall()
        )
        if index_columns == columns:
            return True
    return False


def _migrate_import_schema(connection: sqlite3.Connection) -> None:
    _execute_script(connection, _IMPORT_SCHEMA_MIGRATION_SQL)
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(import_field_evidence)"
        )
    }
    additions = {
        "natural_key": "TEXT",
        "content_sha256": "TEXT",
        "content_json": "TEXT",
    }
    for column, declaration in additions.items():
        if column not in columns:
            connection.execute(
                f"ALTER TABLE import_field_evidence "
                f"ADD COLUMN {column} {declaration}"
            )
    rows = connection.execute(
        """
        SELECT import_field_evidence_id, paper_id, entity_type, entity_id,
               field_name, evidence_id, verification_status, notes
        FROM import_field_evidence
        WHERE natural_key IS NULL OR content_sha256 IS NULL
           OR content_json IS NULL
        ORDER BY import_field_evidence_id
        """
    ).fetchall()
    for row in rows:
        (
            link_id,
            paper_id,
            entity_type,
            entity_id,
            field_name,
            evidence_id,
            verification_status,
            notes,
        ) = row
        source_paper_id = connection.execute(
            "SELECT source_paper_id FROM paper WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()[0]
        entity_key, entity_path, entity_sha = _database_record_identity(
            connection,
            paper_id=paper_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        evidence_key, evidence_path, evidence_sha = _database_record_identity(
            connection,
            paper_id=paper_id,
            entity_type="evidence",
            entity_id=evidence_id,
        )
        natural_key = _field_link_natural_key(
            source_paper_id=source_paper_id,
            entity_type=entity_type,
            entity_local_key=entity_key,
            entity_artifact_path=entity_path,
            entity_artifact_sha256=entity_sha,
            evidence_local_key=evidence_key,
            evidence_artifact_path=evidence_path,
            evidence_artifact_sha256=evidence_sha,
            field_name=field_name,
        )
        content_json = json.dumps(
            {"verification_status": verification_status, "notes": notes},
            sort_keys=True,
            separators=(",", ":"),
        )
        content_sha256 = hashlib.sha256(
            content_json.encode("utf-8")
        ).hexdigest()
        connection.execute(
            """
            UPDATE import_field_evidence
            SET natural_key = ?, content_sha256 = ?, content_json = ?
            WHERE import_field_evidence_id = ?
            """,
            (natural_key, content_sha256, content_json, link_id),
        )
    if _has_unique_index(
        connection,
        "import_field_evidence",
        _FIELD_EVIDENCE_LEGACY_UNIQUE_COLUMNS,
    ):
        _execute_script(connection, _FIELD_EVIDENCE_REBUILD_SQL)
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_import_field_evidence_identity
        ON import_field_evidence(paper_id, natural_key, content_sha256)
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO import_schema_migration (
            version, name, applied_at
        ) VALUES (1, 'stable_field_evidence_identity', ?)
        """,
        (_utc_now(),),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO import_schema_migration (
            version, name, applied_at
        ) VALUES (2, 'drop_legacy_field_evidence_uniqueness', ?)
        """,
        (_utc_now(),),
    )


def _serialized_content(
    record: object,
    artifact: SourceArtifactRecord,
    identity_context: dict[str, int] | None = None,
) -> tuple[str, str]:
    payload = {
        "artifact": {
            "artifact_id": artifact.artifact_id,
            "path": artifact.path,
            "sha256": artifact.sha256.lower(),
        },
        "identity_context": identity_context or {},
        "record": asdict(record),
    }
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return content, hashlib.sha256(content.encode("utf-8")).hexdigest()


def _identity(
    connection: sqlite3.Connection,
    paper_id: int,
    entity_type: str,
    natural_key: str,
    content_sha256: str,
) -> int | None:
    row = connection.execute(
        """
        SELECT entity_id
        FROM import_record_identity
        WHERE paper_id = ? AND entity_type = ? AND natural_key = ?
          AND content_sha256 = ?
        """,
        (paper_id, entity_type, natural_key, content_sha256),
    ).fetchone()
    return None if row is None else int(row[0])


def _natural_key_exists(
    connection: sqlite3.Connection,
    paper_id: int,
    entity_type: str,
    natural_key: str,
) -> bool:
    return connection.execute(
        """
        SELECT 1 FROM import_record_identity
        WHERE paper_id = ? AND entity_type = ? AND natural_key = ?
        LIMIT 1
        """,
        (paper_id, entity_type, natural_key),
    ).fetchone() is not None


def _record_identity(
    connection: sqlite3.Connection,
    *,
    paper_id: int,
    entity_type: str,
    natural_key: str,
    content_sha256: str,
    content_json: str,
    entity_id: int,
) -> None:
    connection.execute(
        """
        INSERT INTO import_record_identity (
            paper_id, entity_type, natural_key, content_sha256,
            content_json, entity_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            entity_type,
            natural_key,
            content_sha256,
            content_json,
            entity_id,
        ),
    )


def _record_provenance(
    connection: sqlite3.Connection,
    *,
    paper_id: int,
    entity_type: str,
    entity_id: int,
    artifact: SourceArtifactRecord,
) -> None:
    connection.execute(
        """
        INSERT INTO record_source (
            paper_id, entity_type, entity_id, artifact_path,
            artifact_sha256, pipeline_name, pipeline_version,
            extraction_run_identifier, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            entity_type,
            entity_id,
            artifact.path,
            artifact.sha256.lower(),
            artifact.pipeline_name,
            artifact.pipeline_version,
            artifact.extraction_run_identifier,
            _utc_now(),
        ),
    )


def _affected_arm_ids(
    connection: sqlite3.Connection,
    paper_id: int,
    entity_type: str,
    natural_key: str,
) -> tuple[int, ...]:
    if entity_type == "paper":
        rows = connection.execute(
            "SELECT experiment_id FROM experiment WHERE paper_id = ?",
            (paper_id,),
        )
    elif entity_type == "formulation":
        rows = connection.execute(
            """
            SELECT DISTINCT experiment.experiment_id
            FROM import_record_identity AS identity_record
            JOIN experiment
              ON experiment.formulation_id = identity_record.entity_id
            WHERE identity_record.paper_id = ?
              AND identity_record.entity_type = 'formulation'
              AND identity_record.natural_key = ?
            """,
            (paper_id, natural_key),
        )
    elif entity_type == "chemical_component":
        rows = connection.execute(
            """
            SELECT DISTINCT experiment.experiment_id
            FROM import_record_identity AS identity_record
            JOIN chemical_component AS component
              ON component.component_id = identity_record.entity_id
            JOIN experiment
              ON experiment.formulation_id = component.formulation_id
            WHERE identity_record.paper_id = ?
              AND identity_record.entity_type = 'chemical_component'
              AND identity_record.natural_key = ?
            """,
            (paper_id, natural_key),
        )
    elif entity_type == "experiment":
        rows = connection.execute(
            """
            SELECT entity_id FROM import_record_identity
            WHERE paper_id = ? AND entity_type = 'experiment'
              AND natural_key = ?
            """,
            (paper_id, natural_key),
        )
    elif entity_type == "outcome":
        rows = connection.execute(
            """
            SELECT DISTINCT outcome.experiment_id
            FROM import_record_identity AS identity_record
            JOIN outcome ON outcome.outcome_id = identity_record.entity_id
            WHERE identity_record.paper_id = ?
              AND identity_record.entity_type = 'outcome'
              AND identity_record.natural_key = ?
            """,
            (paper_id, natural_key),
        )
    else:
        rows = connection.execute(
            """
            SELECT DISTINCT evidence.experiment_id
            FROM import_record_identity AS identity_record
            JOIN evidence ON evidence.evidence_id = identity_record.entity_id
            WHERE identity_record.paper_id = ?
              AND identity_record.entity_type = 'evidence'
              AND identity_record.natural_key = ?
              AND evidence.experiment_id IS NOT NULL
            """,
            (paper_id, natural_key),
        )
    return tuple(int(row[0]) for row in rows)


def _mark_conflict_arms(
    connection: sqlite3.Connection,
    *,
    paper_id: int,
    entity_type: str,
    natural_key: str,
    field_name: str,
) -> None:
    for experiment_id in _affected_arm_ids(
        connection, paper_id, entity_type, natural_key
    ):
        connection.execute(
            """
            UPDATE arm_assessment
            SET completeness_status = CASE
                    WHEN completeness_status = 'quarantined'
                    THEN 'quarantined'
                    ELSE 'conflict'
                END,
                verification_status = CASE
                    WHEN completeness_status = 'quarantined'
                    THEN 'rejected'
                    ELSE 'conflict'
                END,
                nearest_neighbor_eligible = 0,
                comet_eligible = 0,
                updated_at = ?
            WHERE experiment_id = ?
            """,
            (_utc_now(), experiment_id),
        )
        connection.execute(
            """
            INSERT INTO field_verification (
                experiment_id, field_name, verification_status,
                notes, verified_at
            )
            SELECT ?, ?, 'conflict', ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM field_verification
                WHERE experiment_id = ? AND field_name = ?
                  AND verification_status = 'conflict'
            )
            """,
            (
                experiment_id,
                field_name,
                "Multiple contents share one stable import identity.",
                _utc_now(),
                experiment_id,
                field_name,
            ),
        )


def _field_link_arm_ids(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
) -> tuple[int, ...]:
    if entity_type == "arm":
        return (entity_id,)
    if entity_type == "outcome":
        row = connection.execute(
            "SELECT experiment_id FROM outcome WHERE outcome_id = ?",
            (entity_id,),
        ).fetchone()
        return () if row is None else (int(row[0]),)
    if entity_type == "formulation":
        rows = connection.execute(
            "SELECT experiment_id FROM experiment WHERE formulation_id = ?",
            (entity_id,),
        )
    else:
        rows = connection.execute(
            """
            SELECT experiment.experiment_id
            FROM chemical_component AS component
            JOIN experiment
              ON experiment.formulation_id = component.formulation_id
            WHERE component.component_id = ?
            """,
            (entity_id,),
        )
    return tuple(int(row[0]) for row in rows)


def _mark_field_link_conflict(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: int,
    field_name: str,
) -> None:
    for experiment_id in _field_link_arm_ids(
        connection, entity_type, entity_id
    ):
        connection.execute(
            """
            UPDATE arm_assessment
            SET completeness_status = CASE
                    WHEN completeness_status = 'quarantined'
                    THEN 'quarantined'
                    ELSE 'conflict'
                END,
                verification_status = CASE
                    WHEN completeness_status = 'quarantined'
                    THEN 'rejected'
                    ELSE 'conflict'
                END,
                nearest_neighbor_eligible = 0,
                comet_eligible = 0,
                updated_at = ?
            WHERE experiment_id = ?
            """,
            (_utc_now(), experiment_id),
        )
        conflict_field = f"field_evidence_content:{field_name}"
        connection.execute(
            """
            INSERT INTO field_verification (
                experiment_id, field_name, verification_status,
                notes, verified_at
            )
            SELECT ?, ?, 'conflict', ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM field_verification
                WHERE experiment_id = ? AND field_name = ?
                  AND verification_status = 'conflict'
            )
            """,
            (
                experiment_id,
                conflict_field,
                "Changed content shares one stable field-evidence identity.",
                _utc_now(),
                experiment_id,
                conflict_field,
            ),
        )


def _resolve_record(
    connection: sqlite3.Connection,
    *,
    bundle: ImportBundle,
    paper_id: int,
    entity_type: str,
    natural_key: str,
    record: object,
    artifact_id: str,
    identity_context: dict[str, int] | None,
    insert: Callable[[], int],
    counters: _Counters,
) -> tuple[int, bool]:
    artifact = _artifact(bundle, artifact_id)
    content_json, content_sha256 = _serialized_content(
        record, artifact, identity_context
    )
    existing_id = _identity(
        connection,
        paper_id,
        entity_type,
        natural_key,
        content_sha256,
    )
    if existing_id is not None:
        counters.unchanged += 1
        return existing_id, False

    is_conflict = _natural_key_exists(
        connection, paper_id, entity_type, natural_key
    )
    entity_id = int(insert())
    _record_identity(
        connection,
        paper_id=paper_id,
        entity_type=entity_type,
        natural_key=natural_key,
        content_sha256=content_sha256,
        content_json=content_json,
        entity_id=entity_id,
    )
    _record_provenance(
        connection,
        paper_id=paper_id,
        entity_type=entity_type,
        entity_id=entity_id,
        artifact=artifact,
    )
    counters.inserted += 1
    if is_conflict:
        counters.conflicts += 1
    return entity_id, is_conflict


def _insert_paper(
    connection: sqlite3.Connection,
    bundle: ImportBundle,
    counters: _Counters,
) -> tuple[int, bool]:
    record = bundle.paper
    artifact = _artifact(bundle, record.artifact_id)
    natural_key = f"{record.artifact_id}:{record.source_paper_id}"
    content_json, content_sha256 = _serialized_content(record, artifact)
    existing_id = connection.execute(
        "SELECT paper_id FROM paper WHERE source_paper_id = ?",
        (record.source_paper_id,),
    ).fetchone()
    if existing_id is not None:
        paper_id = int(existing_id[0])
        exact = _identity(
            connection,
            paper_id,
            "paper",
            natural_key,
            content_sha256,
        )
        if exact is not None:
            counters.unchanged += 1
            return paper_id, False
        _record_identity(
            connection,
            paper_id=paper_id,
            entity_type="paper",
            natural_key=natural_key,
            content_sha256=content_sha256,
            content_json=content_json,
            entity_id=paper_id,
        )
        _record_provenance(
            connection,
            paper_id=paper_id,
            entity_type="paper",
            entity_id=paper_id,
            artifact=artifact,
        )
        counters.conflicts += 1
        return paper_id, True

    paper_id = int(
        connection.execute(
            """
            INSERT INTO paper (
                source_paper_id, pmid, pmcid, doi, title, authors, journal,
                publication_year, source_type, source_url, retrieval_date,
                search_query_id, full_text_status, screening_status,
                screening_reason, import_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.source_paper_id,
                record.pmid,
                record.pmcid,
                record.doi,
                record.title,
                record.authors,
                record.journal,
                record.publication_year,
                record.source_type,
                record.source_url,
                record.retrieval_date,
                record.search_query_id,
                record.full_text_status,
                record.screening_status,
                record.screening_reason,
                record.import_status,
            ),
        ).lastrowid
    )
    _record_identity(
        connection,
        paper_id=paper_id,
        entity_type="paper",
        natural_key=natural_key,
        content_sha256=content_sha256,
        content_json=content_json,
        entity_id=paper_id,
    )
    _record_provenance(
        connection,
        paper_id=paper_id,
        entity_type="paper",
        entity_id=paper_id,
        artifact=artifact,
    )
    counters.inserted += 1
    return paper_id, False


def _insert_formulation(
    connection: sqlite3.Connection,
    record: FormulationRecord,
    paper_id: int,
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO formulation (
                paper_id, formulation_name, composition_raw,
                composition_basis, np_ratio, formulation_notes,
                formulation_review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                record.formulation_name,
                record.composition_raw,
                record.composition_basis,
                record.np_ratio,
                record.formulation_notes,
                record.formulation_review_status,
            ),
        ).lastrowid
    )


def _insert_component(
    connection: sqlite3.Connection,
    record: ComponentRecord,
    formulation_id: int,
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO chemical_component (
                formulation_id, component_name_reported,
                component_name_normalized, component_role, inchikey,
                molar_percentage, percentage_unit, component_review_status,
                identity_source, identity_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                formulation_id,
                record.component_name_reported,
                record.component_name_normalized,
                record.component_role,
                record.inchikey,
                record.molar_percentage,
                record.percentage_unit,
                record.component_review_status,
                record.identity_source,
                record.identity_notes,
            ),
        ).lastrowid
    )


def _insert_arm(
    connection: sqlite3.Connection,
    record: ArmRecord,
    paper_id: int,
    formulation_id: int,
) -> int:
    values = (
        paper_id,
        formulation_id,
        record.cell_type,
        record.cell_source,
        record.tissue_or_organ,
        record.species,
        record.disease_model,
        record.in_vitro_in_vivo,
        record.payload_type,
        record.payload_name,
        record.payload_encoded_product,
        record.payload_molecular_target,
        record.reporter,
        record.dose,
        record.dose_unit,
        record.route,
        record.timepoint,
        record.timepoint_unit,
        record.assay,
        record.comparator_type,
        record.comparator_description,
        record.protocol_reference,
        record.experiment_notes,
    )
    experiment_id = int(
        connection.execute(
            """
            INSERT INTO experiment (
                paper_id, formulation_id, cell_type, cell_source,
                tissue_or_organ, species, disease_model, in_vitro_in_vivo,
                payload_type, payload_name, payload_encoded_product,
                payload_molecular_target, reporter, dose, dose_unit, route,
                timepoint, timepoint_unit, assay, comparator_type,
                comparator_description, protocol_reference, experiment_notes
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            values,
        ).lastrowid
    )
    connection.execute(
        """
        INSERT INTO arm_assessment (
            experiment_id, completeness_status, missing_fields_json,
            verification_status, nearest_neighbor_eligible, comet_eligible,
            quarantine_reason, updated_at
        ) VALUES (?, ?, '[]', ?, ?, ?, ?, ?)
        """,
        (
            experiment_id,
            record.completeness_status,
            record.verification_status,
            int(record.nearest_neighbor_eligible),
            int(record.comet_eligible),
            record.quarantine_reason,
            _utc_now(),
        ),
    )
    return experiment_id


def _insert_outcome(
    connection: sqlite3.Connection,
    record: OutcomeRecord,
    experiment_id: int,
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO outcome (
                experiment_id, endpoint_family, endpoint_name,
                outcome_value, outcome_unit, normalization_basis,
                uncertainty_value, uncertainty_type, qualitative_outcome,
                value_status, outcome_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                record.endpoint_family,
                record.endpoint_name,
                record.outcome_value,
                record.outcome_unit,
                record.normalization_basis,
                record.uncertainty_value,
                record.uncertainty_type,
                record.qualitative_outcome,
                record.value_status,
                record.outcome_notes,
            ),
        ).lastrowid
    )


def _insert_evidence(
    connection: sqlite3.Connection,
    record: EvidenceRecord,
    paper_id: int,
    experiment_id: int | None,
    outcome_id: int | None,
) -> int:
    evidence_text = record.evidence_text
    if evidence_text is None:
        evidence_text = json.dumps(
            record.structured_evidence,
            sort_keys=True,
            separators=(",", ":"),
        )
    evidence_status = (
        "unreviewed"
        if record.verification_status == "automatically_validated"
        else record.verification_status
    )
    reviewer_notes = record.reviewer_notes
    if record.verification_status == "automatically_validated":
        mapping_note = (
            "Source verification status automatically_validated; stored as "
            "unreviewed because the core schema has no automatic state."
        )
        reviewer_notes = (
            f"{reviewer_notes}\n{mapping_note}"
            if reviewer_notes
            else mapping_note
        )
    return int(
        connection.execute(
            """
            INSERT INTO evidence (
                paper_id, experiment_id, outcome_id, field_name,
                evidence_text, evidence_location_type, section_name,
                page_number, table_number, figure_number,
                supplement_identifier, extraction_method,
                extraction_confidence, evidence_review_status, reviewer_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                experiment_id,
                outcome_id,
                record.field_name,
                evidence_text,
                record.evidence_location_type,
                record.section_name,
                record.page_number,
                record.table_number,
                record.figure_number,
                record.supplement_identifier,
                record.extraction_method,
                record.extraction_confidence,
                evidence_status,
                reviewer_notes,
            ),
        ).lastrowid
    )


def _store_review(
    connection: sqlite3.Connection,
    *,
    paper_id: int,
    natural_key: str,
    arm_id: int | None,
    outcome_id: int | None,
    reason_code: str,
    status: str,
    field_name: str | None,
    notes: str | None,
    artifact: SourceArtifactRecord | None = None,
    evidence_ids: tuple[int, ...] = (),
) -> str:
    tag = review_tag_for_reason(reason_code)
    content = json.dumps(
        {
            "arm_id": arm_id,
            "outcome_id": outcome_id,
            "reason_code": reason_code,
            "status": status,
            "field_name": field_name,
            "notes": notes,
            "artifact_path": artifact.path if artifact else None,
            "artifact_sha256": artifact.sha256.lower() if artifact else None,
            "evidence_ids": evidence_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    connection.execute(
        """
        INSERT OR IGNORE INTO import_review (
            paper_id, natural_key, arm_id, outcome_id, reason_code,
            review_status, review_tag, field_name, notes, artifact_path,
            artifact_sha256, evidence_ids_json, content_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            natural_key,
            arm_id,
            outcome_id,
            reason_code,
            status,
            tag,
            field_name,
            notes,
            artifact.path if artifact else None,
            artifact.sha256.lower() if artifact else None,
            json.dumps(evidence_ids, separators=(",", ":")),
            content_hash,
        ),
    )
    return tag


def _store_explicit_review(
    connection: sqlite3.Connection,
    record: ReviewRecord,
    bundle: ImportBundle,
    paper_id: int,
    arm_ids: dict[str, int],
    outcome_ids: dict[str, int],
    evidence_ids: dict[str, int],
) -> str:
    arm_id = arm_ids.get(record.arm_id) if record.arm_id else None
    outcome_id = outcome_ids.get(record.outcome_id) if record.outcome_id else None
    tag = _store_review(
        connection,
        paper_id=paper_id,
        natural_key=record.record_id,
        arm_id=arm_id,
        outcome_id=outcome_id,
        reason_code=record.reason_code,
        status=record.status,
        field_name=record.field_name,
        notes=record.notes,
        artifact=_artifact(bundle, record.artifact_id),
        evidence_ids=tuple(
            evidence_ids[evidence_id] for evidence_id in record.evidence_ids
        ),
    )
    if record.status == "incomplete" and arm_id is not None and record.field_name:
        connection.execute(
            """
            INSERT INTO missing_field (experiment_id, field_name, reason, recorded_at)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM missing_field
                WHERE experiment_id = ? AND field_name = ? AND reason = ?
                  AND resolved_at IS NULL
            )
            """,
            (
                arm_id,
                record.field_name,
                record.reason_code,
                _utc_now(),
                arm_id,
                record.field_name,
                record.reason_code,
            ),
        )
    return tag


def import_bundle(
    connection: sqlite3.Connection,
    bundle: ImportBundle,
) -> PaperImportResult:
    """Import one validated paper bundle inside one explicit savepoint."""

    if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise RuntimeError("SQLite foreign-key enforcement must be enabled")
    counters = _Counters()
    review_tags: list[str] = list(derive_review_tags(bundle))
    savepoint = "normalized_paper_import"
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        _execute_script(connection, _IMPORT_SCHEMA)
        _migrate_import_schema(connection)
        paper_id, paper_conflict = _insert_paper(connection, bundle, counters)
        if paper_conflict:
            _mark_conflict_arms(
                connection,
                paper_id=paper_id,
                entity_type="paper",
                natural_key=(
                    f"{bundle.paper.artifact_id}:"
                    f"{bundle.paper.source_paper_id}"
                ),
                field_name="paper_content",
            )
            tag = _store_review(
                connection,
                paper_id=paper_id,
                natural_key="auto:paper-content-conflict",
                arm_id=None,
                outcome_id=None,
                reason_code="content_conflict_paper",
                status="conflict",
                field_name=None,
                notes="A second paper payload used the same stable source identity.",
            )
            if tag not in review_tags:
                review_tags.append(tag)

        if bundle.paper.import_status == "screening_only":
            connection.execute(
                """
                INSERT INTO screening_event (
                    paper_id, disposition, reason, source, occurred_at
                )
                SELECT ?, 'screening_only', ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM screening_event
                    WHERE paper_id = ? AND disposition = 'screening_only'
                      AND reason = ? AND source = ?
                )
                """,
                (
                    paper_id,
                    bundle.paper.screening_reason or "Screening-only paper.",
                    _artifact(bundle, bundle.paper.artifact_id).pipeline_name,
                    _utc_now(),
                    paper_id,
                    bundle.paper.screening_reason or "Screening-only paper.",
                    _artifact(bundle, bundle.paper.artifact_id).pipeline_name,
                ),
            )

        formulation_ids: dict[str, int] = {}
        component_ids: dict[str, int] = {}
        arm_ids: dict[str, int] = {}
        outcome_ids: dict[str, int] = {}
        evidence_ids: dict[str, int] = {}

        for record in bundle.formulations:
            entity_id, conflict = _resolve_record(
                connection,
                bundle=bundle,
                paper_id=paper_id,
                entity_type="formulation",
                natural_key=f"{record.artifact_id}:{record.record_id}",
                record=record,
                artifact_id=record.artifact_id,
                identity_context=None,
                insert=lambda record=record: _insert_formulation(
                    connection, record, paper_id
                ),
                counters=counters,
            )
            formulation_ids[record.record_id] = entity_id
            if conflict:
                _mark_conflict_arms(
                    connection,
                    paper_id=paper_id,
                    entity_type="formulation",
                    natural_key=f"{record.artifact_id}:{record.record_id}",
                    field_name="formulation_content",
                )
                tag = _store_review(
                    connection,
                    paper_id=paper_id,
                    natural_key=f"auto:formulation:{record.record_id}",
                    arm_id=None,
                    outcome_id=None,
                    reason_code="conflicting_formulation",
                    status="conflict",
                    field_name=None,
                    notes="Changed content retained for the same formulation identity.",
                )
                if tag not in review_tags:
                    review_tags.append(tag)

        for record in bundle.components:
            entity_id, conflict = _resolve_record(
                connection,
                bundle=bundle,
                paper_id=paper_id,
                entity_type="chemical_component",
                natural_key=f"{record.artifact_id}:{record.record_id}",
                record=record,
                artifact_id=record.artifact_id,
                identity_context={
                    "formulation_id": formulation_ids[record.formulation_id]
                },
                insert=lambda record=record: _insert_component(
                    connection,
                    record,
                    formulation_ids[record.formulation_id],
                ),
                counters=counters,
            )
            component_ids[record.record_id] = entity_id
            if conflict:
                _mark_conflict_arms(
                    connection,
                    paper_id=paper_id,
                    entity_type="chemical_component",
                    natural_key=f"{record.artifact_id}:{record.record_id}",
                    field_name="component_content",
                )
                tag = _store_review(
                    connection,
                    paper_id=paper_id,
                    natural_key=f"auto:component:{record.record_id}",
                    arm_id=None,
                    outcome_id=None,
                    reason_code="conflicting_formulation",
                    status="conflict",
                    field_name=None,
                    notes="Changed content retained for the same component identity.",
                )
                if tag not in review_tags:
                    review_tags.append(tag)

        for record in bundle.arms:
            entity_id, conflict = _resolve_record(
                connection,
                bundle=bundle,
                paper_id=paper_id,
                entity_type="experiment",
                natural_key=f"{record.artifact_id}:{record.record_id}",
                record=record,
                artifact_id=record.artifact_id,
                identity_context={
                    "formulation_id": formulation_ids[record.formulation_id]
                },
                insert=lambda record=record: _insert_arm(
                    connection,
                    record,
                    paper_id,
                    formulation_ids[record.formulation_id],
                ),
                counters=counters,
            )
            arm_ids[record.record_id] = entity_id
            if conflict:
                _mark_conflict_arms(
                    connection,
                    paper_id=paper_id,
                    entity_type="experiment",
                    natural_key=f"{record.artifact_id}:{record.record_id}",
                    field_name="arm_content",
                )
                tag = _store_review(
                    connection,
                    paper_id=paper_id,
                    natural_key=f"auto:arm:{record.record_id}",
                    arm_id=entity_id,
                    outcome_id=None,
                    reason_code="experiment_link_unclear",
                    status="conflict",
                    field_name=None,
                    notes="Changed content retained for the same arm identity.",
                )
                if tag not in review_tags:
                    review_tags.append(tag)

        for record in bundle.outcomes:
            entity_id, conflict = _resolve_record(
                connection,
                bundle=bundle,
                paper_id=paper_id,
                entity_type="outcome",
                natural_key=f"{record.artifact_id}:{record.record_id}",
                record=record,
                artifact_id=record.artifact_id,
                identity_context={"experiment_id": arm_ids[record.arm_id]},
                insert=lambda record=record: _insert_outcome(
                    connection, record, arm_ids[record.arm_id]
                ),
                counters=counters,
            )
            outcome_ids[record.record_id] = entity_id
            if conflict:
                _mark_conflict_arms(
                    connection,
                    paper_id=paper_id,
                    entity_type="outcome",
                    natural_key=f"{record.artifact_id}:{record.record_id}",
                    field_name="outcome_content",
                )
                tag = _store_review(
                    connection,
                    paper_id=paper_id,
                    natural_key=f"auto:outcome:{record.record_id}",
                    arm_id=arm_ids[record.arm_id],
                    outcome_id=entity_id,
                    reason_code="conflicting_outcome",
                    status="conflict",
                    field_name=None,
                    notes="Changed content retained for the same outcome identity.",
                )
                if tag not in review_tags:
                    review_tags.append(tag)

        for record in bundle.evidence:
            entity_id, conflict = _resolve_record(
                connection,
                bundle=bundle,
                paper_id=paper_id,
                entity_type="evidence",
                natural_key=f"{record.artifact_id}:{record.record_id}",
                record=record,
                artifact_id=record.artifact_id,
                identity_context={
                    **(
                        {"experiment_id": arm_ids[record.arm_id]}
                        if record.arm_id is not None
                        else {}
                    ),
                    **(
                        {"outcome_id": outcome_ids[record.outcome_id]}
                        if record.outcome_id is not None
                        else {}
                    ),
                },
                insert=lambda record=record: _insert_evidence(
                    connection,
                    record,
                    paper_id,
                    arm_ids.get(record.arm_id),
                    outcome_ids.get(record.outcome_id),
                ),
                counters=counters,
            )
            evidence_ids[record.record_id] = entity_id
            if conflict:
                _mark_conflict_arms(
                    connection,
                    paper_id=paper_id,
                    entity_type="evidence",
                    natural_key=f"{record.artifact_id}:{record.record_id}",
                    field_name=f"evidence_content:{record.field_name}",
                )
                tag = _store_review(
                    connection,
                    paper_id=paper_id,
                    natural_key=f"auto:evidence:{record.record_id}",
                    arm_id=arm_ids.get(record.arm_id),
                    outcome_id=outcome_ids.get(record.outcome_id),
                    reason_code="content_conflict_evidence",
                    status="conflict",
                    field_name=record.field_name,
                    notes="Changed content retained for the same evidence identity.",
                )
                if tag not in review_tags:
                    review_tags.append(tag)

        entity_maps = {
            "formulation": formulation_ids,
            "component": component_ids,
            "arm": arm_ids,
            "outcome": outcome_ids,
        }
        entity_records = {
            "formulation": {
                row.record_id: row for row in bundle.formulations
            },
            "component": {row.record_id: row for row in bundle.components},
            "arm": {row.record_id: row for row in bundle.arms},
            "outcome": {row.record_id: row for row in bundle.outcomes},
        }
        evidence_records = {row.record_id: row for row in bundle.evidence}
        outcome_records = {row.record_id: row for row in bundle.outcomes}
        for link in bundle.field_evidence_links:
            entity_id = entity_maps[link.entity_type][link.entity_id]
            for local_evidence_id in link.evidence_ids:
                evidence_id = evidence_ids[local_evidence_id]
                entity_record = entity_records[link.entity_type][link.entity_id]
                entity_artifact = _artifact(
                    bundle, entity_record.artifact_id
                )
                evidence_record = evidence_records[local_evidence_id]
                evidence_artifact = _artifact(
                    bundle, evidence_record.artifact_id
                )
                natural_key = _field_link_natural_key(
                    source_paper_id=bundle.paper.source_paper_id,
                    entity_type=link.entity_type,
                    entity_local_key=link.entity_id,
                    entity_artifact_path=entity_artifact.path,
                    entity_artifact_sha256=entity_artifact.sha256,
                    evidence_local_key=local_evidence_id,
                    evidence_artifact_path=evidence_artifact.path,
                    evidence_artifact_sha256=evidence_artifact.sha256,
                    field_name=link.field_name,
                )
                content_json = json.dumps(
                    {
                        "verification_status": link.verification_status,
                        "notes": link.notes,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                content_sha256 = hashlib.sha256(
                    content_json.encode("utf-8")
                ).hexdigest()
                exact_link = connection.execute(
                    """
                    SELECT 1 FROM import_field_evidence
                    WHERE paper_id = ? AND natural_key = ?
                      AND content_sha256 = ?
                    """,
                    (paper_id, natural_key, content_sha256),
                ).fetchone()
                link_conflict = False
                if exact_link is None:
                    link_conflict = connection.execute(
                        """
                        SELECT 1 FROM import_field_evidence
                        WHERE paper_id = ? AND natural_key = ?
                        LIMIT 1
                        """,
                        (paper_id, natural_key),
                    ).fetchone() is not None
                    connection.execute(
                        """
                        INSERT INTO import_field_evidence (
                            paper_id, entity_type, entity_id, field_name,
                            evidence_id, verification_status, notes,
                            natural_key, content_sha256, content_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            paper_id,
                            link.entity_type,
                            entity_id,
                            link.field_name,
                            evidence_id,
                            link.verification_status,
                            link.notes,
                            natural_key,
                            content_sha256,
                            content_json,
                        ),
                    )
                if link_conflict:
                    counters.conflicts += 1
                    _mark_field_link_conflict(
                        connection,
                        entity_type=link.entity_type,
                        entity_id=entity_id,
                        field_name=link.field_name,
                    )
                    affected_arms = _field_link_arm_ids(
                        connection, link.entity_type, entity_id
                    )
                    tag = _store_review(
                        connection,
                        paper_id=paper_id,
                        natural_key=f"auto:field-evidence:{natural_key}",
                        arm_id=(affected_arms[0] if affected_arms else None),
                        outcome_id=(
                            entity_id if link.entity_type == "outcome" else None
                        ),
                        reason_code="content_conflict_field_evidence",
                        status="conflict",
                        field_name=link.field_name,
                        notes=(
                            "Changed content retained for the same "
                            "field-evidence identity."
                        ),
                    )
                    if tag not in review_tags:
                        review_tags.append(tag)
                if link.entity_type in {"arm", "outcome"}:
                    experiment_id = (
                        entity_id
                        if link.entity_type == "arm"
                        else arm_ids[outcome_records[link.entity_id].arm_id]
                    )
                    connection.execute(
                        """
                        INSERT INTO field_verification (
                            experiment_id, field_name, evidence_id,
                            verification_status, notes, verified_at
                        )
                        SELECT ?, ?, ?, ?, ?, ?
                        WHERE NOT EXISTS (
                            SELECT 1 FROM field_verification
                            WHERE experiment_id = ? AND field_name = ?
                              AND evidence_id = ? AND verification_status = ?
                        )
                        """,
                        (
                            experiment_id,
                            link.field_name,
                            evidence_id,
                            link.verification_status,
                            link.notes,
                            _utc_now(),
                            experiment_id,
                            link.field_name,
                            evidence_id,
                            link.verification_status,
                        ),
                    )

        for review in bundle.reviews:
            _store_explicit_review(
                connection,
                review,
                bundle,
                paper_id,
                arm_ids,
                outcome_ids,
                evidence_ids,
            )

        for (stored_tag,) in connection.execute(
            """
            SELECT review_tag FROM import_review
            WHERE paper_id = ?
            ORDER BY import_review_id
            """,
            (paper_id,),
        ):
            if stored_tag not in review_tags:
                review_tags.append(stored_tag)

        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
    except BaseException:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise

    return PaperImportResult(
        inserted=counters.inserted,
        unchanged=counters.unchanged,
        conflicts=counters.conflicts,
        quarantined=sum(
            review.status == "quarantined" for review in bundle.reviews
        ),
        review_tags=tuple(review_tags),
    )


__all__ = ["PaperImportResult", "import_bundle"]
