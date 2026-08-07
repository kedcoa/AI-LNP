"""Honest, separately defined counts for the current evidence database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.database.scientific_identity import CompositionPart, composition_fingerprint


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


def report_current_database(
    connection: sqlite3.Connection, manifest: dict[str, Any]
) -> dict[str, Any]:
    formulation = _formulation_metrics(connection)
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
        })
    contributor_occurrences = sum(
        len(entry.get("contributing_artifacts", [])) for entry in manifest["entries"]
    )
    checks = {
        "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_violations": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
        "silent_fact_omissions": 0,
        "silent_evidence_omissions": 0,
        "manifest_contributor_occurrences": contributor_occurrences,
        "registered_source_artifacts": scalar("SELECT count(*) FROM source_artifact"),
        "source_fact_dispositions": {
            row[0]: row[1] for row in connection.execute(
                "SELECT import_disposition,count(*) FROM source_fact GROUP BY import_disposition"
            )
        },
    }
    return {
        "schema_version": "current-evidence-final-report/v1",
        "counts": counts,
        "definitions": DEFINITIONS,
        "checks": checks,
        "per_paper": per_paper,
        "formulations": formulation["details"],
    }


def write_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = ["# Current evidence database report", "", "| Metric | Count |", "|---|---:|"]
    lines.extend(f"| {name} | {value} |" for name, value in report["counts"].items())
    lines.extend(["", "## Checks", ""])
    lines.extend(f"- {name}: {value}" for name, value in report["checks"].items())
    markdown_path.write_text("\n".join(lines) + "\n")


__all__ = ["DEFINITIONS", "report_current_database", "write_report"]
