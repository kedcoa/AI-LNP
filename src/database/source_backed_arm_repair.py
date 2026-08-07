"""Fail-closed projection of source-backed arm corrections into SQLite."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from src.database.readiness import evaluate_readiness
from src.database.source_fact_import import (
    FactProjectionRecord,
    SourceArtifactRecord,
    SourceFactEvidenceRecord,
    SourceFactRecord,
    import_source_facts,
)
from src.database.status import evaluate_arm_status, evaluate_eligibility


SCHEMA_VERSION = "source-backed-arm-repair/v1"
SAFE_EXPERIMENT_FIELDS = {
    "cell_type",
    "cell_source",
    "tissue_or_organ",
    "intended_target_cell",
    "target_or_recipient_organ",
    "observed_transfected_cell",
    "species",
    "disease_model",
    "in_vitro_in_vivo",
    "payload_type",
    "payload_name",
    "payload_encoded_product",
    "payload_molecular_target",
    "reporter",
    "dose",
    "dose_unit",
    "route",
    "timepoint",
    "timepoint_unit",
    "assay",
    "comparator_type",
    "comparator_description",
    "protocol_reference",
    "experiment_notes",
}


@dataclass(frozen=True)
class RepairResult:
    repairs: int
    updated_fields: int
    evidence_records: int
    field_evidence_links: int
    source_facts: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _source_text(path: Path) -> str:
    if path.suffix.casefold() in {".xml", ".nxml"}:
        return " ".join("".join(ET.parse(path).getroot().itertext()).split())
    if path.suffix.casefold() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        strings: list[str] = []

        def collect(value: object) -> None:
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(payload)
        return " ".join(strings)
    return path.read_text(encoding="utf-8")


def _source_path(raw_path: object, source_root: Path | None) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("source_path must be a non-empty string")
    path = Path(raw_path)
    if not path.is_absolute():
        if source_root is None:
            raise ValueError("relative source_path requires source_root")
        path = source_root / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _validate_fields(fields: Mapping[str, object], label: str) -> None:
    unknown = set(fields) - SAFE_EXPERIMENT_FIELDS
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {sorted(unknown)}")


def _find_or_create_evidence(
    connection: sqlite3.Connection,
    *,
    paper_id: int,
    experiment_id: int,
    excerpt: str,
    location: str,
) -> tuple[int, bool]:
    row = connection.execute(
        """
        SELECT evidence_id FROM evidence
        WHERE paper_id=? AND experiment_id=?
          AND field_name='source_backed_arm_context'
          AND evidence_text=? AND section_name=?
          AND extraction_method='text_extraction'
        """,
        (paper_id, experiment_id, excerpt, location),
    ).fetchone()
    if row is not None:
        return int(row[0]), False
    evidence_id = int(connection.execute(
        """
        INSERT INTO evidence (
            paper_id,experiment_id,field_name,evidence_text,
            evidence_location_type,section_name,extraction_method,
            extraction_confidence,evidence_review_status
        ) VALUES (?,?,'source_backed_arm_context',?,'other',?,
                  'text_extraction','high','automatically_validated')
        """,
        (paper_id, experiment_id, excerpt, location),
    ).lastrowid)
    return evidence_id, True


def _link_field_evidence(
    connection: sqlite3.Connection,
    *,
    paper_id: int,
    experiment_id: int,
    repair_id: str,
    field_name: str,
    evidence_id: int,
) -> bool:
    natural_key = f"source-backed-repair:{repair_id}:{field_name}"
    content_json = json.dumps(
        {
            "evidence_id": evidence_id,
            "field_name": field_name,
            "repair_id": repair_id,
            "verification_status": "automatically_validated",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    content_sha256 = _sha256_bytes(content_json.encode("utf-8"))
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO import_field_evidence (
            paper_id,entity_type,entity_id,field_name,evidence_id,
            verification_status,notes,natural_key,content_sha256,content_json
        ) VALUES (?,'arm',?,?,?,'automatically_validated',?,?,?,?)
        """,
        (
            paper_id,
            experiment_id,
            field_name,
            evidence_id,
            "Exact local full-text excerpt projected by deterministic repair.",
            natural_key,
            content_sha256,
            content_json,
        ),
    )
    return cursor.rowcount == 1


