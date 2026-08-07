"""Normalize recovered PILOT provenance into conservative review bundles."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from src.database.import_contracts import (
    EvidenceRecord,
    ImportBundle,
    PaperRecord,
    ReviewRecord,
    SourceArtifactRecord,
)
from src.database.recover_pilot_artifacts import PilotRecoveryResult
from src.database.lossless_adapter import AdapterCoverage, LosslessAdapterResult
from src.database.scientific_identity import fact_identity
from src.database.source_fact_import import (
    SourceArtifactRecord as LedgerArtifactRecord,
    SourceFactEvidenceRecord,
    SourceFactRecord,
)


def build_blocked_pilot_bundle(
    recovery: PilotRecoveryResult,
    manifest_entry: dict[str, Any],
) -> ImportBundle:
    """Create a visible metadata/review bundle without unsupported science.

    A source inventory is evidence discovery, not an accepted extraction result.
    Consequently recovered inventories are preserved as artifacts while all
    experimental rows remain absent until a validated extraction is available.
    """

    paper_id = str(manifest_entry["paper_id"])
    if paper_id != recovery.paper_id:
        raise ValueError("manifest and recovery paper IDs differ")
    artifacts: list[SourceArtifactRecord] = []
    evidence: list[EvidenceRecord] = []
    if recovery.status == "recovered":
        assert recovery.source_sha256 is not None
        assert recovery.inventory_sha256 is not None
        artifacts.extend(
            [
                SourceArtifactRecord(
                    artifact_id=f"{paper_id}:source-html",
                    path=recovery.source_logical_path,
                    sha256=recovery.source_sha256,
                    source_kind="html",
                    pipeline_name="application_pilot_source_recovery",
                    pipeline_version="day2/v1",
                ),
                SourceArtifactRecord(
                    artifact_id=f"{paper_id}:source-inventory",
                    path=recovery.inventory_logical_path,
                    sha256=recovery.inventory_sha256,
                    source_kind="source_inventory",
                    pipeline_name="unverified_recovered_source_inventory",
                    pipeline_version=(
                        f"{recovery.inventory_version};observed_sha256_unverified"
                    ),
                ),
            ]
        )
        paper_artifact_id = f"{paper_id}:source-inventory"
        reason_code = "recovered_inventory_unverified"
        notes = (
            "The source matches its approved manifest hash. The inventory hash "
            "was observed during recovery but had no approved expected hash, so "
            "its excerpts are quarantined and no experimental rows were imported."
        )
        full_text_status = "available"
        if recovery.inventory_bytes is None:
            raise ValueError("recovered inventory has no bound validation bytes")
        if (
            hashlib.sha256(recovery.inventory_bytes).hexdigest()
            != recovery.inventory_sha256
        ):
            raise ValueError("inventory content does not match recorded SHA-256")
        inventory = json.loads(recovery.inventory_bytes.decode("utf-8"))
        for block in inventory["evidence_blocks"]:
            evidence_id = str(block.get("evidence_id", "")).strip()
            evidence_text = str(block.get("text", "")).strip()
            if not evidence_id or not evidence_text:
                raise ValueError("inventory evidence requires an ID and source text")
            tags = block.get("retrieval_tags") or []
            evidence.append(
                EvidenceRecord(
                    record_id=evidence_id,
                    paper_id=paper_id,
                    artifact_id=f"{paper_id}:source-inventory",
                    field_name=",".join(str(tag) for tag in tags) or "source_inventory",
                    evidence_location_type="source_inventory_block",
                    extraction_method="deterministic_source_inventory_recovery",
                    extraction_confidence="unverified_recovery",
                    evidence_text=evidence_text,
                    section_name=block.get("heading"),
                    page_number=(
                        str(block["page_number"])
                        if block.get("page_number") is not None
                        else None
                    ),
                    verification_status="unreviewed",
                    reviewer_notes=(
                        "Quarantined recovered source excerpt; its inventory had "
                        "no approved expected hash and no experimental entity "
                        "relationship has been validated."
                    ),
                )
            )
    else:
        artifacts.append(
            SourceArtifactRecord(
                artifact_id=f"{paper_id}:screening-manifest",
                path="data/manifests/current_corpus_lanes/pilot_v1.json",
                sha256=str(manifest_entry["manifest_sha256"]),
                source_kind="screening_manifest",
                pipeline_name="day1_current_corpus_inventory",
                pipeline_version="v1",
            )
        )
        paper_artifact_id = f"{paper_id}:screening-manifest"
        reason_code = "source_file_unavailable"
        notes = recovery.reason
        full_text_status = "unavailable"
    metadata = manifest_entry.get("publication_metadata") or {}
    return ImportBundle(
        artifacts=tuple(artifacts),
        paper=PaperRecord(
            source_paper_id=paper_id,
            artifact_id=paper_artifact_id,
            title=str(manifest_entry["title"]),
            source_type="full_text",
            retrieval_date=str(manifest_entry.get("last_checked", "2026-08-06")),
            import_status="needs_review",
            pmid=manifest_entry.get("pmid"),
            pmcid=manifest_entry.get("pmcid"),
            doi=manifest_entry.get("doi"),
            journal=metadata.get("journal"),
            publication_year=metadata.get("publication_year"),
            full_text_status=full_text_status,
            screening_reason=notes,
        ),
        reviews=(
            ReviewRecord(
                record_id=f"{paper_id}:review:validated-extraction",
                paper_id=paper_id,
                artifact_id=paper_artifact_id,
                reason_code=reason_code,
                status="blocked",
                evidence_ids=tuple(record.record_id for record in evidence),
                notes=notes,
            ),
        ),
        evidence=tuple(evidence),
    )


def build_pilot_lossless_result(
    *,
    consolidated_path: Path,
    paper_id: str,
    bundle: ImportBundle,
) -> LosslessAdapterResult:
    """Retain the rejected pilot replay as quarantined source facts.

    These facts remain queryable and evidence-linked, but are deliberately not
    promoted into canonical scientific rows until their source provenance and
    failed formal-acceptance findings are resolved.
    """

    path = Path(consolidated_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    paper = next(
        row for row in payload["extraction"]["papers"]
        if row["paper_id"] == paper_id
    )
    artifact = LedgerArtifactRecord(
        paper_id=paper_id,
        logical_path=path.as_posix(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        role="primary_extraction",
        schema_family="application_pilot_consolidated",
        validation_status="quarantined",
        contributes_facts=True,
        contributes_evidence=True,
        pipeline_name="application_pilot_provider_free_replay",
        pipeline_version=str(payload.get("status") or "unknown"),
    )
    reason = (
        "Consolidated pilot replay did not pass the accepted provenance and "
        "formal-validation gate; retained for explicit review."
    )
    facts: list[SourceFactRecord] = []

    def add(
        json_path: str,
        record_key: str,
        record_kind: str,
        subject_type: str,
        field_name: str,
        raw_value: Any,
        evidence_ids: list[str] | None = None,
    ) -> None:
        facts.append(
            SourceFactRecord(
                json_path=json_path,
                source_record_key=record_key,
                record_kind=record_kind,
                subject_type=subject_type,
                subject_key=record_key,
                field_name=field_name,
                raw_value=raw_value,
                canonical_value=(
                    raw_value.get("canonical_value")
                    if isinstance(raw_value, dict)
                    else None
                ),
                fact_identity_sha256=fact_identity(
                    paper_id, record_kind, record_key, field_name, raw_value
                ),
                import_disposition="quarantined",
                disposition_reason=reason,
                evidence=tuple(
                    SourceFactEvidenceRecord(
                        source_evidence_key=str(evidence_id),
                        resolution_status="unresolved",
                        resolution_reason="pilot source evidence awaits provenance closure",
                    )
                    for evidence_id in (evidence_ids or [])
                ),
            )
        )

    paper_index = payload["extraction"]["papers"].index(paper)
    base = f"$.extraction.papers[{paper_index}]"
    add(f"{base}.paper_id", paper_id, "paper_field", "paper", "paper_id", paper_id)
    for index, row in enumerate(paper.get("shared_facts", [])):
        field_name = str(row.get("field_name") or f"shared-{index}")
        add(
            f"{base}.shared_facts[{index}]", f"shared-{index}",
            "shared_fact", field_name.split(".", 1)[0], field_name, row,
            list(row.get("evidence_ids", [])),
        )
    for experiment_index, experiment in enumerate(paper.get("experiments", [])):
        experiment_id = str(experiment.get("experiment_id") or experiment_index)
        add(
            f"{base}.experiments[{experiment_index}].candidate_id",
            experiment_id, "experiment_metadata", "experiment", "candidate_id",
            experiment.get("candidate_id"),
        )
        add(
            f"{base}.experiments[{experiment_index}].experiment_id",
            experiment_id, "experiment_metadata", "experiment", "experiment_id",
            experiment_id,
        )
        for fact_index, row in enumerate(experiment.get("facts", [])):
            field_name = str(row.get("field_name") or f"fact-{fact_index}")
            add(
                f"{base}.experiments[{experiment_index}].facts[{fact_index}]",
                experiment_id, "experiment_fact", "experiment", field_name, row,
                list(row.get("evidence_ids", [])),
            )
    for collection, record_kind in (
        ("quarantined_conflicts", "quarantined_conflict"),
        ("validation_findings", "validation_finding"),
    ):
        for index, row in enumerate(paper.get(collection, [])):
            add(
                f"{base}.{collection}[{index}]", f"{record_kind}-{index}",
                record_kind, "review", record_kind, row,
                list(row.get("evidence_ids", [])) if isinstance(row, dict) else [],
            )
    return LosslessAdapterResult(
        bundle=bundle,
        artifact=artifact,
        source_facts=tuple(facts),
        coverage=AdapterCoverage(
            source_experiments=len(paper.get("experiments", [])),
            source_fields=len(facts),
            unresolved_items=(
                len(paper.get("quarantined_conflicts", []))
                + len(paper.get("validation_findings", []))
            ),
            silent_omissions=0,
        ),
        contributing_artifacts=(artifact,),
    )


__all__ = ["build_blocked_pilot_bundle", "build_pilot_lossless_result"]
