"""Generic handoff from a screened extraction bundle to the application DB."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from src.database.import_bundle import import_bundle
from src.database.import_contracts import ImportBundle
from src.database.readiness import ReadinessSummary, evaluate_readiness
from src.database.run_current_corpus_import import _generic_facts
from src.database.source_fact_audit import audit_source_fact_coverage
from src.database.source_fact_import import (
    SourceArtifactRecord,
    import_source_facts,
)
from src.init_db import initialize_database
from src.rag.current_corpus_assets import discover_declared_assets
from src.ui.evidence_browser_service import (
    BrowserFilters,
    list_combined_arm_rows,
)


@dataclass(frozen=True)
class ScreenedCandidate:
    """A paper that passed screening and has a normalized extraction bundle."""

    paper_id: str
    title: str
    screening_disposition: str
    source_paths: tuple[Path, ...]
    extraction_bundle_path: Path


@dataclass(frozen=True)
class HandoffResult:
    """Auditable result of sending one paper through the generic application path."""

    paper_id: str
    title: str
    screening_disposition: str
    database_path: Path
    source_paths: tuple[str, ...]
    discovered_assets: tuple[str, ...]
    asset_provenance: tuple[dict[str, Any], ...]
    extraction_artifact: str
    source_fact_count: int
    source_fact_accounting_balanced: bool
    imported_arm_ids: tuple[int, ...]
    readiness: tuple[dict[str, Any], ...]
    visible_in_combined_table: bool
    paper_specific_adapter: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["database_path"] = str(self.database_path)
        return payload


def _load_bundle(path: Path, expected_paper_id: str) -> ImportBundle:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("extraction bundle must be a JSON object")
    bundle_paper_id = str(payload.get("paper", {}).get("source_paper_id", ""))
    if bundle_paper_id != expected_paper_id:
        raise ValueError(
            "candidate paper ID does not match extraction bundle paper ID: "
            f"{expected_paper_id!r} != {bundle_paper_id!r}"
        )
    return ImportBundle.from_dict(payload)


def _readiness_payload(
    experiment_id: int,
    readiness: ReadinessSummary,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "general_usable": readiness.general_usable,
        "nearest_neighbor_ready": readiness.nearest_neighbor_ready,
        "comet_ready": readiness.comet_ready,
        "nearest_neighbor_blockers": list(
            readiness.nearest_neighbor_blockers
        ),
        "comet_blockers": list(readiness.comet_blockers),
        "queue_label": readiness.queue_label,
        "rules_version": readiness.rules_version,
    }


def run_new_paper_handoff(
    candidate: ScreenedCandidate,
    workspace: Path,
) -> HandoffResult:
    """Import one included paper without a paper-specific adapter."""

    if candidate.screening_disposition != "include":
        raise ValueError("new-paper handoff requires an included paper")
    bundle_path = candidate.extraction_bundle_path.resolve()
    bundle = _load_bundle(bundle_path, candidate.paper_id)

    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    database_path = workspace / "lnp_evidence.db"
    initialize_database(database_path)
    assets = discover_declared_assets(candidate.source_paths)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        import_bundle(connection, bundle)
        fact_import = import_source_facts(
            connection,
            SourceArtifactRecord(
                paper_id=candidate.paper_id,
                logical_path=str(bundle_path),
                sha256=hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
                role="validated_extraction",
                schema_family=bundle.schema_version,
                validation_status="validated",
                contributes_facts=True,
                contributes_evidence=bool(bundle.evidence),
                pipeline_name="generic-new-paper-handoff",
                pipeline_version="v1",
            ),
            _generic_facts(bundle_path, candidate.paper_id, "validated"),
        )
        coverage = audit_source_fact_coverage(
            connection, fact_import.artifact_id
        )
        arm_ids = tuple(
            int(row[0])
            for row in connection.execute(
                """
                SELECT experiment.experiment_id
                FROM experiment JOIN paper USING(paper_id)
                WHERE paper.source_paper_id=?
                ORDER BY experiment.experiment_id
                """,
                (candidate.paper_id,),
            )
        )
        readiness = tuple(
            _readiness_payload(arm_id, evaluate_readiness(connection, arm_id))
            for arm_id in arm_ids
        )
        connection.commit()

    visible_ids = {
        row.experiment_id
        for row in list_combined_arm_rows(
            BrowserFilters(paper_ids=(candidate.paper_id,)),
            database_path=database_path,
        )
    }
    asset_provenance = tuple(asdict(asset) for asset in assets)
    return HandoffResult(
        paper_id=candidate.paper_id,
        title=candidate.title,
        screening_disposition=candidate.screening_disposition,
        database_path=database_path,
        source_paths=tuple(str(path.resolve()) for path in candidate.source_paths),
        discovered_assets=tuple(asset.filename for asset in assets),
        asset_provenance=asset_provenance,
        extraction_artifact=str(bundle_path),
        source_fact_count=coverage.source_count,
        source_fact_accounting_balanced=(
            coverage.source_count == coverage.accounted_count
            and not coverage.silent_omissions
            and not coverage.unresolved_evidence
        ),
        imported_arm_ids=arm_ids,
        readiness=readiness,
        visible_in_combined_table=bool(arm_ids)
        and set(arm_ids).issubset(visible_ids),
    )


def write_handoff_report(result: HandoffResult, output_path: Path) -> Path:
    """Write the smoke-gate result as stable, human-readable JSON."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


__all__ = [
    "HandoffResult",
    "ScreenedCandidate",
    "run_new_paper_handoff",
    "write_handoff_report",
]