def _record_field_verification(
    connection: sqlite3.Connection,
    *,
    experiment_id: int,
    field_name: str,
    evidence_id: int,
) -> None:
    exists = connection.execute(
        """
        SELECT 1 FROM field_verification
        WHERE experiment_id=? AND field_name=? AND evidence_id=?
          AND verification_status='automatically_validated'
        """,
        (experiment_id, field_name, evidence_id),
    ).fetchone()
    if exists is None:
        connection.execute(
            """
            INSERT INTO field_verification (
                experiment_id,field_name,evidence_id,verification_status,
                notes,verified_at
            ) VALUES (?,?,?,'automatically_validated',?,?)
            """,
            (
                experiment_id,
                field_name,
                evidence_id,
                "Exact excerpt verified against local full text.",
                _utc_now(),
            ),
        )


def _artifact(
    path: Path,
    paper_id: str,
    source_root: Path | None,
) -> SourceArtifactRecord:
    logical_path = str(path)
    if source_root is not None:
        try:
            logical_path = str(path.relative_to(source_root.resolve()))
        except ValueError:
            pass
    return SourceArtifactRecord(
        paper_id=paper_id,
        logical_path=logical_path,
        sha256=_sha256_file(path),
        role="source_document",
        schema_family="full_text_source",
        validation_status="validated",
        contributes_facts=True,
        contributes_evidence=True,
        pipeline_name="source_backed_arm_repair",
        pipeline_version="v1",
    )


