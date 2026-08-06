"""Deterministic, zero-call orchestration for the current evidence corpus."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from src.database.import_bundle import PaperImportResult, import_bundle
from src.database.import_contracts import (
    ImportBundle,
    PaperRecord,
    ReviewRecord,
    SourceArtifactRecord,
)
from src.database.migrations import migrate_database
from src.database.status import evaluate_arm_status, evaluate_eligibility


SCIENTIFIC_TABLES = (
    "paper",
    "formulation",
    "chemical_component",
    "experiment",
    "outcome",
    "evidence",
)
SCREENING_ONLY_IDS = frozenset({"GP-001", "GP-003", "GP-009"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bundle_paths(bundle_root: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for path in sorted(bundle_root.glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        paper = payload.get("paper")
        if not isinstance(paper, dict) or not paper.get("source_paper_id"):
            continue
        paper_id = str(paper["source_paper_id"])
        if paper_id in paths:
            raise ValueError(f"duplicate bundle for {paper_id}")
        paths[paper_id] = path
    return paths


def _screening_bundle(entry: dict[str, Any], manifest_path: Path) -> ImportBundle:
    paper_id = str(entry["paper_id"])
    manifest_hash = _sha256(manifest_path)
    artifact_id = f"{paper_id}:screening-manifest"
    return ImportBundle(
        artifacts=(
            SourceArtifactRecord(
                artifact_id=artifact_id,
                path=str(manifest_path),
                sha256=manifest_hash,
                source_kind="screening_manifest",
                pipeline_name="current_corpus_manifest",
                pipeline_version="v1",
            ),
        ),
        paper=PaperRecord(
            source_paper_id=paper_id,
            artifact_id=artifact_id,
            title=entry.get("title") or paper_id,
            source_type="screening_record",
            retrieval_date=entry.get("last_checked") or "2026-08-06",
            screening_status="exclude",
            import_status="screening_only",
            pmid=entry.get("pmid"),
            pmcid=entry.get("pmcid"),
            doi=entry.get("doi"),
            screening_reason=(
                entry.get("strongest_artifact_rationale")
                or "Screening-only paper."
            ),
        ),
    )


def _load_ordered_bundles(
    manifest_path: Path, bundle_root: Path
) -> list[ImportBundle]:
    manifest = _load_manifest(manifest_path)
    paths = _bundle_paths(bundle_root)
    bundles: list[ImportBundle] = []
    for entry in manifest["entries"]:
        paper_id = str(entry["paper_id"])
        if entry.get("import_status") == "screening_only":
            if paper_id not in SCREENING_ONLY_IDS:
                raise ValueError(f"unexpected screening-only paper: {paper_id}")
            bundles.append(_screening_bundle(entry, manifest_path))
            continue
        path = paths.get(paper_id)
        if path is None:
            raise FileNotFoundError(f"missing import bundle for {paper_id}")
        bundle = ImportBundle.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )
        if bundle.paper.source_paper_id != paper_id:
            raise ValueError(f"bundle order mismatch for {paper_id}")
        if bundle.paper.full_text_status not in {
            "unknown", "abstract_only", "open_full_text", "pdf_available", "unavailable"
        }:
            bundle = replace(
                bundle,
                paper=replace(bundle.paper, full_text_status="pdf_available"),
            )
        bundle = _normalize_database_vocabulary(bundle)
        bundles.append(bundle)
    if len(bundles) != 14:
        raise ValueError(f"expected 14 corpus dispositions, found {len(bundles)}")
    return bundles


def _normalize_database_vocabulary(bundle: ImportBundle) -> ImportBundle:
    """Map descriptive adapter labels to lossless database categories."""

    cell_types = {
        "hepatocyte": "hepatocyte",
        "hepatocytes": "hepatocyte",
        "Kupffer cells": "kupffer_cell",
        "Kupffer cells (CD31− CD45+ CD68+)": "kupffer_cell",
        "liver endothelial cells": "lsec",
        "hepatic stellate cells": "hsc",
    }
    locations = {
        "clause": "results",
        "paragraph": "results",
        "pdf_page": "other",
        "source_inventory_block": "other",
        "table_cell": "table",
    }
    methods = {
        "accepted_graph": "text_extraction",
        "validated_extraction": "text_extraction",
        "deterministic_source_inventory_recovery": "text_extraction",
    }
    confidence = {
        "accepted": "high",
        "requires_review": "medium",
        "unverified_recovery": "low",
    }
    components = tuple(
        replace(component, component_role="other")
        if component.component_role == "reported component"
        else component
        for component in bundle.components
    )
    formulations = tuple(
        replace(formulation, composition_basis="other")
        if formulation.composition_basis
        not in {None, "mol%", "weight%", "molar_ratio", "mass_ratio", "not_reported", "other"}
        else formulation
        for formulation in bundle.formulations
    )
    normalized_arms = []
    review_gated_arm_ids: set[str] = set()
    for arm in bundle.arms:
        mapped = cell_types.get(arm.cell_type)
        if mapped is not None:
            normalized_arms.append(replace(arm, cell_type=mapped))
            continue
        original = arm.cell_type.strip()
        review_gated_arm_ids.add(arm.record_id)
        note = f"Reported target-cell value: {original}" if original else "Target cell was not reported."
        normalized_arms.append(
            replace(
                arm,
                cell_type="other" if original else "not_reported",
                completeness_status="quarantined",
                verification_status="ambiguous",
                nearest_neighbor_eligible=False,
                comet_eligible=False,
                quarantine_reason="Target cell needs human verification",
                experiment_notes=(
                    f"{arm.experiment_notes}\n{note}" if arm.experiment_notes else note
                ),
            )
        )
    arms = tuple(normalized_arms)
    outcomes = tuple(
        replace(outcome, endpoint_family="other")
        if outcome.endpoint_family in {"reported endpoint", "reported outcome"}
        else outcome
        for outcome in bundle.outcomes
    )
    evidence = tuple(
        replace(
            row,
            evidence_location_type=locations.get(
                row.evidence_location_type, row.evidence_location_type
            ),
            extraction_method=methods.get(row.extraction_method, row.extraction_method),
            extraction_confidence=confidence.get(
                row.extraction_confidence, row.extraction_confidence
            ),
        )
        for row in bundle.evidence
    )
    reviews = []
    reviewed_ids: set[str] = set()
    for review in bundle.reviews:
        if review.arm_id in review_gated_arm_ids:
            reviewed_ids.add(review.arm_id)
            reviews.append(
                replace(
                    review,
                    status="quarantined" if review.evidence_ids else "blocked",
                    reason_code="target_cell_needs_verification",
                )
            )
        else:
            reviews.append(review)
    for arm_id in sorted(review_gated_arm_ids - reviewed_ids):
        scoped_evidence = tuple(
            row.record_id for row in evidence if row.arm_id == arm_id
        )
        reviews.append(
            ReviewRecord(
                record_id=f"{arm_id}:target-cell-review",
                paper_id=bundle.paper.source_paper_id,
                artifact_id=next(arm.artifact_id for arm in arms if arm.record_id == arm_id),
                reason_code="target_cell_needs_verification",
                status="quarantined" if scoped_evidence else "blocked",
                evidence_ids=scoped_evidence,
                arm_id=arm_id,
                field_name="cell_type",
                notes="Target cell is not safely mapped to a supported liver cell type.",
            )
        )
    return replace(
        bundle,
        formulations=formulations,
        components=components,
        arms=arms,
        outcomes=outcomes,
        evidence=evidence,
        reviews=tuple(reviews),
    )


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in SCIENTIFIC_TABLES
    }


def _bundle_expected_counts(bundle: ImportBundle) -> dict[str, int]:
    return {
        "papers": 1,
        "formulations": len(bundle.formulations),
        "components": len(bundle.components),
        "arms": len(bundle.arms),
        "outcomes": len(bundle.outcomes),
        "evidence": len(bundle.evidence),
        "field_evidence_references": sum(
            len(link.evidence_ids) for link in bundle.field_evidence_links
        ),
        "reviews": len(bundle.reviews),
    }


def _expected_counts(bundles: list[ImportBundle]) -> dict[str, int]:
    rows = [_bundle_expected_counts(bundle) for bundle in bundles]
    return {key: sum(row[key] for row in rows) for key in rows[0]}


def _recalculate_paper(
    connection: sqlite3.Connection, source_paper_id: str
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT e.experiment_id
        FROM experiment e JOIN paper p USING (paper_id)
        WHERE p.source_paper_id = ? ORDER BY e.experiment_id
        """,
        (source_paper_id,),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for (experiment_id,) in rows:
        status = evaluate_arm_status(connection, experiment_id)
        nearest = evaluate_eligibility(connection, experiment_id, "nearest_neighbor")
        comet = evaluate_eligibility(connection, experiment_id, "comet")
        results.append(
            {
                "paper_id": source_paper_id,
                "experiment_id": experiment_id,
                "completeness_status": status.completeness_status,
                "verification_status": status.verification_status,
                "nearest_neighbor_eligible": nearest.eligible,
                "nearest_neighbor_reasons": list(nearest.reasons),
                "comet_eligible": comet.eligible,
                "comet_reasons": list(comet.reasons),
            }
        )
    return results


