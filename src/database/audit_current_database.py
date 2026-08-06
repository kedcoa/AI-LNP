"""Read-only integrity and provenance audit for the current evidence database."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


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


def _coverage(connection: sqlite3.Connection) -> dict[str, list[int]]:
    arms = [
        int(row[0])
        for row in connection.execute(
            """SELECT experiment_id FROM experiment e WHERE NOT EXISTS
            (SELECT 1 FROM evidence v WHERE v.experiment_id=e.experiment_id)
            ORDER BY experiment_id"""
        )
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
    rows = connection.execute(
        """
        SELECT p.source_paper_id, a.experiment_id, a.completeness_status,
               a.nearest_neighbor_eligible, a.comet_eligible,
               max(CASE WHEN r.profile='nearest_neighbor' THEN r.eligible END),
               max(CASE WHEN r.profile='comet' THEN r.eligible END),
               count(DISTINCT v.evidence_id), count(DISTINCT o.outcome_id)
        FROM arm_assessment a
        JOIN experiment e USING (experiment_id)
        JOIN paper p USING (paper_id)
        LEFT JOIN eligibility_result r USING (experiment_id)
        LEFT JOIN evidence v USING (experiment_id)
        LEFT JOIN outcome o USING (experiment_id)
        GROUP BY a.experiment_id
        ORDER BY p.source_paper_id, a.experiment_id
        """
    ).fetchall()
    problems = []
    for paper_id, arm_id, status, nearest, comet, stored_nearest, stored_comet, evidence, outcomes in rows:
        reasons = []
        if stored_nearest is None or stored_comet is None:
            reasons.append("missing eligibility result")
        if stored_nearest is not None and nearest != stored_nearest:
            reasons.append("nearest-neighbor flag differs from result")
        if stored_comet is not None and comet != stored_comet:
            reasons.append("COMET flag differs from result")
        if (nearest or comet) and (status != "complete" or not evidence or not outcomes):
            reasons.append("eligible arm is incomplete or lacks evidence/outcome")
        if reasons:
            problems.append({"paper_id": paper_id, "arm_id": arm_id, "reasons": reasons})
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

    uri = f"file:{database_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
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
        coverage = _coverage(connection)
        tag_gaps = _review_tag_gaps(connection)
        eligibility = _eligibility_inconsistencies(connection)
        orphans = _orphan_counts(connection)
        duplicates = _duplicate_natural_keys(connection)
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

    manifest_match = expected_manifest_hash in (None, manifest_hash)
    checks = {
        "sqlite_integrity": integrity,
        "foreign_key_violations": fk,
        "orphan_counts": orphans,
        "exact_duplicate_natural_keys": duplicates,
        "evidence_coverage": coverage,
        "review_tag_gaps": tag_gaps,
        "eligibility_inconsistencies": eligibility,
        "manifest_dispositions": disposition,
        "manifest_hash_matches": manifest_match,
        "bundle_hash_mismatches": bundle_mismatches,
    }
    passed = (
        integrity == "ok" and not fk and not orphans and not duplicates
        and not coverage["arms_without_evidence"] and not coverage["outcomes_without_evidence"]
        and not tag_gaps and not eligibility and not disposition["missing"]
        and not disposition["unexpected"] and disposition["present"] == 14
        and manifest_match and not bundle_mismatches
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


__all__ = ["audit_current_database", "build_selective_call_preflight", "render_audit_report"]
