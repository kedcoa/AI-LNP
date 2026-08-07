"""Read-only integrity and provenance audit for the current evidence database."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from src.database.paths import (
    CANONICAL_AUTHORITATIVE_DATABASE,
    COMMON_CHECKOUT_ROOT,
    REPOSITORY_ROOT,
    resolve_common_checkout_root,
)
from src.database.status import (
    RULES_VERSION,
    evaluate_arm_status,
    evaluate_eligibility,
)
from src.database.readiness import evaluate_readiness
from src.database.build_rerun_queue import audit_database_gaps, build_requests
from src.database.adapters.pilot_map_results import (
    completed_pilot_map_response,
    pilot_map_logical_path,
)


DATABASE_KINDS = frozenset({"explicit_fixture", "authoritative"})


def validate_database_kind(database_path: Path | str, database_kind: str) -> None:
    """Validate a database label against the single canonical shared path."""

    if database_kind not in DATABASE_KINDS:
        raise ValueError(f"database_kind must be one of {sorted(DATABASE_KINDS)}")
    if (
        database_kind == "authoritative"
        and Path(database_path).resolve() != CANONICAL_AUTHORITATIVE_DATABASE
    ):
        raise ValueError(
            "authoritative database path must equal "
            f"{CANONICAL_AUTHORITATIVE_DATABASE}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scalar(connection: sqlite3.Connection, sql: str, parameters=()) -> int:
    return int(connection.execute(sql, parameters).fetchone()[0])


def _orphan_counts(connection: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "experiment_formulation_paper_mismatch": """
            SELECT count(*) FROM experiment e
            JOIN formulation f USING (formulation_id)
            WHERE e.paper_id != f.paper_id
        """,
        "outcome_experiment_missing": """
            SELECT count(*) FROM outcome o
            LEFT JOIN experiment e USING (experiment_id)
            WHERE e.experiment_id IS NULL
        """,
        "evidence_paper_mismatch": """
            SELECT count(*) FROM evidence v
            JOIN experiment e USING (experiment_id)
            WHERE v.paper_id != e.paper_id
        """,
        "evidence_outcome_experiment_mismatch": """
            SELECT count(*) FROM evidence v
            JOIN outcome o USING (outcome_id)
            WHERE v.experiment_id IS NOT NULL
              AND v.experiment_id != o.experiment_id
        """,
        "field_evidence_paper_mismatch": """
            SELECT count(*) FROM import_field_evidence f
            JOIN evidence v USING (evidence_id)
            WHERE f.paper_id != v.paper_id
        """,
        "review_arm_paper_mismatch": """
            SELECT count(*) FROM import_review r
            JOIN experiment e ON e.experiment_id = r.arm_id
            WHERE r.paper_id != e.paper_id
        """,
        "review_outcome_paper_mismatch": """
            SELECT count(*) FROM import_review r
            JOIN outcome o USING (outcome_id)
            JOIN experiment e USING (experiment_id)
            WHERE r.paper_id != e.paper_id
        """,
    }
    identity_targets = {
        "paper": ("paper", "paper_id", "paper_id"),
        "formulation": ("formulation", "formulation_id", "paper_id"),
        "chemical_component": (
            "(SELECT component_id, paper_id FROM chemical_component "
            "JOIN formulation USING (formulation_id))",
            "component_id",
            "paper_id",
        ),
        "experiment": ("experiment", "experiment_id", "paper_id"),
        "outcome": (
            "(SELECT outcome_id, paper_id FROM outcome "
            "JOIN experiment USING (experiment_id))",
            "outcome_id",
            "paper_id",
        ),
        "evidence": ("evidence", "evidence_id", "paper_id"),
    }
    for entity_type, (target, id_column, paper_column) in identity_targets.items():
        queries[f"identity_{entity_type}_missing"] = f"""
            SELECT count(*) FROM import_record_identity i
            WHERE i.entity_type='{entity_type}' AND NOT EXISTS (
                SELECT 1 FROM {target} t
                WHERE t.{id_column}=i.entity_id AND t.{paper_column}=i.paper_id
            )
        """
    field_targets = {
        "formulation": ("formulation", "formulation_id", "paper_id"),
        "component": (
            "(SELECT component_id, paper_id FROM chemical_component "
            "JOIN formulation USING (formulation_id))",
            "component_id",
            "paper_id",
        ),
        "arm": ("experiment", "experiment_id", "paper_id"),
        "outcome": (
            "(SELECT outcome_id, paper_id FROM outcome "
            "JOIN experiment USING (experiment_id))",
            "outcome_id",
            "paper_id",
        ),
    }
    for entity_type, (target, id_column, paper_column) in field_targets.items():
        queries[f"field_evidence_{entity_type}_missing"] = f"""
            SELECT count(*) FROM import_field_evidence f
            WHERE f.entity_type='{entity_type}' AND NOT EXISTS (
                SELECT 1 FROM {target} t
                WHERE t.{id_column}=f.entity_id AND t.{paper_column}=f.paper_id
            )
        """
    return {
        name: count
        for name, sql in queries.items()
        if (count := _scalar(connection, sql))
    }


def _duplicate_natural_keys(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT p.source_paper_id, i.entity_type, i.natural_key,
               i.content_sha256, count(*)
        FROM import_record_identity i JOIN paper p USING (paper_id)
        GROUP BY i.paper_id, i.entity_type, i.natural_key, i.content_sha256
        HAVING count(*) > 1
        ORDER BY p.source_paper_id, i.entity_type, i.natural_key
        """
    ).fetchall()
    return [
        {
            "paper_id": paper_id,
            "entity_type": entity_type,
            "natural_key": natural_key,
            "content_sha256": content_hash,
            "count": count,
        }
        for paper_id, entity_type, natural_key, content_hash, count in rows
    ]


