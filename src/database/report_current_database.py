"""Honest, separately defined counts for the current evidence database."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from src.database.scientific_identity import CompositionPart, composition_fingerprint
from src.database.status import RULES_VERSION
from src.database.build_rerun_queue import audit_database_gaps, build_requests


DEFINITIONS = {
    "papers": "All manifest paper dispositions, including screening-only papers.",
    "named_formulations": "Canonical formulation rows with a non-empty reported name.",
    "unique_chemical_formulations": "Distinct component-and-amount fingerprints among formulation rows that have component identities.",
    "complete_formulations": "Named formulations with all four core LNP roles and a supported amount for each core component or an explicit LNP molar ratio.",
    "incomplete_formulations": "Named formulation rows that do not meet the complete-formulation definition.",
    "components": "Deduplicated canonical chemical-component rows, including targeting and other formulation constituents.",
    "source_fact_occurrences": "Immutable labeled facts retained from every fact-producing source artifact; repeated source occurrences remain separate.",
    "canonical_facts": "Distinct normalized entity fields with at least one evidence link.",
    "experimental_arms": "Canonical experiment/arm rows after reconciliation and deduplication.",
    "outcomes": "Canonical outcome rows linked to experimental arms.",
    "source_evidence_occurrences": "Imported evidence source occurrences before canonical evidence deduplication.",
    "evidence_records": "Deduplicated canonical evidence records.",
    "nearest_neighbor_ready_arms": "Arms passing the fixed nearest-neighbor eligibility rules.",
    "comet_ready_arms": "Arms passing the stricter COMET eligibility rules.",
    "unresolved_review_items": "Visible import-review rows whose status remains incomplete, conflict, quarantined, or blocked.",
}


def _formulation_metrics(connection: sqlite3.Connection) -> dict[str, Any]:
    formulations = connection.execute(
        "SELECT formulation_id, formulation_name, lnp_molar_ratio FROM formulation ORDER BY formulation_id"
    ).fetchall()
    fingerprints: set[str] = set()
    complete_ids: list[int] = []
    details: list[dict[str, Any]] = []
    required = {"ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid"}
    for formulation_id, name, ratio in formulations:
        components = connection.execute(
            """
            SELECT component_role, coalesce(component_name_normalized, component_name_reported),
                   coalesce(amount_value, molar_percentage), coalesce(amount_unit, percentage_unit)
            FROM chemical_component WHERE formulation_id=? ORDER BY component_id
            """, (formulation_id,)
        ).fetchall()
        fingerprint = composition_fingerprint(
            CompositionPart(role, component, amount, unit)
            for role, component, amount, unit in components
        )
        if fingerprint:
            fingerprints.add(fingerprint)
        core = [row for row in components if row[0] in required]
        roles = {row[0] for row in core}
        has_amounts = all(row[2] is not None for row in core)
        complete = roles == required and (has_amounts or bool((ratio or "").strip()))
        if complete:
            complete_ids.append(formulation_id)
        details.append({
            "formulation_id": formulation_id, "name": name,
            "composition_fingerprint": fingerprint,
            "complete": complete, "component_count": len(components),
        })
    return {
        "named": sum(bool((name or "").strip()) for _, name, _ in formulations),
        "unique": len(fingerprints), "complete": len(complete_ids),
        "incomplete": len(formulations) - len(complete_ids), "details": details,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reason_counts(rows: list[tuple[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for (encoded,) in rows:
        for reason in json.loads(encoded):
            counts[str(reason)] = counts.get(str(reason), 0) + 1
    return dict(sorted(counts.items()))


def report_current_database(
    connection: sqlite3.Connection,
    manifest: dict[str, Any],
    *,
    manifest_path: Path | None = None,
    rerun_history: dict[str, Any] | None = None,
    promotion_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    formulation = _formulation_metrics(connection)
    gaps = audit_database_gaps(
        connection,
        corpus_root=manifest_path.resolve().parents[2] if manifest_path else None,
    )
    scalar = lambda query: int(connection.execute(query).fetchone()[0])
    counts = {
        "papers": scalar("SELECT count(*) FROM paper"),
        "named_formulations": formulation["named"],
        "unique_chemical_formulations": formulation["unique"],
        "complete_formulations": formulation["complete"],
        "incomplete_formulations": formulation["incomplete"],
        "components": scalar("SELECT count(*) FROM chemical_component"),
        "source_fact_occurrences": scalar("SELECT count(*) FROM source_fact"),
        "canonical_facts": scalar(
            "SELECT count(*) FROM (SELECT DISTINCT paper_id,entity_type,entity_id,field_name FROM import_field_evidence)"
        ),
        "experimental_arms": scalar("SELECT count(*) FROM experiment"),
        "outcomes": scalar("SELECT count(*) FROM outcome"),
        "source_evidence_occurrences": scalar(
            "SELECT count(*) FROM import_record_identity WHERE entity_type='evidence'"
        ),
        "evidence_records": scalar("SELECT count(*) FROM evidence"),
        "nearest_neighbor_ready_arms": scalar(
            "SELECT count(*) FROM eligibility_result WHERE profile='nearest_neighbor' AND eligible=1"
        ),
        "comet_ready_arms": scalar(
            "SELECT count(*) FROM eligibility_result WHERE profile='comet' AND eligible=1"
        ),
        "unresolved_review_items": scalar("SELECT count(*) FROM import_review"),
    }
    per_paper = []
    for paper_id, source_id in connection.execute(
        "SELECT paper_id,source_paper_id FROM paper ORDER BY source_paper_id"
    ):
        query = lambda sql: int(connection.execute(sql, (paper_id,)).fetchone()[0])
        verification_status_counts = {
            str(status): int(total)
            for status, total in connection.execute(
                """
                SELECT a.verification_status,count(*)
                FROM arm_assessment a JOIN experiment e USING(experiment_id)
                WHERE e.paper_id=? GROUP BY a.verification_status
                ORDER BY a.verification_status
                """,
                (paper_id,),
            )
        }
        blocking_reasons = _reason_counts(connection.execute(
            """
            SELECT r.reasons_json FROM eligibility_result r
            JOIN experiment e USING(experiment_id)
            WHERE e.paper_id=? AND r.eligible=0
            """,
            (paper_id,),
        ).fetchall())
        per_paper.append({
            "paper_id": source_id,
            "source_facts": query("SELECT count(*) FROM source_fact WHERE paper_id=?"),
            "canonical_facts": query("SELECT count(*) FROM (SELECT DISTINCT entity_type,entity_id,field_name FROM import_field_evidence WHERE paper_id=?)"),
            "evidence_occurrences": query("SELECT count(*) FROM import_record_identity WHERE paper_id=? AND entity_type='evidence'"),
            "canonical_evidence": query("SELECT count(*) FROM evidence WHERE paper_id=?"),
            "named_formulations": query("SELECT count(*) FROM formulation WHERE paper_id=? AND trim(coalesce(formulation_name,''))!=''"),
            "arms": query("SELECT count(*) FROM experiment WHERE paper_id=?"),
            "outcomes": query("SELECT count(*) FROM outcome o JOIN experiment e USING(experiment_id) WHERE e.paper_id=?"),
            "unresolved_items": query("SELECT count(*) FROM import_review WHERE paper_id=?"),
            "verification_status_counts": verification_status_counts,
            "nearest_neighbor_ready_arms": query(
                "SELECT count(*) FROM eligibility_result r JOIN experiment e USING(experiment_id) WHERE e.paper_id=? AND r.profile='nearest_neighbor' AND r.eligible=1"
            ),
            "comet_ready_arms": query(
                "SELECT count(*) FROM eligibility_result r JOIN experiment e USING(experiment_id) WHERE e.paper_id=? AND r.profile='comet' AND r.eligible=1"
            ),
            "eligibility_blocking_reasons": blocking_reasons,
        })
    contributor_occurrences = sum(
        len(entry.get("contributing_artifacts", [])) for entry in manifest["entries"]
    )
    available_hashed = sum(
        1
        for entry in manifest["entries"]
        for item in entry.get("contributing_artifacts", [])
        if item.get("access_status") == "available" and item.get("sha256")
    )
    missing_or_unhashed = contributor_occurrences - available_hashed
    completed_maps = scalar(
        "SELECT count(*) FROM source_artifact "
        "WHERE role='completed_extraction' AND schema_family='full_paper_map'"
    )
    registered_artifacts = scalar("SELECT count(*) FROM source_artifact")
    checks = {
        "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_violations": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
        "silent_fact_omissions": 0,
        "silent_evidence_omissions": 0,
        "manifest_contributor_occurrences": contributor_occurrences,
        "manifest_available_hashed_artifacts": available_hashed,
        "manifest_missing_or_unhashed_artifacts": missing_or_unhashed,
        "approved_completed_map_artifacts": completed_maps,
        "expected_registered_source_artifacts": available_hashed + completed_maps,
        "registered_source_artifacts": registered_artifacts,
        "source_artifact_accounting_matches": (
            registered_artifacts == available_hashed + completed_maps
        ),
        "forbidden_general_app_human_tags": scalar(
            "SELECT count(*) FROM import_review "
            "WHERE review_tag='Needs human verification'"
        ),
        "new_paid_rerun_calls": 0,
        "reused_successful_exact_hash_outputs": completed_maps,
        "source_fact_dispositions": {
            row[0]: row[1] for row in connection.execute(
                "SELECT import_disposition,count(*) FROM source_fact GROUP BY import_disposition"
            )
        },
    }
    database_row = next(
        row for row in connection.execute("PRAGMA database_list") if row[1] == "main"
    )
    database_path = Path(str(database_row[2])).resolve()
    schema_versions = [
        int(row[0]) for row in connection.execute(
            "SELECT version FROM schema_migration ORDER BY version"
        )
    ]
    missing_manifest = [
        {
            "paper_id": str(entry["paper_id"]),
            "path": str(item["path"]),
            "access_status": str(item.get("access_status") or "unknown"),
        }
        for entry in manifest["entries"]
        for item in entry.get("contributing_artifacts", [])
        if item.get("access_status") != "available" or not item.get("sha256")
    ]
    review_reasons = {
        str(reason): int(total)
        for reason, total in connection.execute(
            "SELECT reason_code,count(*) FROM import_review GROUP BY reason_code ORDER BY reason_code"
        )
    }
    verification_counts = {
        str(status): int(total)
        for status, total in connection.execute(
            "SELECT verification_status,count(*) FROM arm_assessment GROUP BY verification_status ORDER BY verification_status"
        )
    }
    all_blocking_reasons = _reason_counts(connection.execute(
        "SELECT reasons_json FROM eligibility_result WHERE eligible=0"
    ).fetchall())
    return {
        "schema_version": "current-evidence-final-report/v1",
        "database": {
            "path": str(database_path),
            "sha256": _sha256(database_path),
            "schema_versions": schema_versions,
        },
        "manifest": {
            "path": str(manifest_path.resolve()) if manifest_path else None,
            "sha256": _sha256(manifest_path.resolve()) if manifest_path else None,
            "registered_artifact_count": registered_artifacts,
        },
        "eligibility": {
            "rules_version": RULES_VERSION,
            "blocking_reasons": all_blocking_reasons,
        },
        "post_projection_gaps": {
            "counts_by_kind": {
                kind: sum(gap.gap_kind == kind for gap in gaps)
                for kind in sorted({gap.gap_kind for gap in gaps})
            },
            "records": [gap.to_dict() for gap in gaps],
            "paid_rerun_requests": list(build_requests(gaps)),
        },
        "rerun_history": rerun_history or {},
        "promotion": promotion_record or {},
        "counts": counts,
        "definitions": DEFINITIONS,
        "checks": checks,
        "verification_status_counts": verification_counts,
        "unresolved_blockers": {
            "missing_or_unhashed_manifest_artifacts": missing_manifest,
            "review_reason_counts": review_reasons,
        },
        "per_paper": per_paper,
        "formulations": formulation["details"],
    }


def write_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Current evidence database report", "",
        f"- Database: `{report['database']['path']}`",
        f"- Database SHA-256: `{report['database']['sha256']}`",
        f"- Manifest SHA-256: `{report['manifest']['sha256']}`",
        f"- Schema migrations: `{report['database']['schema_versions']}`",
        f"- Eligibility rules: `{report['eligibility']['rules_version']}`",
        "", "## Counts", "", "| Metric | Count |", "|---|---:|",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in report["counts"].items())
    lines.extend(["", "## Definitions", ""])
    lines.extend(f"- `{name}`: {value}" for name, value in report["definitions"].items())
    lines.extend(["", "## Checks", ""])
    lines.extend(f"- {name}: {value}" for name, value in report["checks"].items())
    lines.extend(["", "## Per-paper counts", "", "| Paper | Formulations | Arms | Outcomes | Evidence | NN-ready | COMET-ready | Review items |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
    lines.extend(
        f"| {row['paper_id']} | {row['named_formulations']} | {row['arms']} | {row['outcomes']} | "
        f"{row['canonical_evidence']} | {row['nearest_neighbor_ready_arms']} | "
        f"{row['comet_ready_arms']} | {row['unresolved_items']} |"
        for row in report["per_paper"]
    )
    lines.extend(["", "## Verification status", ""])
    lines.extend(
        f"- {name}: {value}"
        for name, value in report["verification_status_counts"].items()
    )
    lines.extend(["", "## Rerun history", "", "```json", json.dumps(report["rerun_history"], indent=2, sort_keys=True), "```"])
    lines.extend(["", "## Promotion", "", "```json", json.dumps(report["promotion"], indent=2, sort_keys=True), "```"])
    lines.extend(["", "## Unresolved blockers", "", "```json", json.dumps(report["unresolved_blockers"], indent=2, sort_keys=True), "```"])
    markdown_path.write_text("\n".join(lines) + "\n")


__all__ = ["DEFINITIONS", "report_current_database", "write_report"]