def run_current_corpus_import(
    database_path: Path | str,
    manifest_path: Path | str,
    bundle_root: Path | str,
) -> dict[str, Any]:
    """Import all 14 manifest dispositions, committing or rolling back per paper."""

    database_path = Path(database_path)
    manifest_path = Path(manifest_path)
    bundle_root = Path(bundle_root)
    bundles = _load_ordered_bundles(manifest_path, bundle_root)
    dispositions: list[dict[str, Any]] = []
    eligibility: list[dict[str, Any]] = []
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        migrate_database(connection)
        connection.commit()
        for bundle in bundles:
            paper_id = bundle.paper.source_paper_id
            try:
                connection.execute("BEGIN")
                result: PaperImportResult = import_bundle(connection, bundle)
                paper_eligibility = _recalculate_paper(connection, paper_id)
                connection.commit()
            except BaseException as exc:
                connection.rollback()
                dispositions.append(
                    {"paper_id": paper_id, "status": "rolled_back", "error": str(exc)}
                )
                continue
            eligibility.extend(paper_eligibility)
            dispositions.append(
                {
                    "paper_id": paper_id,
                    "status": "committed",
                    **asdict(result),
                }
            )
        return {
            "paid_calls": 0,
            "dispositions": dispositions,
            "expected_counts": _expected_counts(bundles),
            "database_counts": _table_counts(connection),
            "eligibility": eligibility,
        }
    finally:
        connection.close()