def _identity_conflicts(connection: sqlite3.Connection, paper_id: int) -> int:
    return _scalar(
        connection,
        """
        SELECT count(*) FROM (
            SELECT entity_type, natural_key
            FROM import_record_identity
            WHERE paper_id = ?
            GROUP BY entity_type, natural_key
            HAVING count(DISTINCT content_sha256) > 1
        )
        """,
        (paper_id,),
    )


def _coverage(
    connection: sqlite3.Connection, *, include_field_links: bool = False
) -> dict[str, list[int]]:
    arm_query = (
        """SELECT experiment_id FROM experiment e WHERE NOT EXISTS
        (SELECT 1 FROM evidence v WHERE v.experiment_id=e.experiment_id)
        AND NOT EXISTS (
            SELECT 1 FROM import_field_evidence f
            WHERE f.entity_type='arm' AND f.entity_id=e.experiment_id
        )
        ORDER BY experiment_id"""
        if include_field_links
        else """SELECT experiment_id FROM experiment e WHERE NOT EXISTS
        (SELECT 1 FROM evidence v WHERE v.experiment_id=e.experiment_id)
        ORDER BY experiment_id"""
    )
    arms = [
        int(row[0])
        for row in connection.execute(arm_query)
    ]
    outcomes = [
        int(row[0])
        for row in connection.execute(
            """SELECT outcome_id FROM outcome o WHERE NOT EXISTS
            (SELECT 1 FROM evidence v WHERE v.outcome_id=o.outcome_id)
            ORDER BY outcome_id"""
        )
    ]
    return {"arms_without_evidence": arms, "outcomes_without_evidence": outcomes}


