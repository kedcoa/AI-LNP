"""Normalize recovered PILOT provenance into conservative review bundles."""

from __future__ import annotations

import json
import hashlib
from typing import Any

from src.database.import_contracts import (
    EvidenceRecord,
    ImportBundle,
    PaperRecord,
    ReviewRecord,
    SourceArtifactRecord,
)
from src.database.recover_pilot_artifacts import PilotRecoveryResult


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


__all__ = ["build_blocked_pilot_bundle"]