def apply_repair_manifest(
    connection: sqlite3.Connection,
    manifest: Mapping[str, object],
    *,
    source_root: Path | None = None,
) -> RepairResult:
    """Apply evidence-covered arm repairs atomically and idempotently."""

    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported source-backed repair schema")
    repairs = manifest.get("repairs")
    if not isinstance(repairs, list):
        raise ValueError("repairs must be a list")
    original_row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    updated_fields = 0
    evidence_records = 0
    field_links = 0
    source_facts = 0
    connection.execute("SAVEPOINT source_backed_arm_repair")
    try:
        for raw_repair in repairs:
            repair = _mapping(raw_repair, "repair")
            repair_id = str(repair.get("repair_id") or "").strip()
            source_paper_id = str(repair.get("paper_id") or "").strip()
            experiment_id = repair.get("experiment_id")
            arm_record_id = str(repair.get("arm_record_id") or "").strip()
            if not repair_id or not source_paper_id:
                raise ValueError("repair_id and paper_id are required")
            if not isinstance(experiment_id, int):
                if not arm_record_id:
                    raise ValueError(
                        "integer experiment_id or stable arm_record_id is required"
                    )
                identities = connection.execute(
                    """
                    SELECT DISTINCT identity.entity_id
                    FROM import_record_identity AS identity
                    JOIN paper USING(paper_id)
                    WHERE paper.source_paper_id=?
                      AND identity.entity_type='experiment'
                      AND json_extract(
                            identity.content_json,'$.record.record_id'
                          )=?
                    """,
                    (source_paper_id, arm_record_id),
                ).fetchall()
                if len(identities) != 1:
                    raise ValueError(
                        f"stable arm identity mismatch for {repair_id}"
                    )
                experiment_id = int(identities[0][0])
            row = connection.execute(
                """
                SELECT experiment.*,paper.source_paper_id
                FROM experiment JOIN paper USING(paper_id)
                WHERE experiment.experiment_id=? AND paper.source_paper_id=?
                """,
                (experiment_id, source_paper_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"arm identity mismatch for {repair_id}")
            expected = _mapping(repair.get("expected", {}), f"{repair_id}.expected")
            updates = _mapping(repair.get("updates"), f"{repair_id}.updates")
            _validate_fields(expected, f"{repair_id}.expected")
            _validate_fields(updates, f"{repair_id}.updates")
            if not updates:
                raise ValueError(f"{repair_id} has no updates")
            for field_name, expected_value in expected.items():
                current = row[field_name]
                desired = updates.get(field_name, object())
                if current != expected_value and current != desired:
                    raise ValueError(
                        f"arm identity mismatch for {repair_id}: {field_name}"
                    )
            evidence_items = repair.get("evidence")
            if not isinstance(evidence_items, list) or not evidence_items:
                raise ValueError(f"{repair_id}.evidence must be a non-empty list")
            field_evidence: dict[str, int] = {}
            source_paths: set[Path] = set()
            for raw_evidence in evidence_items:
                evidence = _mapping(raw_evidence, f"{repair_id}.evidence")
                path = _source_path(evidence.get("source_path"), source_root)
                source_paths.add(path)
                excerpt = str(evidence.get("excerpt") or "").strip()
                location = str(evidence.get("location") or "").strip()
                fields = evidence.get("fields")
                if not excerpt or not location or not isinstance(fields, list) or not fields:
                    raise ValueError(f"{repair_id} has malformed evidence")
                if _normalized(excerpt) not in _normalized(_source_text(path)):
                    raise ValueError(
                        f"excerpt was not found in local source for {repair_id}"
                    )
                evidence_id, inserted = _find_or_create_evidence(
                    connection,
                    paper_id=int(row["paper_id"]),
                    experiment_id=experiment_id,
                    excerpt=excerpt,
                    location=location,
                )
                evidence_records += int(inserted)
                for field_name in fields:
                    if field_name not in updates:
                        raise ValueError(
                            f"{repair_id} evidence names a field without an update: {field_name}"
                        )
                    if field_name in field_evidence:
                        raise ValueError(
                            f"{repair_id} has duplicate evidence coverage for {field_name}"
                        )
                    field_evidence[field_name] = evidence_id
            if set(field_evidence) != set(updates):
                missing = sorted(set(updates) - set(field_evidence))
                raise ValueError(f"{repair_id} lacks evidence for fields: {missing}")
            if len(source_paths) != 1:
                raise ValueError(f"{repair_id} must use exactly one source artifact")

            facts: list[SourceFactRecord] = []
            source_path = next(iter(source_paths))
            for field_name, desired in updates.items():
                evidence_id = field_evidence[field_name]
                if row[field_name] != desired:
                    connection.execute(
                        f"UPDATE experiment SET {field_name}=? WHERE experiment_id=?",
                        (desired, experiment_id),
                    )
                    updated_fields += 1
                if _link_field_evidence(
                    connection,
                    paper_id=int(row["paper_id"]),
                    experiment_id=experiment_id,
                    repair_id=repair_id,
                    field_name=field_name,
                    evidence_id=evidence_id,
                ):
                    field_links += 1
                _record_field_verification(
                    connection,
                    experiment_id=experiment_id,
                    field_name=field_name,
                    evidence_id=evidence_id,
                )
                canonical_json = json.dumps(
                    desired, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                fact_hash = _sha256_bytes(
                    f"{source_paper_id}|{experiment_id}|{field_name}|{canonical_json}".encode(
                        "utf-8"
                    )
                )
                facts.append(SourceFactRecord(
                    json_path=f"source-backed-repair:{repair_id}.{field_name}",
                    source_record_key=repair_id,
                    record_kind="source_backed_arm_field",
                    source_context_key=repair_id,
                    subject_type="arm",
                    subject_key=f"{source_paper_id}:{experiment_id}",
                    field_name=field_name,
                    raw_value=desired,
                    canonical_value=desired,
                    fact_identity_sha256=fact_hash,
                    import_disposition="projected",
                    projections=(FactProjectionRecord(
                        "arm", experiment_id, field_name, fact_hash
                    ),),
                    evidence=(SourceFactEvidenceRecord(
                        source_evidence_key=f"{repair_id}:{field_name}",
                        resolution_status="resolved",
                        evidence_id=evidence_id,
                    ),),
                ))
            imported = import_source_facts(
                connection,
                _artifact(source_path, source_paper_id, source_root),
                facts,
            )
            source_facts += imported.inserted
            evaluate_arm_status(connection, experiment_id)
            evaluate_eligibility(connection, experiment_id, "nearest_neighbor")
            evaluate_readiness(connection, experiment_id)
        connection.execute("RELEASE SAVEPOINT source_backed_arm_repair")
    except BaseException:
        connection.execute("ROLLBACK TO SAVEPOINT source_backed_arm_repair")
        connection.execute("RELEASE SAVEPOINT source_backed_arm_repair")
        connection.row_factory = original_row_factory
        raise
    connection.row_factory = original_row_factory
    return RepairResult(
        repairs=len(repairs),
        updated_fields=updated_fields,
        evidence_records=evidence_records,
        field_evidence_links=field_links,
        source_facts=source_facts,
    )


__all__ = ["RepairResult", "apply_repair_manifest"]
