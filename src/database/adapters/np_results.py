"""Normalize validated NP extraction results into an evidence-preserving bundle."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from src.database.import_contracts import (
    ArmRecord, ComponentRecord, EvidenceRecord, FieldEvidenceLink,
    FormulationRecord, ImportBundle, OutcomeRecord, PaperRecord, ReviewRecord,
    SourceArtifactRecord,
)
from src.database.reconcile_np002 import load_and_reconcile
from src.database.lossless_adapter import (
    AdapterCoverage,
    ArtifactFactSet,
    LosslessAdapterResult,
)
from src.database.scientific_identity import fact_identity
from src.database.source_fact_import import (
    SourceArtifactRecord as LedgerArtifactRecord,
    SourceFactEvidenceRecord,
    SourceFactRecord,
)


CONFLICT_EVIDENCE_FIELDS = {
    "composition": "composition_raw",
    "formulation_name": "formulation_name",
    "composition_basis": "composition_basis",
    "np_ratio": "np_ratio",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value(field: Any) -> Any:
    return field.get("value") if isinstance(field, dict) else field


def _eids(field: Any) -> list[str]:
    return list(field.get("evidence_ids", [])) if isinstance(field, dict) else []


def _slice_of(record: dict[str, Any], default: str) -> str:
    slices = record.get("source_slices")
    return str(slices[0] if slices else record.get("source_slice", default))


def _artifact_id(slice_name: str) -> str:
    return f"artifact::{slice_name}"


def _record_id(paper_id: str, kind: str, raw_id: str) -> str:
    return f"{paper_id}::{kind}::{raw_id}"


def _repo_root(path: Path) -> Path | None:
    for parent in (path.resolve(), *path.resolve().parents):
        if (parent / "src/database").is_dir() and (parent / "data").is_dir():
            return parent
    return None


def _canonical_path(path: Path, repo_root: Path | None) -> str:
    resolved = path.resolve()
    if repo_root is not None:
        try:
            return resolved.relative_to(repo_root).as_posix()
        except ValueError:
            pass
    return path.name


def _source_artifact(path: Path, kind: str, pipeline_name: str) -> SourceArtifactRecord:
    digest = _sha(path)
    root = _repo_root(path)
    return SourceArtifactRecord(
        artifact_id=f"artifact::{kind}::{digest[:16]}",
        path=_canonical_path(path, root), sha256=digest, source_kind=kind,
        pipeline_name=pipeline_name,
    )


def build_np_bundle(
    *,
    result_paths: Iterable[Path],
    packet_path: Path,
    paper_metadata: dict[str, Any],
) -> ImportBundle:
    paths = sorted((Path(path) for path in result_paths), key=lambda path: str(path))
    if not paths:
        raise ValueError("at least one result path is required")
    payloads = []
    for path in paths:
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    paper_ids = {payload.get("paper_id") for payload in payloads}
    if len(paper_ids) != 1:
        raise ValueError("result paths must belong to one paper")
    paper_id = str(next(iter(paper_ids)))
    default_slice = paper_id if len(paths) == 1 else paths[0].parent.name
    merged = load_and_reconcile(paths) if len(paths) > 1 else _single(payloads[0], default_slice)

    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    packet_evidence = {row["evidence_id"]: row for row in packet.get("evidence", [])}
    packet_sources = {row["source_id"]: row for row in packet.get("sources", [])}
    repo_root = _repo_root(Path(packet_path))
    supplemental_claim_paths: list[Path] = []
    if repo_root is not None:
        supplemental_claim_paths = sorted(
            (repo_root / "data/staging/extraction/v12_docling_candidates").glob(
                f"{paper_id}-*/claims.json"
            )
        )
    packet_artifact = _source_artifact(Path(packet_path), "source_inventory", "compact_packet")
    evidence_artifact: dict[str, str] = {
        evidence_id: packet_artifact.artifact_id for evidence_id in packet_evidence
    }
    docling_artifacts: list[SourceArtifactRecord] = []
    for claims_path in supplemental_claim_paths:
        claims_artifact = _source_artifact(claims_path, "table", "docling_supported_claims")
        docling_artifacts.append(claims_artifact)
        for claim in json.loads(claims_path.read_text(encoding="utf-8")):
            for item in claim.get("evidence", []):
                packet_evidence.setdefault(
                    item["evidence_id"],
                    {
                        "evidence_id": item["evidence_id"],
                        "text": item.get("quote"),
                        "source_ids": [item.get("source_id")],
                    },
                )
                packet_sources.setdefault(
                    item.get("source_id"),
                    {
                        "source_id": item.get("source_id"),
                        "block_type": item.get("locator_type", "table_cell"),
                        "section": item.get("panel_label"),
                    },
                )
                evidence_artifact.setdefault(item["evidence_id"], claims_artifact.artifact_id)

    local_source_artifacts: list[SourceArtifactRecord] = []
    if repo_root is not None and paper_metadata.get("pmcid"):
        source_dir = repo_root / "data/staging/new_papers" / paper_id
        for suffix, source_kind in (("html", "html"), ("pdf", "pdf")):
            source_path = source_dir / f"{paper_metadata['pmcid']}.{suffix}"
            if source_path.is_file():
                local_source_artifacts.append(
                    _source_artifact(source_path, source_kind, "local_fulltext_copy")
                )

    result_artifacts = tuple(
        _source_artifact(
            path, "validated_extraction",
            "compact" if paper_id == "NP-001" else "isolated_liver_cell",
        ) for path in paths
    )
    artifacts = (
        result_artifacts + (packet_artifact,) + tuple(docling_artifacts)
        + tuple(local_source_artifacts)
    )
    slice_names = [paper_id] if len(paths) == 1 else [path.parent.name for path in paths]
    artifact_by_slice = {
        slice_name: artifact.artifact_id
        for slice_name, artifact in zip(slice_names, result_artifacts, strict=True)
    }
    primary_artifact = artifacts[0].artifact_id

    evidence_records: dict[str, EvidenceRecord] = {}
    links: list[FieldEvidenceLink] = []

    def link(entity_type: str, entity_id: str, field_name: str, raw_field: Any, slice_name: str, *, arm_id=None, outcome_id=None) -> None:
        ids = _eids(raw_field)
        if _value(raw_field) is not None and not ids:
            raise ValueError(f"populated field lacks evidence: {entity_id}.{field_name}")
        namespaced = []
        for raw_eid in ids:
            if raw_eid not in packet_evidence:
                raise ValueError(f"unknown packet evidence: {raw_eid}")
            eid = f"{slice_name}::{entity_type}::{entity_id}::{field_name}::{raw_eid}"
            namespaced.append(eid)
            if eid not in evidence_records:
                item = packet_evidence[raw_eid]
                sources = [
                    packet_sources.get(source_id, {"source_id": source_id})
                    for source_id in item.get("source_ids", [])
                ]
                source = sources[0] if sources else {}
                locators = [
                    {key: value for key, value in row.items() if value is not None}
                    for row in sources
                ]
                unverified_source_paths = list(dict.fromkeys(
                    str(row["source_path"])
                    for row in sources if row.get("source_path")
                ))
                evidence_records[eid] = EvidenceRecord(
                    record_id=eid,
                    paper_id=paper_id,
                    artifact_id=evidence_artifact[raw_eid],
                    field_name=field_name,
                    evidence_location_type=str(source.get("block_type") or "text"),
                    extraction_method="validated_extraction",
                    extraction_confidence="requires_review",
                    evidence_text=item.get("text"),
                    structured_evidence={
                        "source_locators": locators,
                        "immediate_artifact_id": evidence_artifact[raw_eid],
                        "available_local_source_artifact_ids": [
                            artifact.artifact_id for artifact in local_source_artifacts
                        ],
                        "unverified_source_paths": unverified_source_paths,
                    },
                    arm_id=arm_id,
                    outcome_id=outcome_id,
                    section_name=source.get("section"),
                    page_number=str(source["page_number"]) if source.get("page_number") is not None else None,
                    verification_status="unreviewed",
                    reviewer_notes=f"Source slice: {slice_name}; packet evidence: {raw_eid}",
                )
        if namespaced:
            links.append(FieldEvidenceLink(
                paper_id=paper_id, entity_type=entity_type, entity_id=entity_id,
                field_name=field_name, evidence_ids=tuple(namespaced),
                verification_status="unreviewed", notes=f"Source slice: {slice_name}",
            ))

    formulations = []
    formulation_ids = {}
    for raw in merged["formulations"]:
        raw_id = raw["formulation_id"]
        slice_name = (raw.get("source_slices") or [default_slice])[0]
        rid = _record_id(paper_id, "formulation", raw_id)
        formulation_ids[raw_id] = rid
        def supported(field_name: str) -> Any:
            field = raw.get(field_name)
            return _value(field) if _eids(field) else None
        record = FormulationRecord(
            record_id=rid, paper_id=paper_id, artifact_id=artifact_by_slice[slice_name],
            formulation_name=supported("formulation_name"),
            composition_raw=supported("composition"),
            composition_basis=supported("composition_basis"),
            np_ratio=supported("np_ratio"),
            formulation_review_status="unreviewed",
        )
        formulations.append(record)
        for dst, src in (("formulation_name", "formulation_name"), ("composition_raw", "composition"), ("composition_basis", "composition_basis"), ("np_ratio", "np_ratio")):
            link("formulation", rid, dst, raw.get(src) if _eids(raw.get(src)) else None, slice_name)

    reviews: list[ReviewRecord] = []
    components = []
    molar_ratio_totals: dict[tuple[str, str], float] = {}
    component_counts: dict[tuple[str, str], int] = {}
    numeric_molar_ratio_counts: dict[tuple[str, str], int] = {}
    for raw in merged["components"]:
        unit = _value(raw.get("amount_unit"))
        amount = _value(raw.get("amount"))
        key = (_slice_of(raw, default_slice), raw["formulation_id"])
        component_counts[key] = component_counts.get(key, 0) + 1
        if (
            isinstance(unit, str)
            and re.fullmatch(r"\s*molar[- ]ratio parts\s*", unit, re.IGNORECASE)
            and isinstance(amount, (int, float))
            and not isinstance(amount, bool)
        ):
            molar_ratio_totals[key] = molar_ratio_totals.get(key, 0.0) + float(amount)
            numeric_molar_ratio_counts[key] = (
                numeric_molar_ratio_counts.get(key, 0) + 1
            )
    for raw in merged["components"]:
        slice_name = _slice_of(raw, default_slice)
        rid = _record_id(paper_id, "component", raw["component_id"])
        amount = _value(raw.get("amount"))
        amount_unit = _value(raw.get("amount_unit"))
        explicit_mol_percent = bool(
            amount is not None
            and isinstance(amount_unit, str)
            and re.fullmatch(r"\s*mol\s*%\s*", amount_unit, re.IGNORECASE)
        )
        ratio_key = (slice_name, raw["formulation_id"])
        safe_molar_ratio_parts = bool(
            amount is not None
            and isinstance(amount_unit, str)
            and re.fullmatch(
                r"\s*molar[- ]ratio parts\s*", amount_unit, re.IGNORECASE
            )
            and numeric_molar_ratio_counts.get(ratio_key, 0)
            == component_counts.get(ratio_key, -1)
            and abs(molar_ratio_totals.get(ratio_key, float("nan")) - 100.0) < 1e-9
        )
        is_molar_percentage = explicit_mol_percent or safe_molar_ratio_parts
        raw_amount_note = (
            f"Reported amount: {amount} {amount_unit}"
            if amount is not None and amount_unit is not None and not is_molar_percentage
            else None
        )
        record = ComponentRecord(
            record_id=rid, paper_id=paper_id, artifact_id=artifact_by_slice[slice_name],
            formulation_id=formulation_ids[raw["formulation_id"]],
            component_name_reported=_value(raw.get("identity")),
            component_role=_value(raw.get("role")),
            molar_percentage=amount if is_molar_percentage else None,
            percentage_unit="mol%" if is_molar_percentage else None,
            component_review_status="unreviewed", identity_notes=raw_amount_note,
            amount_value=amount,
            amount_unit=amount_unit,
            amount_raw=(
                None if amount is None else f"{amount} {amount_unit or ''}".strip()
            ),
        )
        components.append(record)
        for dst, src in (("component_name_reported", "identity"), ("component_role", "role")):
            link("component", rid, dst, raw.get(src), slice_name)
        if is_molar_percentage:
            link("component", rid, "molar_percentage", raw.get("amount"), slice_name)
            link("component", rid, "percentage_unit", raw.get("amount_unit"), slice_name)
        elif raw_amount_note:
            link("component", rid, "identity_notes", raw.get("amount"), slice_name)
            link("component", rid, "identity_notes", raw.get("amount_unit"), slice_name)
            note_evidence = tuple(
                evidence_id for evidence_id, evidence_record in evidence_records.items()
                if evidence_record.field_name == "identity_notes"
                and f"::{rid}::" in evidence_id
            )
            reviews.append(ReviewRecord(
                record_id=f"{rid}::review::reported-amount", paper_id=paper_id,
                artifact_id=artifact_by_slice[slice_name], reason_code="unsupported_value",
                status="incomplete", evidence_ids=note_evidence,
                field_name="identity_notes", notes=raw_amount_note,
            ))

    outcomes_by_experiment: dict[str, list[dict[str, Any]]] = {}
    for raw in merged["outcomes"]:
        outcomes_by_experiment.setdefault(raw["experiment_id"], []).append(raw)

    arms = []
    arm_ids = {}
    for raw in merged["experiments"]:
        slice_name = _slice_of(raw, default_slice)
        rid = _record_id(paper_id, "arm", raw["experiment_id"])
        arm_ids[raw["experiment_id"]] = rid
        related = outcomes_by_experiment.get(raw["experiment_id"], [])
        assay_field = related[0].get("assay") if len(related) == 1 else None
        comparator_field = related[0].get("comparator") if len(related) == 1 else None
        missing = []
        for reason, field in (("missing_dose", raw.get("dose")), ("missing_timepoint", raw.get("timepoint")), ("missing_comparator", comparator_field)):
            if _value(field) is None:
                missing.append(reason)
        if not missing:
            missing.append("needs_human_verification")
        record = ArmRecord(
            record_id=rid, paper_id=paper_id, artifact_id=artifact_by_slice[slice_name],
            formulation_id=formulation_ids[raw["formulation_id"]],
            cell_type=_value(raw.get("therapeutic_target_cell")) or _value(raw.get("delivery_recipient_cell")) or "Unknown",
            cell_source=_value(raw.get("delivery_recipient_cell")), tissue_or_organ=_value(raw.get("tissue_or_organ")),
            species=_value(raw.get("species")), disease_model=_value(raw.get("disease_model")),
            in_vitro_in_vivo=_value(raw.get("experimental_context")), payload_type=_value(raw.get("payload_type")),
            payload_name=_value(raw.get("payload_name")), payload_encoded_product=_value(raw.get("encoded_product")),
            payload_molecular_target=_value(raw.get("molecular_target")), dose=_value(raw.get("dose")),
            dose_unit=_value(raw.get("dose_unit")), route=_value(raw.get("route")), timepoint=_value(raw.get("timepoint")),
            timepoint_unit=_value(raw.get("timepoint_unit")), assay=_value(assay_field),
            comparator_description=_value(comparator_field), completeness_status="quarantined",
            verification_status="unreviewed", quarantine_reason="; ".join(missing) or "Needs human verification",
        )
        arms.append(record)
        mapping = {
            "cell_type": "therapeutic_target_cell", "cell_source": "delivery_recipient_cell", "tissue_or_organ": "tissue_or_organ",
            "species": "species", "disease_model": "disease_model", "in_vitro_in_vivo": "experimental_context",
            "payload_type": "payload_type", "payload_name": "payload_name", "payload_encoded_product": "encoded_product",
            "payload_molecular_target": "molecular_target", "dose": "dose", "dose_unit": "dose_unit", "route": "route",
            "timepoint": "timepoint", "timepoint_unit": "timepoint_unit",
        }
        for dst, src in mapping.items():
            field = raw.get(src)
            if dst == "cell_type" and _value(field) is None:
                field = raw.get("delivery_recipient_cell")
            link("arm", rid, dst, field, slice_name, arm_id=rid)
        link("arm", rid, "assay", assay_field, slice_name, arm_id=rid)
        link("arm", rid, "comparator_description", comparator_field, slice_name, arm_id=rid)
        review_evidence = tuple(
            evidence_id
            for evidence_id, evidence_record in evidence_records.items()
            if evidence_record.arm_id == rid and evidence_record.outcome_id is None
        )
        for index, reason in enumerate(missing):
            reviews.append(ReviewRecord(
                record_id=f"{rid}::review::{index}", paper_id=paper_id,
                artifact_id=artifact_by_slice[slice_name], reason_code=reason,
                status="quarantined" if review_evidence else "blocked",
                evidence_ids=review_evidence, arm_id=rid,
            ))

    outcomes = []
    for raw in merged["outcomes"]:
        slice_name = _slice_of(raw, default_slice)
        arm_id = arm_ids[raw["experiment_id"]]
        rid = _record_id(paper_id, "outcome", raw["outcome_id"])
        numeric = _value(raw.get("outcome_value"))
        qualitative = _value(raw.get("qualitative_outcome"))
        value_status = "reported" if numeric is not None else ("qualitative_only" if qualitative else "missing")
        endpoint = _value(raw.get("endpoint")) or "Unspecified outcome"
        record = OutcomeRecord(
            record_id=rid, paper_id=paper_id, artifact_id=artifact_by_slice[slice_name], arm_id=arm_id,
            endpoint_family="reported outcome", endpoint_name=endpoint, value_status=value_status,
            outcome_value=numeric, outcome_unit=_value(raw.get("outcome_unit")), qualitative_outcome=qualitative,
        )
        outcomes.append(record)
        link("outcome", rid, "endpoint_family", raw.get("endpoint"), slice_name, arm_id=arm_id, outcome_id=rid)
        link("outcome", rid, "endpoint_name", raw.get("endpoint"), slice_name, arm_id=arm_id, outcome_id=rid)
        link("outcome", rid, "outcome_value", raw.get("outcome_value"), slice_name, arm_id=arm_id, outcome_id=rid)
        link("outcome", rid, "outcome_unit", raw.get("outcome_unit"), slice_name, arm_id=arm_id, outcome_id=rid)
        link("outcome", rid, "qualitative_outcome", raw.get("qualitative_outcome"), slice_name, arm_id=arm_id, outcome_id=rid)

    for index, conflict in enumerate(merged.get("conflicts", [])):
        evidence_field = CONFLICT_EVIDENCE_FIELDS.get(
            conflict.get("field_name"), conflict.get("field_name")
        )
        def resolve_side(
            raw_ids: list[str], formulation_source_ids: list[str]
        ) -> tuple[str, ...]:
            normalized_formulation_ids = {
                _record_id(paper_id, "formulation", source_id)
                for source_id in formulation_source_ids
            }
            return tuple(
                record_id for record_id, record in evidence_records.items()
                if record.field_name == evidence_field
                and any(
                    f"::{formulation_id}::" in record_id
                    for formulation_id in normalized_formulation_ids
                )
                and any(record_id.endswith(f"::{raw_id}") for raw_id in raw_ids)
            )
        left_evidence = resolve_side(
            conflict.get("left_evidence_ids", []),
            conflict.get("left_formulation_ids", []),
        )
        right_evidence = resolve_side(
            conflict.get("right_evidence_ids", []),
            [conflict.get("right_formulation_id")],
        )
        conflict_evidence = tuple(dict.fromkeys((*left_evidence, *right_evidence)))
        fully_supported = bool(left_evidence and right_evidence)
        conflict_notes = dict(conflict)
        conflict_notes["left_resolved_evidence_ids"] = list(left_evidence)
        conflict_notes["right_resolved_evidence_ids"] = list(right_evidence)
        reviews.append(ReviewRecord(
            record_id=f"{paper_id}::conflict::{index}", paper_id=paper_id,
            artifact_id=primary_artifact, reason_code="conflicting_formulation",
            status="conflict" if fully_supported else "blocked",
            evidence_ids=conflict_evidence,
            field_name=conflict.get("field_name"),
            notes=json.dumps(conflict_notes, sort_keys=True),
        ))
    for index, item in enumerate(merged.get("unresolved_items", [])):
        text = item["text"] if isinstance(item, dict) else str(item)
        slice_name = item.get("source_slice", default_slice) if isinstance(item, dict) else default_slice
        reviews.append(ReviewRecord(
            record_id=f"{paper_id}::unresolved::{index}", paper_id=paper_id,
            artifact_id=artifact_by_slice[slice_name], reason_code="unsupported_value",
            status="incomplete", notes=text,
        ))

    return ImportBundle(
        paper=PaperRecord(
            source_paper_id=paper_id, artifact_id=primary_artifact,
            title=paper_metadata["title"], source_type="research_article",
            retrieval_date="2026-08-06", screening_status="include", import_status="needs_review",
            doi=paper_metadata.get("doi"), pmid=paper_metadata.get("pmid"), pmcid=paper_metadata.get("pmcid"),
            full_text_status="available",
        ), artifacts=artifacts, formulations=tuple(formulations), components=tuple(components),
        arms=tuple(arms), outcomes=tuple(outcomes), evidence=tuple(evidence_records.values()),
        field_evidence_links=tuple(links), reviews=tuple(reviews),
    )


def _single(payload: dict[str, Any], slice_name: str) -> dict[str, Any]:
    merged = {key: list(payload.get(key, [])) for key in ("formulations", "components", "experiments", "outcomes")}
    for kind in merged.values():
        for row in kind:
            row["source_slice"] = slice_name
    for row in merged["formulations"]:
        row["source_slices"] = [slice_name]
    merged["unresolved_items"] = [{"source_slice": slice_name, "text": text} for text in payload.get("unresolved_items", [])]
    merged["conflicts"] = []
    return merged


def write_bundle(bundle: ImportBundle, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(bundle.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
    return path


def _source_field_facts(path: Path) -> tuple[SourceFactRecord, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    paper_id = str(payload["paper_id"])
    facts: list[SourceFactRecord] = []

    def add(
        json_path: str,
        record_key: str,
        record_kind: str,
        subject_type: str,
        field_name: str,
        raw_value: Any,
    ) -> None:
        evidence_ids = _eids(raw_value)
        value = _value(raw_value)
        status = raw_value.get("status") if isinstance(raw_value, dict) else None
        reason = (
            raw_value.get("missing_reason")
            if isinstance(raw_value, dict)
            else None
        )
        facts.append(
            SourceFactRecord(
                json_path=json_path,
                source_record_key=record_key,
                record_kind=record_kind,
                subject_type=subject_type,
                subject_key=record_key,
                field_name=field_name,
                raw_value=raw_value,
                canonical_value=value,
                fact_identity_sha256=fact_identity(
                    paper_id, record_kind, record_key, field_name, raw_value
                ),
                import_disposition="unresolved",
                disposition_reason=(
                    reason
                    or ("explicitly missing" if status == "missing" else "awaiting normalized projection")
                ),
                evidence=tuple(
                    SourceFactEvidenceRecord(
                        source_evidence_key=str(evidence_id),
                        resolution_status="unresolved",
                        resolution_reason="awaiting canonical evidence import",
                    )
                    for evidence_id in evidence_ids
                ),
            )
        )

    for field_name, value in payload.items():
        if field_name in {
            "formulations", "components", "experiments", "outcomes",
            "unresolved_items", "eligibility",
        }:
            continue
        add(f"$.{field_name}", paper_id, "paper_field", "paper", field_name, value)
    for field_name, value in payload.get("eligibility", {}).items():
        add(
            f"$.eligibility.{field_name}", paper_id, "eligibility_field",
            "paper", field_name, value,
        )
    collections = {
        "formulations": ("formulation_id", "formulation"),
        "components": ("component_id", "component"),
        "experiments": ("experiment_id", "experiment"),
        "outcomes": ("outcome_id", "outcome"),
    }
    for collection, (id_field, subject_type) in collections.items():
        for index, row in enumerate(payload.get(collection, [])):
            record_key = str(row.get(id_field) or f"{subject_type}-{index}")
            for field_name, value in row.items():
                add(
                    f"$.{collection}[{index}].{field_name}", record_key,
                    f"{subject_type}_field", subject_type, field_name, value,
                )
    for index, value in enumerate(payload.get("unresolved_items", [])):
        add(
            f"$.unresolved_items[{index}]", f"unresolved-{index}",
            "unresolved_item", "review", "unresolved_item", value,
        )
    return tuple(facts)


def build_np_lossless_result(
    *,
    result_paths: Iterable[Path],
    packet_path: Path,
    paper_metadata: dict[str, Any],
) -> LosslessAdapterResult:
    """Preserve every labeled NP result field before normalized projection."""

    paths = sorted((Path(path) for path in result_paths), key=lambda item: str(item))
    bundle = build_np_bundle(
        result_paths=paths,
        packet_path=packet_path,
        paper_metadata=paper_metadata,
    )
    fact_sets: list[ArtifactFactSet] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        artifact = LedgerArtifactRecord(
            paper_id=str(payload["paper_id"]),
            logical_path=_canonical_path(path, _repo_root(path)),
            sha256=_sha(path),
            role="primary_extraction",
            schema_family="np_result",
            validation_status="accepted",
            contributes_facts=True,
            contributes_evidence=True,
            pipeline_name=(
                "compact" if payload["paper_id"] == "NP-001"
                else "isolated_liver_cell"
            ),
            pipeline_version=str(payload.get("contract_version") or "unknown"),
        )
        fact_sets.append(ArtifactFactSet(artifact, _source_field_facts(path)))
    all_facts = tuple(fact for item in fact_sets for fact in item.source_facts)
    unresolved_count = sum(
        len(json.loads(path.read_text(encoding="utf-8")).get("unresolved_items", []))
        for path in paths
    )
    return LosslessAdapterResult(
        bundle=bundle,
        artifact=fact_sets[0].artifact,
        source_facts=all_facts,
        coverage=AdapterCoverage(
            source_fields=len(all_facts),
            unresolved_items=unresolved_count,
            silent_omissions=0,
        ),
        contributing_artifacts=tuple(item.artifact for item in fact_sets),
        artifact_fact_sets=tuple(fact_sets),
    )


__all__ = ["build_np_bundle", "build_np_lossless_result", "write_bundle"]