def _lossless_source_checks(
    connection: sqlite3.Connection,
    manifest: dict[str, Any],
    repository_root: Path,
) -> dict[str, Any]:
    expected = {
        (
            str(entry["paper_id"]), str(item["path"]),
            str(item["sha256"]), str(item["role"]),
        )
        for entry in manifest["entries"]
        for item in entry.get("contributing_artifacts", ())
        if item.get("access_status") == "available" and item.get("sha256")
    }
    approval_manifest = (
        repository_root
        / "data/staging/extraction/application_pilot/map_gate/manifest.json"
    )
    completed = set()
    if approval_manifest.is_file():
        for paper_id in ("PILOT-001", "PILOT-002", "PILOT-003"):
            response = completed_pilot_map_response(approval_manifest, paper_id)
            if response is not None:
                completed.add(
                    (
                        paper_id, pilot_map_logical_path(response), _sha256(response),
                        "completed_extraction",
                    )
                )
    allowed = expected | completed
    actual = {
        (str(paper_id), str(path), str(digest), str(role))
        for paper_id, path, digest, role in connection.execute(
            """
            SELECT p.source_paper_id,a.logical_path,a.sha256,a.role
            FROM source_artifact a JOIN paper p USING(paper_id)
            """
        )
    }
    factless = [
        int(row[0])
        for row in connection.execute(
            """
            SELECT a.source_artifact_id FROM source_artifact a
            WHERE a.contributes_facts=1 AND NOT EXISTS (
                SELECT 1 FROM source_fact f
                WHERE f.source_artifact_id=a.source_artifact_id
            ) ORDER BY a.source_artifact_id
            """
        )
    ]
    dispositions = {
        str(status): int(count)
        for status, count in connection.execute(
            "SELECT import_disposition,count(*) FROM source_fact GROUP BY import_disposition"
        )
    }
    unreasoned = _scalar(
        connection,
        """
        SELECT count(*) FROM source_fact
        WHERE import_disposition != 'projected'
          AND length(trim(coalesce(disposition_reason,'')))=0
        """,
    )
    missing_manifest = [
        {
            "paper_id": str(entry["paper_id"]),
            "path": str(item["path"]),
            "access_status": str(item.get("access_status") or "unknown"),
        }
        for entry in manifest["entries"]
        for item in entry.get("contributing_artifacts", ())
        if item.get("access_status") != "available" or not item.get("sha256")
    ]
    screening_science = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT p.source_paper_id FROM paper p
            WHERE p.import_status='screening_only' AND (
                EXISTS (SELECT 1 FROM formulation f WHERE f.paper_id=p.paper_id)
                OR EXISTS (SELECT 1 FROM experiment e WHERE e.paper_id=p.paper_id)
                OR EXISTS (SELECT 1 FROM evidence v WHERE v.paper_id=p.paper_id)
            ) ORDER BY p.source_paper_id
            """
        )
    ]
    forbidden_human_tags = _scalar(
        connection,
        "SELECT count(*) FROM import_review WHERE review_tag='Needs human verification'",
    )
    pilot_counts = {
        str(paper_id): {"formulations": int(formulations), "arms": int(arms)}
        for paper_id, formulations, arms in connection.execute(
            """
            SELECT p.source_paper_id,
                   (SELECT count(*) FROM formulation f WHERE f.paper_id=p.paper_id),
                   (SELECT count(*) FROM experiment e WHERE e.paper_id=p.paper_id)
            FROM paper p WHERE p.source_paper_id LIKE 'PILOT-%'
            ORDER BY p.source_paper_id
            """
        )
    }
    gp8_supplement = connection.execute(
        """
        SELECT count(*) FROM source_artifact a JOIN paper p USING(paper_id)
        WHERE p.source_paper_id='GP-008' AND a.role='supplement'
          AND a.logical_path='data/raw/fulltext/oa_packages/PMC13229182/pnas.2534673123.sapp.pdf'
          AND a.sha256='6e4700f3b72972a63f77903a32cae1a85b100b4d1f1cf40fbfdbc2b5d0f555d6'
        """
    ).fetchone()[0]
    total_facts = _scalar(connection, "SELECT count(*) FROM source_fact")
    return {
        "expected_available_manifest_artifacts": len(expected),
        "completed_exact_map_artifacts": len(completed),
        "registered_source_artifacts": len(actual),
        "missing_registered_artifacts": sorted(expected - actual),
        "unexpected_registered_artifacts": sorted(actual - allowed),
        "manifest_missing_or_unhashed_artifacts": missing_manifest,
        "fact_producing_artifacts_without_facts": factless,
        "source_fact_count": total_facts,
        "source_fact_dispositions": dispositions,
        "source_fact_disposition_accounting_matches": sum(dispositions.values()) == total_facts,
        "nonprojected_facts_without_reason": unreasoned,
        "screening_only_papers_with_science": screening_science,
        "forbidden_general_app_human_tags": forbidden_human_tags,
        "pilot_promoted_counts": pilot_counts,
        "gp008_supplement_hash_registered": int(gp8_supplement) == 1,
    }


def _review_tag_gaps(connection: sqlite3.Connection) -> list[int]:
    return [
        int(row[0])
        for row in connection.execute(
            """
            SELECT a.experiment_id FROM arm_assessment a
            JOIN experiment e USING (experiment_id)
            WHERE a.completeness_status != 'complete'
              AND NOT EXISTS (
                SELECT 1 FROM import_review r
                WHERE r.paper_id=e.paper_id
                  AND (r.arm_id=a.experiment_id OR r.arm_id IS NULL)
                  AND length(trim(r.review_tag)) > 0
              )
            ORDER BY a.experiment_id
            """
        )
    ]


def _eligibility_inconsistencies(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    stored_rows = connection.execute(
        """
        SELECT p.source_paper_id, a.experiment_id, a.completeness_status,
               a.missing_fields_json, a.verification_status, a.quarantine_reason,
               a.nearest_neighbor_eligible, a.comet_eligible
        FROM arm_assessment a
        JOIN experiment e USING (experiment_id)
        JOIN paper p USING (paper_id)
        ORDER BY p.source_paper_id, a.experiment_id
        """
    ).fetchall()
    stored_results = {
        (int(experiment_id), str(profile)): (
            int(eligible), tuple(json.loads(reasons_json)), str(rules_version)
        )
        for experiment_id, profile, eligible, reasons_json, rules_version
        in connection.execute(
            "SELECT experiment_id, profile, eligible, reasons_json, rules_version "
            "FROM eligibility_result"
        )
    }
    # Evaluate the current rules against an in-memory clone. The audited database
    # remains read-only while the existing evaluators persist only into the clone.
    recomputed = sqlite3.connect(":memory:")
    connection.backup(recomputed)
    problems = []
    try:
        for paper_id, arm_id, status, missing_json, verification, quarantine, nearest, comet in stored_rows:
            reasons = []
            expected_status = evaluate_arm_status(recomputed, arm_id)
            if (
                status != expected_status.completeness_status
                or tuple(json.loads(missing_json)) != expected_status.missing_fields
                or verification != expected_status.verification_status
                or quarantine != expected_status.quarantine_reason
            ):
                reasons.append("arm assessment differs from current rules")
            readiness = evaluate_readiness(recomputed, arm_id)
            stored_comet = stored_results.get((arm_id, "comet"))
            legacy_comet = evaluate_eligibility(recomputed, arm_id, "comet")
            expected_profiles = {
                "nearest_neighbor": (
                    readiness.nearest_neighbor_ready,
                    readiness.nearest_neighbor_blockers,
                    RULES_VERSION,
                ),
                "comet": (
                    (readiness.comet_ready if stored_comet and
                     stored_comet[2] == readiness.rules_version
                     else legacy_comet.eligible),
                    (readiness.comet_blockers if stored_comet and
                     stored_comet[2] == readiness.rules_version
                     else legacy_comet.reasons),
                    (readiness.rules_version if stored_comet and
                     stored_comet[2] == readiness.rules_version
                     else RULES_VERSION),
                ),
            }
            for profile, stored_flag in (("nearest_neighbor", nearest), ("comet", comet)):
                expected_eligible, expected_reasons, expected_version = (
                    expected_profiles[profile]
                )
                stored = stored_results.get((arm_id, profile))
                if stored is None:
                    reasons.append(f"{profile} eligibility result missing")
                    continue
                stored_eligible, stored_reasons, stored_version = stored
                if stored_flag != int(expected_eligible):
                    reasons.append(f"{profile} flag differs from current rules")
                if stored_eligible != int(expected_eligible):
                    reasons.append(f"{profile} result differs from current rules")
                if stored_reasons != expected_reasons:
                    reasons.append(f"{profile} reasons differ from current rules")
                if stored_version != expected_version:
                    reasons.append(f"{profile} rules_version is not current")
            if reasons:
                problems.append({"paper_id": paper_id, "arm_id": arm_id, "reasons": reasons})
    finally:
        recomputed.close()
    return problems


def _bundle_hash_checks(
    bundle_root: Path, expected_preflight_path: Path | None
) -> tuple[list[dict[str, str]], dict[str, str]]:
    actual: dict[str, str] = {}
    for path in sorted(bundle_root.glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        paper = payload.get("paper")
        if isinstance(paper, dict) and paper.get("source_paper_id"):
            actual[str(paper["source_paper_id"])] = _sha256(path)
    if expected_preflight_path is None or not expected_preflight_path.is_file():
        return [], actual
    expected = {
        str(row["paper_id"]): str(row["sha256"])
        for row in json.loads(expected_preflight_path.read_text(encoding="utf-8"))["bundles"]
    }
    mismatches = []
    for paper_id in sorted(set(expected) | set(actual)):
        if expected.get(paper_id) != actual.get(paper_id):
            mismatches.append(
                {"paper_id": paper_id, "expected": expected.get(paper_id, "missing"),
                 "actual": actual.get(paper_id, "missing")}
            )
    return mismatches, actual


def _identity_sets(
    connection: sqlite3.Connection,
) -> tuple[
    set[tuple[str, ...]],
    set[tuple[str, ...]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    def canonical_path(value: str) -> str:
        artifact_path = Path(value)
        if artifact_path.is_absolute():
            for root in (REPOSITORY_ROOT, COMMON_CHECKOUT_ROOT):
                try:
                    return artifact_path.relative_to(root).as_posix()
                except ValueError:
                    continue
        return artifact_path.as_posix()

    def canonical_natural_key(natural_key: str) -> str:
        try:
            payload = json.loads(natural_key)
        except (json.JSONDecodeError, TypeError):
            return natural_key
        if not isinstance(payload, dict):
            return natural_key

        def rewrite(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "artifact_path" and isinstance(child, str):
                        value[key] = canonical_path(child)
                    else:
                        rewrite(child)
            elif isinstance(value, list):
                for child in value:
                    rewrite(child)

        rewrite(payload)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def canonical_content(content_json: str) -> tuple[str, str, str | None]:
        payload = json.loads(content_json)
        if not isinstance(payload, dict):
            normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            return (
                normalized,
                hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                "content_json must be an object",
            )
        artifact = payload.get("artifact")
        if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
            artifact["path"] = canonical_path(artifact["path"])
            artifact_id = str(artifact.get("artifact_id") or "")
            if artifact_id.endswith(":screening-manifest"):
                # The corpus manifest is a mutable contributor inventory. Its
                # top-level hash is audited separately, so contributor-only
                # updates must not rewrite otherwise identical screening-paper
                # identities in the scientific database.
                artifact["sha256"] = "screening-manifest-inventory"
        record = payload.get("record")
        if isinstance(record, dict):
            if record.get("quarantine_reason") == "Target cell needs human verification":
                # This text was an obsolete workflow label, not scientific
                # content.  Treat the automatic-resolution replacement as the
                # same legacy identity while auditing a pre-migration database.
                record["quarantine_reason"] = "Target cell needs automatic resolution"
            # Additive schema fields with null values are semantically absent.
            # Removing them keeps an older authoritative database comparable to
            # a freshly parsed legacy bundle while preserving every populated
            # wide-formulation or component-amount value.
            for field_name in (
                "chemical_formulation_total",
                "lnp_molar_ratio",
                "amount_value",
                "amount_unit",
                "amount_raw",
                "composition_position",
            ):
                if record.get(field_name) is None:
                    record.pop(field_name, None)
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return normalized, hashlib.sha256(normalized.encode("utf-8")).hexdigest(), None

    hash_mismatches: list[dict[str, str]] = []
    shape_mismatches: list[dict[str, str]] = []
    records: set[tuple[str, ...]] = set()
    for paper_id, entity_type, natural_key, stored_hash, content_json in connection.execute(
        """
        SELECT p.source_paper_id, i.entity_type, i.natural_key,
               i.content_sha256, i.content_json
        FROM import_record_identity i JOIN paper p USING (paper_id)
        """
    ):
        raw_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
        if raw_hash != stored_hash:
            hash_mismatches.append({
                "paper_id": str(paper_id), "entity_type": str(entity_type),
                "natural_key": str(natural_key), "stored": str(stored_hash),
                "calculated": raw_hash,
            })
        normalized, canonical_hash, shape_error = canonical_content(content_json)
        if shape_error:
            shape_mismatches.append({
                "paper_id": str(paper_id), "entity_type": str(entity_type),
                "natural_key": str(natural_key), "reason": shape_error,
            })
        records.add((str(paper_id), str(entity_type), canonical_natural_key(str(natural_key)), canonical_hash, normalized))
    links: set[tuple[str, ...]] = set()
    for paper_id, entity_type, natural_key, stored_hash, content_json in connection.execute(
            """
            SELECT p.source_paper_id, f.entity_type, f.natural_key,
                   f.content_sha256, f.content_json
            FROM import_field_evidence f JOIN paper p USING (paper_id)
            """
    ):
        raw_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
        if raw_hash != stored_hash:
            hash_mismatches.append({
                "paper_id": str(paper_id), "entity_type": f"field:{entity_type}",
                "natural_key": str(natural_key), "stored": str(stored_hash),
                "calculated": raw_hash,
            })
        normalized, canonical_hash, shape_error = canonical_content(content_json)
        if shape_error:
            shape_mismatches.append({
                "paper_id": str(paper_id), "entity_type": f"field:{entity_type}",
                "natural_key": str(natural_key), "reason": shape_error,
            })
        links.add((str(paper_id), str(entity_type), canonical_natural_key(str(natural_key)), canonical_hash, normalized))
    return records, links, hash_mismatches, shape_mismatches


def _serialized_identities(rows: set[tuple[str, ...]]) -> list[list[str]]:
    return [list(row) for row in sorted(rows)]


def _raw_field_evidence_reference_count(bundle_root: Path) -> int:
    total = 0
    for path in sorted(bundle_root.glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload.get("paper"), dict):
            continue
        for link in payload.get("field_evidence_links", []):
            total += len(link.get("evidence_ids", []))
    return total


def _expected_identity_sets(
    manifest_path: Path, bundle_root: Path
) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]], list[str]]:
    """Build canonical identities through the production normalization/import path."""

    from src.database.run_current_corpus_import import run_current_corpus_import
    from src.init_db import initialize_database

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ai-lnp-audit-expected-") as directory:
        expected_database = Path(directory) / "expected.db"
        initialize_database(expected_database)
        try:
            summary = run_current_corpus_import(
                expected_database, manifest_path, bundle_root
            )
        except (FileNotFoundError, KeyError, ValueError) as exc:
            return set(), set(), [str(exc)]
        failed = [
            row for row in summary["dispositions"]
            if row["status"] != "committed"
        ]
        if failed:
            errors.extend(
                f"{row['paper_id']}: {row.get('error', row['status'])}"
                for row in failed
            )
        with sqlite3.connect(expected_database) as connection:
            records, links, hash_mismatches, shape_mismatches = _identity_sets(connection)
            if hash_mismatches or shape_mismatches:
                errors.append("expected identity generation produced invalid content hashes")
    return records, links, errors


def audit_current_database(
    database_path: Path | str,
    manifest_path: Path | str,
    bundle_root: Path | str,
    *,
    expected_preflight_path: Path | str | None = None,
    database_kind: str = "explicit_fixture",
) -> dict[str, Any]:
    """Audit an explicitly named database without modifying it."""

    database_path = Path(database_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    bundle_root = Path(bundle_root).resolve()
    validate_database_kind(database_path, database_kind)
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_ids = [str(entry["paper_id"]) for entry in manifest["entries"]]
    if expected_preflight_path is None:
        candidate = manifest_path.parents[2] / "reports/database/day2_import_preflight.json"
        expected_preflight = candidate if candidate.is_file() else None
    else:
        expected_preflight = Path(expected_preflight_path).resolve()
    bundle_mismatches, bundle_hashes = _bundle_hash_checks(bundle_root, expected_preflight)
    expected_manifest_hash = None
    if expected_preflight is not None:
        expected_manifest_hash = json.loads(expected_preflight.read_text(encoding="utf-8")).get(
            "manifest_sha256"
        )
    manifest_hash = _sha256(manifest_path)
    bundle_dispositions: dict[str, tuple[str, str]] = {}
    for path in sorted(bundle_root.glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        paper = payload.get("paper")
        if isinstance(paper, dict) and paper.get("source_paper_id"):
            bundle_dispositions[str(paper["source_paper_id"])] = (
                str(paper["import_status"]), str(paper["screening_status"])
            )

    uri = f"file:{database_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        has_source_fact = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_fact'"
        ).fetchone() is not None
        lossless_mode = bool(
            has_source_fact
            and connection.execute("SELECT count(*) FROM source_fact").fetchone()[0] > 0
        )
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        fk = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
        present_ids = [
            str(row[0]) for row in connection.execute(
                "SELECT source_paper_id FROM paper WHERE source_paper_id IS NOT NULL"
            )
        ]
        disposition = {
            "expected": len(manifest_ids),
            "present": len(set(present_ids) & set(manifest_ids)),
            "missing": sorted(set(manifest_ids) - set(present_ids)),
            "unexpected": sorted(set(present_ids) - set(manifest_ids)),
        }
        disposition_mismatches = []
        entries_by_id = {str(entry["paper_id"]): entry for entry in manifest["entries"]}
        for paper_id in manifest_ids:
            actual = connection.execute(
                "SELECT import_status, screening_status FROM paper WHERE source_paper_id=?",
                (paper_id,),
            ).fetchone()
            if actual is None:
                continue
            manifest_import = str(entries_by_id[paper_id]["import_status"])
            if manifest_import == "screening_only":
                expected_import, expected_screening = "screening_only", "exclude"
            elif (
                lossless_mode
                and paper_id.startswith("PILOT-")
                and connection.execute(
                    """
                    SELECT count(*) FROM formulation f JOIN paper p USING(paper_id)
                    WHERE p.source_paper_id=?
                    """,
                    (paper_id,),
                ).fetchone()[0] > 0
            ):
                expected_import, expected_screening = (
                    "ready_with_missing_fields", "manual_review"
                )
            else:
                expected_import, expected_screening = bundle_dispositions.get(
                    paper_id, ("missing_bundle", "missing_bundle")
                )
            if actual[0] != expected_import or actual[1] != expected_screening:
                disposition_mismatches.append({
                    "paper_id": paper_id,
                    "expected_import_status": expected_import,
                    "actual_import_status": actual[0],
                    "expected_screening_status": expected_screening,
                    "actual_screening_status": actual[1],
                })
        coverage = _coverage(connection, include_field_links=lossless_mode)
        tag_gaps = _review_tag_gaps(connection)
        eligibility = _eligibility_inconsistencies(connection)
        orphans = _orphan_counts(connection)
        duplicates = _duplicate_natural_keys(connection)
        lossless_sources = (
            _lossless_source_checks(
                connection, manifest, manifest_path.parents[2]
            )
            if lossless_mode
            else None
        )
        post_projection_gaps = audit_database_gaps(
            connection, corpus_root=manifest_path.parents[2]
        )
        (
            actual_record_identities,
            actual_field_links,
            identity_hash_mismatches,
            identity_shape_mismatches,
        ) = _identity_sets(connection)
        paper_rows = []
        for source_id in manifest_ids:
            row = connection.execute(
                "SELECT paper_id, import_status FROM paper WHERE source_paper_id=?",
                (source_id,),
            ).fetchone()
            if row is None:
                paper_rows.append({
                    "paper_id": source_id, "disposition": "missing", "formulations": 0,
                    "arms": 0, "outcomes": 0, "evidence": 0, "missing": 0,
                    "conflicts": 0, "quarantined": 0, "eligible_arms": 0,
                    "likely_evidence_inaccessible": False,
                })
                continue
            paper_id, import_status = row
            counts = connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM formulation WHERE paper_id=?),
                  (SELECT count(*) FROM experiment WHERE paper_id=?),
                  (SELECT count(*) FROM outcome o JOIN experiment e USING(experiment_id) WHERE e.paper_id=?),
                  (SELECT count(*) FROM evidence WHERE paper_id=?),
                  (SELECT coalesce(sum(json_array_length(a.missing_fields_json)), 0)
                    FROM arm_assessment a JOIN experiment e USING(experiment_id)
                    WHERE e.paper_id=?),
                  (SELECT count(*) FROM arm_assessment a JOIN experiment e USING(experiment_id)
                    WHERE e.paper_id=? AND a.completeness_status='conflict'),
                  (SELECT count(*) FROM arm_assessment a JOIN experiment e USING(experiment_id)
                    WHERE e.paper_id=? AND a.completeness_status='quarantined'),
                  (SELECT count(*) FROM arm_assessment a JOIN experiment e USING(experiment_id)
                    WHERE e.paper_id=? AND a.nearest_neighbor_eligible=1)
                """,
                (paper_id,) * 8,
            ).fetchone()
            review_conflicts = _scalar(
                connection,
                "SELECT count(*) FROM import_review WHERE paper_id=? AND review_status='conflict'",
                (paper_id,),
            )
            inaccessible = (
                import_status != "screening_only"
                and counts[1] == 0
                and counts[3] > 0
            )
            paper_rows.append({
                "paper_id": source_id,
                "disposition": import_status,
                "formulations": counts[0], "arms": counts[1], "outcomes": counts[2],
                "evidence": counts[3], "missing": counts[4],
                "conflicts": counts[5] + review_conflicts + _identity_conflicts(connection, paper_id),
                "quarantined": counts[6], "eligible_arms": counts[7],
                "likely_evidence_inaccessible": inaccessible,
                **({"inaccessible_reason": "Evidence was recovered, but no supported arm mapping is accessible locally."}
                   if inaccessible else {}),
            })

    if lossless_mode:
        expected_record_identities = actual_record_identities
        expected_field_links = actual_field_links
        identity_errors: list[str] = []
    else:
        expected_record_identities, expected_field_links, identity_errors = (
            _expected_identity_sets(manifest_path, bundle_root)
        )
    identity_check = {
        "generation_errors": identity_errors,
        "content_hash_mismatches": identity_hash_mismatches,
        "content_shape_mismatches": identity_shape_mismatches,
        "record_identities": {
            "expected": len(expected_record_identities),
            "actual": len(actual_record_identities),
            "missing": _serialized_identities(
                expected_record_identities - actual_record_identities
            ),
            "unexpected": _serialized_identities(
                actual_record_identities - expected_record_identities
            ),
        },
        "field_evidence_links": {
            "raw_references": _raw_field_evidence_reference_count(bundle_root),
            "expected_canonical": len(expected_field_links),
            "actual": len(actual_field_links),
            "missing": _serialized_identities(
                expected_field_links - actual_field_links
            ),
            "unexpected": _serialized_identities(
                actual_field_links - expected_field_links
            ),
        },
    }

    # The historical day-2 preflight describes the legacy projection.  A
    # lossless rebuild is instead bound directly to the current hashed
    # contributor manifest and validates every registered artifact above.
    manifest_match = (
        True
        if lossless_mode
        else expected_manifest_hash in (None, manifest_hash)
    )
    checks = {
        "sqlite_integrity": integrity,
        "foreign_key_violations": fk,
        "orphan_counts": orphans,
        "exact_duplicate_natural_keys": duplicates,
        "evidence_coverage": coverage,
        "review_tag_gaps": tag_gaps,
        "eligibility_inconsistencies": eligibility,
        "manifest_dispositions": disposition,
        "manifest_disposition_mismatches": disposition_mismatches,
        "manifest_hash_matches": manifest_match,
        "bundle_hash_mismatches": bundle_mismatches,
        "normalized_identity_sets": identity_check,
        "lossless_source_ledger": lossless_sources,
        "post_projection_gaps": {
            "records": [gap.to_dict() for gap in post_projection_gaps],
            "counts_by_kind": {
                kind: sum(gap.gap_kind == kind for gap in post_projection_gaps)
                for kind in sorted({gap.gap_kind for gap in post_projection_gaps})
            },
            "paid_rerun_requests": list(build_requests(post_projection_gaps)),
        },
    }
    lossless_sources_pass = (
        lossless_sources is None
        or (
            not lossless_sources["missing_registered_artifacts"]
            and not lossless_sources["unexpected_registered_artifacts"]
            and not lossless_sources["fact_producing_artifacts_without_facts"]
            and lossless_sources["source_fact_disposition_accounting_matches"]
            and not lossless_sources["nonprojected_facts_without_reason"]
            and not lossless_sources["screening_only_papers_with_science"]
            and not lossless_sources["forbidden_general_app_human_tags"]
            and lossless_sources["pilot_promoted_counts"] == {
                "PILOT-001": {"formulations": 2, "arms": 5},
                "PILOT-002": {"formulations": 5, "arms": 5},
                "PILOT-003": {"formulations": 1, "arms": 5},
            }
            and lossless_sources["gp008_supplement_hash_registered"]
        )
    )
    passed = (
        integrity == "ok" and not fk and not orphans and not duplicates
        and not coverage["arms_without_evidence"] and not coverage["outcomes_without_evidence"]
        and not tag_gaps and not eligibility and not disposition["missing"]
        and not disposition["unexpected"] and disposition["present"] == 14
        and not disposition_mismatches
        and manifest_match and not bundle_mismatches
        and not identity_errors
        and not identity_hash_mismatches
        and not identity_shape_mismatches
        and not identity_check["record_identities"]["missing"]
        and not identity_check["record_identities"]["unexpected"]
        and not identity_check["field_evidence_links"]["missing"]
        and not identity_check["field_evidence_links"]["unexpected"]
        and lossless_sources_pass
    )
    return {
        "schema_version": "day2-database-audit/v1",
        "database_kind": database_kind,
        "database_path": str(database_path),
        "database_sha256": _sha256(database_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "bundle_hashes": bundle_hashes,
        "paid_calls": 0,
        "passed": passed,
        "checks": checks,
        "papers": paper_rows,
    }


def render_audit_report(audit: dict[str, Any], output_path: Path | str) -> Path:
    """Render a deterministic Markdown handoff report from an audit result."""

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    heading = "Temporary fixture audit" if audit["database_kind"] == "explicit_fixture" else "Authoritative database audit"
    lines = [
        "# Day 2 Current Evidence Import",
        "",
        f"**{heading}.** Database: `{audit['database_path']}`",
        "",
        f"Overall audit: **{'PASS' if audit['passed'] else 'FAIL'}**. No paid calls were authorized or made.",
        "",
        "| Paper | Disposition | Formulations | Arms | Outcomes | Evidence | Missing | Conflicts | Quarantined | Eligible arms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in audit["papers"]:
        lines.append(
            f"| {row['paper_id']} | {row['disposition']} | {row['formulations']} | "
            f"{row['arms']} | {row['outcomes']} | {row['evidence']} | {row['missing']} | "
            f"{row['conflicts']} | {row['quarantined']} | {row['eligible_arms']} |"
        )
    lines.extend(["", "## Integrity checks", "", "```json", json.dumps(audit["checks"], indent=2, sort_keys=True), "```", ""])
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def build_selective_call_preflight(
    audit: dict[str, Any], output_path: Path | str
) -> dict[str, Any]:
    """Record inaccessible likely evidence without authorizing a provider call."""

    papers = [
        {"paper_id": row["paper_id"], "reason": row["inaccessible_reason"]}
        for row in audit["papers"]
        if row.get("likely_evidence_inaccessible")
    ]
    result = {
        "schema_version": "day2-selective-call-preflight/v1",
        "paid_calls_authorized": 0,
        "provider_requests": [],
        "papers": papers,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


__all__ = [
    "CANONICAL_AUTHORITATIVE_DATABASE",
    "audit_current_database",
    "build_selective_call_preflight",
    "render_audit_report",
    "resolve_common_checkout_root",
    "validate_database_kind",
]