def build_import_preflight(
    authoritative_database_path: Path | str,
    manifest_path: Path | str,
    bundle_root: Path | str,
    *,
    report_path: Path | str | None = None,
) -> dict[str, Any]:
    """Describe the exact import inputs without opening SQLite for writes."""

    database_path = Path(authoritative_database_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    bundle_root = Path(bundle_root).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"authoritative database not found: {database_path}")
    manifest = _load_manifest(manifest_path)
    paths = _bundle_paths(bundle_root)
    bundles = _load_ordered_bundles(manifest_path, bundle_root)
    bundles_by_id = {bundle.paper.source_paper_id: bundle for bundle in bundles}
    corpus_date = max(str(entry.get("last_checked") or "unknown") for entry in manifest["entries"])
    stamp = corpus_date.replace("-", "")
    backup = (
        Path(tempfile.gettempdir())
        / "ai-lnp-database-backups"
        / f"lnp_evidence-pre-day2-{stamp}.db"
    )
    rows = []
    for paper_id in [str(entry["paper_id"]) for entry in manifest["entries"]]:
        path = paths.get(paper_id)
        if path is None:
            continue
        rows.append(
            {
                "paper_id": paper_id,
                "path": str(path.relative_to(bundle_root.parent.parent.parent.parent)),
                "sha256": _sha256(path),
                "expected_counts": _bundle_expected_counts(bundles_by_id[paper_id]),
            }
        )
    report = {
        "schema_version": "day2-import-preflight/v1",
        "corpus_date": corpus_date,
        "paid_calls": 0,
        "authoritative_database_path": str(database_path),
        "authoritative_database_sha256": _sha256(database_path),
        "backup_target_proposal": str(backup),
        "manifest_path": str(manifest_path.relative_to(bundle_root.parent.parent.parent.parent)),
        "manifest_sha256": _sha256(manifest_path),
        "paper_order": [str(entry["paper_id"]) for entry in manifest["entries"]],
        "expected_counts": _expected_counts(bundles),
        "bundles": rows,
    }
    if report_path is not None:
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


__all__ = ["build_import_preflight", "run_current_corpus_import"]
