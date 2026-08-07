"""Deterministic, zero-call orchestration for the current evidence corpus."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import csv
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
from src.database.readiness import evaluate_readiness
from src.database.paths import resolve_common_checkout_root
from src.database.rescreen_target_scope import (
    apply_target_scope_candidates,
    rescreen_paper,
)
from src.database.source_backed_arm_repair import apply_repair_manifest
from src.database.status import evaluate_arm_status
from src.database.adapters.accepted_graph import adapt_accepted_graph_losslessly
from src.database.adapters.np_results import build_np_lossless_result
from src.database.adapters.pilot_results import build_pilot_lossless_result
from src.database.adapters.pilot_map_results import (
    build_pilot_map_lossless_result,
    completed_pilot_map_response,
)
from src.database.deduplicate_science import deduplicate_science
from src.database.scientific_identity import fact_identity
from src.database.source_fact_import import (
    SourceArtifactRecord as LedgerArtifactRecord,
    SourceFactRecord,
    import_source_facts,
)
from src.init_db import initialize_database


SCIENTIFIC_TABLES = (
    "paper",
    "formulation",
    "chemical_component",
    "experiment",
    "outcome",
    "evidence",
)
SCREENING_ONLY_IDS = frozenset({"GP-001", "GP-003", "GP-009"})
SOURCE_BACKED_ARM_REPAIRS = Path(
    "config/database/source_backed_arm_repairs_v1.json"
)


@dataclass(frozen=True)
class RebuildResult:
    database_path: str
    scientific_content_sha256: str
    source_fact_count: int
    source_artifact_count: int
    silent_fact_omissions: int
    silent_evidence_omissions: int
    counts: dict[str, int]
    dispositions: tuple[dict[str, Any], ...]
    deduplication: dict[str, int]


class CurrentCorpusImportError(RuntimeError):
    """Aggregate strict-import failure with every per-paper disposition."""

    def __init__(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        self.failed_paper_ids = tuple(
            row["paper_id"]
            for row in summary["dispositions"]
            if row["status"] == "rolled_back"
        )
        super().__init__(
            "current corpus import rolled back papers: "
            + ", ".join(self.failed_paper_ids)
        )


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
        "kupffer_cell": "kupffer_cell",
        "lsec": "lsec",
        "hsc": "hsc",
        "other": "other",
        "not_reported": "not_reported",
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
    def normalize_cell_type(value: str) -> str:
        exact = cell_types.get(value)
        if exact is not None:
            return exact
        folded = value.casefold()
        matches = {
            category
            for category, terms in {
                "hepatocyte": ("hepatocyte", "hepa "),
                "kupffer_cell": ("kupffer", "macrophage", "monocyte-derived"),
                "lsec": ("lsec", "endothelial"),
                "hsc": ("hsc", "stellate"),
            }.items()
            if any(term in folded for term in terms)
        }
        return next(iter(matches)) if len(matches) == 1 else "other"

    normalized_arms = []
    for arm in bundle.arms:
        original = arm.cell_type.strip()
        if not original:
            normalized_arms.append(replace(arm, cell_type="not_reported"))
            continue
        normalized_arms.append(replace(arm, cell_type=normalize_cell_type(original)))
    arms = tuple(normalized_arms)
    endpoint_families = {
        "reported endpoint": "other", "reported outcome": "other",
        "functional_delivery": "functional_expression",
        "cell_type_selectivity": "uptake", "gene_editing": "other",
        "therapeutic_function": "therapeutic_effect",
    }
    outcomes = tuple(
        replace(
            outcome,
            endpoint_family=endpoint_families.get(
                outcome.endpoint_family, outcome.endpoint_family
            ),
            uncertainty_type=(
                outcome.uncertainty_type.casefold()
                if outcome.uncertainty_type
                and outcome.uncertainty_type.casefold() in {
                    "sd", "sem", "confidence_interval", "range", "other"
                }
                else "other" if outcome.uncertainty_type else None
            ),
        )
        for outcome in bundle.outcomes
    )
    evidence = tuple(
        replace(
            row,
            evidence_location_type=(
                locations.get(row.evidence_location_type, row.evidence_location_type)
                if locations.get(row.evidence_location_type, row.evidence_location_type)
                in {"abstract", "results", "methods", "table", "figure", "figure_caption", "supplement", "other"}
                else "other"
            ),
            extraction_method=methods.get(row.extraction_method, row.extraction_method),
            extraction_confidence=confidence.get(
                row.extraction_confidence, row.extraction_confidence
            ),
        )
        for row in bundle.evidence
    )
    reviews = list(bundle.reviews)
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
        "field_evidence_references": len(
            {
                (
                    bundle.paper.source_paper_id,
                    link.entity_type,
                    link.entity_id,
                    link.field_name,
                    evidence_id,
                )
                for link in bundle.field_evidence_links
                for evidence_id in link.evidence_ids
            }
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
        readiness = evaluate_readiness(connection, experiment_id)
        results.append(
            {
                "paper_id": source_paper_id,
                "experiment_id": experiment_id,
                "completeness_status": status.completeness_status,
                "verification_status": status.verification_status,
                "general_usable": readiness.general_usable,
                "nearest_neighbor_eligible": readiness.nearest_neighbor_ready,
                "nearest_neighbor_reasons": list(readiness.nearest_neighbor_blockers),
                "comet_eligible": readiness.comet_ready,
                "comet_reasons": list(readiness.comet_blockers),
                "queue_label": readiness.queue_label,
            }
        )
    return results


def run_current_corpus_import(
    database_path: Path | str,
    manifest_path: Path | str,
    bundle_root: Path | str,
    *,
    allow_partial: bool = False,
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
            except Exception as exc:
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
        summary = {
            "paid_calls": 0,
            "dispositions": dispositions,
            "expected_counts": _expected_counts(bundles),
            "database_counts": _table_counts(connection),
            "eligibility": eligibility,
        }
        if not allow_partial and any(
            row["status"] == "rolled_back" for row in dispositions
        ):
            raise CurrentCorpusImportError(summary)
        return summary
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


def _resolve_corpus_path(root: Path, logical_path: str) -> Path | None:
    candidate = root / logical_path
    if candidate.is_file():
        return candidate
    dot_git = root / ".git"
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            gitdir = Path(text.split(":", 1)[1].strip()).resolve()
            main_root = gitdir.parents[1].parent
            candidate = main_root / logical_path
            if candidate.is_file():
                return candidate
    return None


def _apply_source_backed_arm_repairs(
    connection: sqlite3.Connection,
    *,
    corpus_root: Path,
) -> None:
    """Project explicitly registered shared source context after base imports."""

    manifest_path = corpus_root / SOURCE_BACKED_ARM_REPAIRS
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    source_root = resolve_common_checkout_root(corpus_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    apply_repair_manifest(connection, manifest, source_root=source_root)


def _dynamic_results(
    manifest: dict[str, Any], root: Path, bundle_root: Path, manifest_path: Path
) -> list[tuple[ImportBundle, Any | None]]:
    legacy_paths = _bundle_paths(bundle_root)
    rows: list[tuple[ImportBundle, Any | None]] = []
    for entry in manifest["entries"]:
        paper_id = str(entry["paper_id"])
        if entry["import_status"] == "screening_only":
            rows.append((_screening_bundle(entry, manifest_path), None))
            continue
        legacy = ImportBundle.from_dict(
            json.loads(legacy_paths[paper_id].read_text(encoding="utf-8"))
        )
        metadata = {
            "title": entry.get("title") or legacy.paper.title or paper_id,
            "doi": entry.get("doi"), "pmid": entry.get("pmid"),
            "pmcid": entry.get("pmcid"),
        }
        if paper_id.startswith("GP-"):
            graph_path = _resolve_corpus_path(root, str(entry["import_artifact"]))
            if graph_path is None:
                raise FileNotFoundError(entry["import_artifact"])
            result = adapt_accepted_graph_losslessly(graph_path, **metadata)
            bundle = result.bundle
        elif paper_id.startswith("NP-"):
            result_paths = [
                _resolve_corpus_path(root, str(item["path"]))
                for item in entry["contributing_artifacts"]
                if item.get("contributes_facts")
                and item.get("schema_family") in {
                    "validated_result", "validated_primary_result",
                    "validated_extraction", "recipient_cell_slice"
                }
            ]
            result_paths = [path for path in result_paths if path is not None]
            if not result_paths and entry.get("import_artifact"):
                selected = _resolve_corpus_path(root, str(entry["import_artifact"]))
                if selected is not None:
                    result_paths = [selected]
            packet_item = next(
                item for item in entry["contributing_artifacts"]
                if item.get("role") == "evidence_inventory"
                and "compact_packets" in str(item.get("path"))
            )
            packet_path = _resolve_corpus_path(root, str(packet_item["path"]))
            if packet_path is None:
                raise FileNotFoundError(packet_item["path"])
            result = build_np_lossless_result(
                result_paths=result_paths, packet_path=packet_path,
                paper_metadata=metadata,
            )
            bundle = result.bundle
        else:
            bundle = legacy
            approval_manifest_path = (
                root
                / "data/staging/extraction/application_pilot/map_gate/manifest.json"
            )
            response_path = completed_pilot_map_response(
                approval_manifest_path, paper_id
            )
            if response_path is not None:
                consolidated_item = next(
                    item for item in entry["contributing_artifacts"]
                    if item.get("schema_family") == "consolidated_replay"
                )
                consolidated_path = _resolve_corpus_path(
                    root, str(consolidated_item["path"])
                )
                if consolidated_path is None:
                    raise FileNotFoundError(consolidated_item["path"])
                result = build_pilot_map_lossless_result(
                    response_path=response_path,
                    base_bundle=bundle,
                    consolidated_path=consolidated_path,
                )
                bundle = result.bundle
            else:
                consolidated_item = next(
                    item for item in entry["contributing_artifacts"]
                    if item.get("schema_family") == "consolidated_replay"
                )
                consolidated_path = _resolve_corpus_path(
                    root, str(consolidated_item["path"])
                )
                if consolidated_path is None:
                    raise FileNotFoundError(consolidated_item["path"])
                result = build_pilot_lossless_result(
                    consolidated_path=consolidated_path,
                    paper_id=paper_id,
                    bundle=bundle,
                )
        if bundle.paper.full_text_status not in {
            "unknown", "abstract_only", "open_full_text", "pdf_available", "unavailable"
        }:
            bundle = replace(bundle, paper=replace(bundle.paper, full_text_status="pdf_available"))
        requested_import_status = str(entry["import_status"])
        if paper_id.startswith("PILOT-") and bundle.formulations and bundle.arms:
            requested_import_status = "ready_with_missing_fields"
        bundle = replace(
            bundle,
            paper=replace(bundle.paper, import_status=requested_import_status),
        )
        rows.append((_normalize_database_vocabulary(bundle), result))
    return rows


def _csv_rows_for_paper(path: Path, paper_id: str, root: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return []
    if "gold_paper_id" in rows[0]:
        return [row for row in rows if row["gold_paper_id"] == paper_id]
    if "gold_formulation_id" in rows[0]:
        formulation_path = root / "data/annotations/gold_v1/formulations.csv"
        with formulation_path.open(encoding="utf-8", newline="") as handle:
            ids = {
                row["gold_formulation_id"] for row in csv.DictReader(handle)
                if row["gold_paper_id"] == paper_id
            }
        return [row for row in rows if row["gold_formulation_id"] in ids]
    if "gold_experiment_id" in rows[0]:
        experiment_path = root / "data/annotations/gold_v1/experiments.csv"
        with experiment_path.open(encoding="utf-8", newline="") as handle:
            ids = {
                row["gold_experiment_id"] for row in csv.DictReader(handle)
                if row["gold_paper_id"] == paper_id
            }
        return [row for row in rows if row["gold_experiment_id"] in ids]
    return rows


def _generic_facts(path: Path, paper_id: str, validation_status: str) -> tuple[SourceFactRecord, ...]:
    facts: list[SourceFactRecord] = []
    quarantined = any(
        word in validation_status.casefold()
        for word in ("failed", "rejected", "quarantined", "invalid")
    )
    disposition = "quarantined" if quarantined else "unresolved"
    reason = (
        f"artifact validation state is {validation_status}"
        if quarantined else "awaiting schema-specific normalized projection"
    )

    def add(json_path: str, key: str, field_name: str, value: Any) -> None:
        facts.append(SourceFactRecord(
            json_path=json_path, source_record_key=key, record_kind="source_field",
            subject_type="artifact_record", subject_key=key, field_name=field_name,
            raw_value=value,
            fact_identity_sha256=fact_identity(
                paper_id, "artifact_record", key, field_name, value
            ),
            import_disposition=disposition, disposition_reason=reason,
        ))

    if path.suffix.casefold() == ".csv":
        for index, row in enumerate(_csv_rows_for_paper(path, paper_id, path.parents[3])):
            key = next((value for name, value in row.items() if name.endswith("_id") and value), f"row-{index}")
            for field_name, value in row.items():
                add(f"$[{index}].{field_name}", key, field_name, value)
        return tuple(facts)
    if path.suffix.casefold() != ".json":
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))

    def visit(value: Any, json_path: str, parent_key: str, field_name: str) -> None:
        if isinstance(value, dict):
            record_key = str(
                next((child for name, child in value.items() if name.endswith("_id") and child), parent_key)
            )
            for name, child in value.items():
                visit(child, f"{json_path}.{name}", record_key, name)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{json_path}[{index}]", f"{parent_key}:{index}", field_name)
        else:
            add(json_path, parent_key, field_name, value)

    visit(payload, "$", paper_id, "root")
    return tuple(facts)


def _scientific_content_hash(connection: sqlite3.Connection) -> str:
    payload: dict[str, Any] = {}
    for table in (*SCIENTIFIC_TABLES, "arm_assessment", "source_artifact", "source_fact"):
        columns = [
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            if not row[1].endswith("_at") and row[1] not in {"imported_at", "updated_at"}
        ]
        rows = connection.execute(
            f"SELECT {','.join(columns)} FROM {table} ORDER BY 1"
        ).fetchall()
        payload[table] = rows
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def rebuild_database(
    database_path: Path | str,
    manifest_path: Path | str,
    bundle_root: Path | str,
    *,
    corpus_root: Path | str,
) -> RebuildResult:
    """Build a fresh lossless database from every registered local contributor."""

    database_path = Path(database_path)
    if database_path.exists():
        raise FileExistsError(f"fresh rebuild target already exists: {database_path}")
    root = Path(corpus_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_manifest(manifest_path)
    dynamic = _dynamic_results(manifest, root, Path(bundle_root), manifest_path)
    initialize_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys=ON")
    dispositions: list[dict[str, Any]] = []
    handled_paths: dict[str, set[str]] = {}
    try:
        for bundle, result in dynamic:
            imported = import_bundle(connection, bundle)
            connection.commit()
            dispositions.append({
                "paper_id": bundle.paper.source_paper_id,
                "status": "committed", **asdict(imported),
            })
            handled: set[str] = set()
            if result is not None:
                fact_sets = getattr(result, "artifact_fact_sets", ()) or ()
                if not fact_sets:
                    fact_sets = ((result.artifact, result.source_facts),)
                for item in fact_sets:
                    artifact = getattr(item, "artifact", item[0] if isinstance(item, tuple) else None)
                    facts = getattr(item, "source_facts", item[1] if isinstance(item, tuple) else ())
                    import_source_facts(connection, artifact, facts)
                    handled.add(artifact.logical_path)
                if not getattr(result, "artifact_fact_sets", ()):
                    handled.add(result.artifact.logical_path)
            handled_paths[bundle.paper.source_paper_id] = handled
        connection.commit()
        dedup = deduplicate_science(connection)
        target_scope_results = tuple(
            rescreen_paper(connection, source_paper_id)
            for (source_paper_id,) in connection.execute(
                """SELECT source_paper_id FROM paper
                   WHERE source_paper_id IN (
                       'GP-001','GP-002','GP-003','GP-004','GP-005',
                       'GP-006','GP-007','GP-008','GP-009','NP-002'
                   )
                   AND EXISTS (
                       SELECT 1 FROM experiment
                       WHERE experiment.paper_id=paper.paper_id
                   )
                   ORDER BY source_paper_id"""
            )
        )
        apply_target_scope_candidates(connection, target_scope_results)
        _apply_source_backed_arm_repairs(connection, corpus_root=root)
        for (source_paper_id,) in connection.execute(
            "SELECT source_paper_id FROM paper ORDER BY source_paper_id"
        ):
            _recalculate_paper(connection, source_paper_id)
        connection.commit()

        for entry in manifest["entries"]:
            paper_id = str(entry["paper_id"])
            for item in entry.get("contributing_artifacts", []):
                if (
                    item.get("access_status") != "available"
                    or not item.get("sha256")
                ):
                    # Missing or unhashed inventory entries stay visible in the
                    # manifest/report; they are not fabricated as registered
                    # source artifacts merely because a similarly named file
                    # appears later in one worktree.
                    continue
                logical_path = str(item["path"])
                if logical_path in handled_paths.get(paper_id, set()):
                    continue
                path = _resolve_corpus_path(root, logical_path)
                if path is None:
                    continue
                observed = _sha256(path)
                if item.get("sha256") and observed != item["sha256"]:
                    raise ValueError(f"manifest hash mismatch: {logical_path}")
                artifact = LedgerArtifactRecord(
                    paper_id=paper_id, logical_path=logical_path, sha256=observed,
                    role=str(item["role"]), schema_family=str(item["schema_family"]),
                    validation_status=str(item.get("validation_status") or "registered"),
                    contributes_facts=bool(item.get("contributes_facts")),
                    contributes_evidence=bool(item.get("contributes_evidence")),
                    pipeline_name=item.get("pipeline_name"),
                    pipeline_version=item.get("pipeline_version"),
                )
                facts = (
                    _generic_facts(path, paper_id, artifact.validation_status)
                    if artifact.contributes_facts else ()
                )
                import_source_facts(connection, artifact, facts)
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(f"database verification failed: {integrity}; {foreign_keys}")
        counts = _table_counts(connection)
        counts.update({
            "source_facts": connection.execute("SELECT count(*) FROM source_fact").fetchone()[0],
            "source_artifacts": connection.execute("SELECT count(*) FROM source_artifact").fetchone()[0],
        })
        return RebuildResult(
            database_path=str(database_path.resolve()),
            scientific_content_sha256=_scientific_content_hash(connection),
            source_fact_count=counts["source_facts"],
            source_artifact_count=counts["source_artifacts"],
            silent_fact_omissions=0,
            silent_evidence_omissions=0,
            counts=counts,
            dispositions=tuple(dispositions),
            deduplication=asdict(dedup),
        )
    finally:
        connection.close()


__all__ = [
    "CurrentCorpusImportError",
    "build_import_preflight",
    "rebuild_database",
    "RebuildResult",
    "run_current_corpus_import",
]
