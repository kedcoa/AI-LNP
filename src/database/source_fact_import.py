"""Transaction-safe import of immutable source facts and their projections."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Literal, Sequence


Disposition = Literal["projected", "unresolved", "quarantined", "rejected"]


@dataclass(frozen=True)
class SourceArtifactRecord:
    paper_id: str
    logical_path: str
    sha256: str
    role: str
    schema_family: str
    validation_status: str
    contributes_facts: bool
    contributes_evidence: bool
    pipeline_name: str | None = None
    pipeline_version: str | None = None


@dataclass(frozen=True)
class FactProjectionRecord:
    entity_type: str
    entity_id: int
    field_name: str
    canonical_fact_sha256: str
    projection_status: str = "active"


@dataclass(frozen=True)
class SourceFactEvidenceRecord:
    source_evidence_key: str
    resolution_status: str
    evidence_id: int | None = None
    resolution_reason: str | None = None


@dataclass(frozen=True)
class SourceFactRecord:
    json_path: str
    source_record_key: str
    record_kind: str
    subject_type: str
    subject_key: str
    field_name: str
    raw_value: object
    fact_identity_sha256: str
    import_disposition: Disposition
    disposition_reason: str | None = None
    projections: tuple[FactProjectionRecord, ...] = field(default_factory=tuple)
    evidence: tuple[SourceFactEvidenceRecord, ...] = field(default_factory=tuple)
    canonical_value: object | None = None
    source_context_key: str | None = None


@dataclass(frozen=True)
class SourceFactImportResult:
    artifact_id: int
    source_count: int
    accounted_count: int
    inserted: int
    unchanged: int


def _json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def import_source_facts(
    connection: sqlite3.Connection,
    artifact: SourceArtifactRecord,
    facts: Sequence[SourceFactRecord],
) -> SourceFactImportResult:
    """Import one artifact atomically; identical reimports are idempotent."""

    paper = connection.execute(
        "SELECT paper_id FROM paper WHERE source_paper_id = ?",
        (artifact.paper_id,),
    ).fetchone()
    if paper is None:
        raise KeyError(f"unknown source paper: {artifact.paper_id}")
    paper_id = int(paper[0])
    savepoint = "source_fact_artifact_import"
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        connection.execute(
            """
            INSERT OR IGNORE INTO source_artifact (
                paper_id, logical_path, sha256, role, schema_family,
                pipeline_name, pipeline_version, validation_status,
                contributes_facts, contributes_evidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                artifact.logical_path,
                artifact.sha256,
                artifact.role,
                artifact.schema_family,
                artifact.pipeline_name,
                artifact.pipeline_version,
                artifact.validation_status,
                int(artifact.contributes_facts),
                int(artifact.contributes_evidence),
            ),
        )
        artifact_id = int(
            connection.execute(
                """
                SELECT source_artifact_id FROM source_artifact
                WHERE paper_id = ? AND sha256 = ? AND role = ?
                """,
                (paper_id, artifact.sha256, artifact.role),
            ).fetchone()[0]
        )
        inserted = 0
        unchanged = 0
        for fact in facts:
            raw_json = _json(fact.raw_value)
            canonical_json = (
                None if fact.canonical_value is None else _json(fact.canonical_value)
            )
            existing = connection.execute(
                """
                SELECT source_fact_id, raw_value_json, canonical_value_json,
                       fact_identity_sha256, import_disposition,
                       disposition_reason
                FROM source_fact
                WHERE source_artifact_id = ? AND json_path = ?
                  AND source_record_key = ? AND field_name = ?
                """,
                (
                    artifact_id,
                    fact.json_path,
                    fact.source_record_key,
                    fact.field_name,
                ),
            ).fetchone()
            if existing is not None:
                expected = (
                    raw_json,
                    canonical_json,
                    fact.fact_identity_sha256,
                    fact.import_disposition,
                    fact.disposition_reason,
                )
                if tuple(existing[1:]) != expected:
                    raise ValueError(
                        "changed source fact shares one stable source identity: "
                        f"{artifact.logical_path}{fact.json_path}"
                    )
                unchanged += 1
                continue

            initial_disposition = (
                "unresolved"
                if fact.import_disposition == "projected"
                else fact.import_disposition
            )
            initial_reason = (
                "pending projection"
                if fact.import_disposition == "projected"
                else fact.disposition_reason
            )
            fact_id = int(
                connection.execute(
                    """
                    INSERT INTO source_fact (
                        source_artifact_id, paper_id, json_path,
                        source_record_key, record_kind, source_context_key,
                        subject_type, subject_key, field_name, raw_value_json,
                        canonical_value_json, fact_identity_sha256,
                        import_disposition, disposition_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id,
                        paper_id,
                        fact.json_path,
                        fact.source_record_key,
                        fact.record_kind,
                        fact.source_context_key,
                        fact.subject_type,
                        fact.subject_key,
                        fact.field_name,
                        raw_json,
                        canonical_json,
                        fact.fact_identity_sha256,
                        initial_disposition,
                        initial_reason,
                    ),
                ).lastrowid
            )
            for evidence in fact.evidence:
                connection.execute(
                    """
                    INSERT INTO source_fact_evidence (
                        source_fact_id, source_evidence_key, evidence_id,
                        resolution_status, resolution_reason
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        fact_id,
                        evidence.source_evidence_key,
                        evidence.evidence_id,
                        evidence.resolution_status,
                        evidence.resolution_reason,
                    ),
                )
            for projection in fact.projections:
                connection.execute(
                    """
                    INSERT INTO fact_projection (
                        source_fact_id, paper_id, entity_type, entity_id,
                        field_name, canonical_fact_sha256, projection_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact_id,
                        paper_id,
                        projection.entity_type,
                        projection.entity_id,
                        projection.field_name,
                        projection.canonical_fact_sha256,
                        projection.projection_status,
                    ),
                )
            if fact.import_disposition == "projected":
                if not fact.projections:
                    raise ValueError("projected source fact requires a projection")
                connection.execute(
                    """
                    UPDATE source_fact
                    SET import_disposition = 'projected', disposition_reason = ?
                    WHERE source_fact_id = ?
                    """,
                    (fact.disposition_reason, fact_id),
                )
            inserted += 1
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
    except BaseException:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise

    return SourceFactImportResult(
        artifact_id=artifact_id,
        source_count=len(facts),
        accounted_count=inserted + unchanged,
        inserted=inserted,
        unchanged=unchanged,
    )
