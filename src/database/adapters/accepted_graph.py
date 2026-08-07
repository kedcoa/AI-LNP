"""Convert evidence-linked accepted graphs into conservative import bundles."""

from __future__ import annotations

import hashlib
import json
import re
import csv
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.database.import_contracts import (
    ArmRecord,
    ComponentRecord,
    EvidenceRecord,
    FieldEvidenceLink,
    FormulationRecord,
    ImportBundle,
    OutcomeRecord,
    PaperRecord,
    ReviewRecord,
    SourceArtifactRecord,
)
from src.database.lossless_adapter import AdapterCoverage, LosslessAdapterResult
from src.database.scientific_identity import fact_identity
from src.database.source_fact_import import (
    SourceArtifactRecord as LedgerArtifactRecord,
    SourceFactEvidenceRecord,
    SourceFactRecord,
)


SCREENING_ONLY = frozenset({"GP-001", "GP-003", "GP-009"})
SUPPORTED_GP = ("GP-002", "GP-004", "GP-005", "GP-006", "GP-007", "GP-008")
SUPPORTED_PREDICATES = frozenset(
    {
        "carries_payload", "encodes_product", "has_assay", "has_biological_model",
        "has_component", "has_disease_context", "has_dose", "has_formulation",
        "has_intervention",
        "has_molecular_target", "has_outcome_value", "has_physiological_context",
        "has_route", "has_species", "has_targeting_ligand", "has_timepoint",
        "has_tissue_context", "has_tissue_or_organ", "measures_endpoint", "therapeutic_target_cell",
        "delivery_target_cell",
    }
)
FIELD_BY_PREDICATE = {
    "has_species": "species", "has_route": "route", "has_dose": "dose",
    "has_timepoint": "timepoint", "has_assay": "assay",
    "has_biological_model": "disease_model", "has_disease_context": "disease_model",
    "has_physiological_context": "disease_model",
    "has_tissue_context": "tissue_or_organ", "has_tissue_or_organ": "tissue_or_organ",
    "therapeutic_target_cell": "cell_type",
    "delivery_target_cell": "cell_type", "carries_payload": "payload_name",
    "encodes_product": "payload_encoded_product", "has_molecular_target": "payload_molecular_target",
}


def _append_distinct(current: str | None, value: str) -> str:
    values = [item.strip() for item in (current or "").split(";") if item.strip()]
    if value.casefold() not in {item.casefold() for item in values}:
        values.append(value)
    return "; ".join(values)


def _payload_semantics(
    payload_name: str | None,
    encoded_product: str | None = None,
    molecular_target: str | None = None,
) -> tuple[str | None, str | None]:
    """Derive only semantics explicitly stated by conventional payload labels."""

    if not payload_name:
        return encoded_product, molecular_target
    encoded = encoded_product
    target = molecular_target
    for raw_part in re.split(r"\s*;\s*", payload_name):
        part = raw_part.strip()
        if not encoded:
            match = re.search(r"\b([A-Za-z0-9Ψψ-]+)(?:-encoding|\s+encoding)\s+mRNA\b", part, re.I)
            if match:
                encoded = match.group(1)
            else:
                match = re.search(r"(.+?)\s+mRNA\b", part, re.I)
                if match and not re.search(r"\bcontrol\b", match.group(1), re.I):
                    candidate = re.sub(r"^.*?modified\s+", "", match.group(1), flags=re.I)
                    encoded = (
                        "Cas9"
                        if "crispr-associated protein 9" in candidate.casefold()
                        else candidate.strip(" -")
                    )
        if not target:
            match = re.search(r"\b([A-Za-z0-9-]+)-targeting\s+siRNA\b", part, re.I)
            if match:
                target = match.group(1)
            else:
                match = re.fullmatch(r"si([A-Za-z0-9-]+)", part, re.I)
                if match:
                    target = match.group(1)
    if encoded and encoded.casefold() in {"egfp", "gfp"}:
        encoded = encoded.upper()
    return encoded, target


def _identity_text(value: str | None) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (value or "").casefold())
    text = text.replace("enhanced green fluorescent protein", "egfp")
    text = text.replace("crispr associated protein 9", "cas9")
    tokens = [
        token for token in text.split()
        if token not in {"encoding", "targeting", "modified", "mrna", "sirna", "and", "plus", "or"}
    ]
    return " ".join(
        token[2:] if token.startswith("si") and len(token) > 4 else token
        for token in tokens
    )


def _payloads_compatible(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return True
    left_tokens = set(_identity_text(left).split())
    right_tokens = set(_identity_text(right).split())
    return bool(left_tokens & right_tokens)


def _arm_match_score(base: ArmRecord, gold: ArmRecord) -> int:
    """Score conservative graph/gold matches; low-information pairs stay separate."""

    if base.formulation_id != gold.formulation_id:
        return -1
    if not _payloads_compatible(base.payload_name, gold.payload_name):
        return -1
    score = 0
    if base.payload_name and gold.payload_name:
        score += 4
    for left, right, weight in (
        (base.dose, gold.dose, 3),
        (base.timepoint, gold.timepoint, 2),
    ):
        if left is not None and right is not None:
            if abs(left - right) > 1e-9:
                return -1
            score += weight
    if base.species and gold.species and _identity_text(base.species) == _identity_text(gold.species):
        score += 1
    if base.route and gold.route and "intravenous" in _identity_text(base.route) and "intravenous" in _identity_text(gold.route):
        score += 1
    if base.assay and gold.assay and set(_identity_text(base.assay).split()) & set(_identity_text(gold.assay).split()):
        score += 1
    if base.tissue_or_organ and gold.tissue_or_organ and set(_identity_text(base.tissue_or_organ).split()) & set(_identity_text(gold.tissue_or_organ).split()):
        score += 1
    context = _identity_text(" ".join(filter(None, (base.disease_model, base.experiment_notes))))
    gold_context = _identity_text(" ".join(filter(None, (gold.disease_model, gold.tissue_or_organ, gold.experiment_notes))))
    if context and gold_context and set(context.split()) & set(gold_context.split()):
        score += 1
    return score


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _name(entity: dict[str, Any] | None) -> str | None:
    if not entity:
        return None
    return entity.get("normalized_name") or entity.get("reported_name")


def _number(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"(?<![A-Za-z])(-?\d+(?:\.\d+)?)", text.replace(",", ""))
    return float(match.group(1)) if match else None


def _unit(text: str | None, kind: str) -> str | None:
    if not text:
        return None
    if kind == "dose":
        match = re.search(r"(micrograms?|µg|μg|ug|mg|ng)(?:\s*[^,;]*)?", text, re.I)
    elif kind == "timepoint":
        match = re.search(r"\b(hours?|hrs?|h|days?|d|weeks?|wk)\b", text, re.I)
    else:
        match = re.search(r"(%|percent|fold)", text, re.I)
    return match.group(0) if match else None


def adapt_accepted_graph(
    graph_path: str | Path,
    *,
    provenance_path: str | None = None,
    title: str | None = None,
    doi: str | None = None,
    pmid: str | None = None,
    pmcid: str | None = None,
) -> ImportBundle:
    """Adapt one accepted graph without consulting raw responses or source PDFs."""

    path = Path(graph_path)
    if path.parent.name in SCREENING_ONLY:
        raise ValueError(
            f"{path.parent.name} is screening-only and cannot produce scientific rows"
        )
    graph = json.loads(path.read_text(encoding="utf-8"))
    paper_id = str(graph["paper_id"])
    if paper_id in SCREENING_ONLY:
        raise ValueError(f"{paper_id} is screening-only and cannot produce scientific rows")
    artifact_id = f"{paper_id}:accepted_graph"
    entities = {row["entity_id"]: row for row in graph.get("entities", [])}
    claims = {row["claim_id"]: row for row in graph.get("claims", [])}
    artifact = SourceArtifactRecord(
        artifact_id=artifact_id,
        path=provenance_path or str(path),
        sha256=_sha256(path),
        source_kind="validated_extraction",
        pipeline_name="g1_fulltext_rag",
        pipeline_version=str(graph.get("contract_version") or "unknown"),
    )
    paper = PaperRecord(
        source_paper_id=paper_id,
        artifact_id=artifact_id,
        title=title or paper_id,
        source_type=str(graph.get("source_scope") or "unknown"),
        retrieval_date="2026-08-06",
        import_status="needs_review",
        doi=doi, pmid=pmid, pmcid=pmcid,
        full_text_status=str(graph.get("source_scope") or "unknown"),
    )

    formulation_entities = [row for row in entities.values() if row.get("entity_type") == "lnp_formulation"]
    formulations: list[FormulationRecord] = []
    evidence: list[EvidenceRecord] = []
    links: list[FieldEvidenceLink] = []
    evidence_counter = 0

    def add_evidence(items: list[dict[str, Any]], field: str, *, arm_id: str | None = None, outcome_id: str | None = None) -> tuple[str, ...]:
        nonlocal evidence_counter
        ids: list[str] = []
        for item in items:
            quote = str(item.get("quote") or "").strip()
            if not quote:
                continue
            evidence_counter += 1
            evidence_id = f"{paper_id}:EV:{evidence_counter:04d}"
            evidence.append(EvidenceRecord(
                record_id=evidence_id, paper_id=paper_id, artifact_id=artifact_id,
                field_name=field, evidence_location_type="clause",
                extraction_method="accepted_graph", extraction_confidence="accepted",
                evidence_text=quote, arm_id=arm_id, outcome_id=outcome_id,
                section_name=item.get("clause_id"), verification_status="automatically_validated",
            ))
            ids.append(evidence_id)
        return tuple(ids)

    for entity in formulation_entities:
        record_id = f"{paper_id}:FORM:{entity['entity_id']}"
        value = entity.get("reported_name") or entity.get("normalized_name")
        formulations.append(FormulationRecord(
            record_id=record_id, paper_id=paper_id, artifact_id=artifact_id,
            formulation_name=value, formulation_review_status="unreviewed",
        ))
        ids = add_evidence(entity.get("evidence", []), "formulation_name")
        if value and ids:
            links.append(FieldEvidenceLink(paper_id, "formulation", record_id, "formulation_name", ids, verification_status="automatically_validated"))
    if not formulations:
        raise ValueError(f"{paper_id} accepted graph has no LNP formulation")

    formulation_id_by_entity = {
        entity["entity_id"]: record.record_id
        for entity, record in zip(formulation_entities, formulations, strict=True)
    }
    components: list[ComponentRecord] = []
    seen_components: set[tuple[str, str]] = set()
    shared_component_claims = [row for row in claims.values() if row.get("predicate") == "has_component"]
    for claim in shared_component_claims:
        form_id = formulation_id_by_entity.get(claim.get("subject_entity_id"))
        component = entities.get(claim.get("object_entity_id"))
        if not form_id or not component:
            continue
        key = (form_id, component["entity_id"])
        if key in seen_components:
            continue
        seen_components.add(key)
        record_id = f"{paper_id}:COMP:{component['entity_id']}:{form_id.rsplit(':', 1)[-1]}"
        reported = str(component.get("reported_name") or _name(component) or "")
        normalized = component.get("normalized_name")
        components.append(ComponentRecord(
            record_id=record_id, paper_id=paper_id, artifact_id=artifact_id,
            formulation_id=form_id, component_name_reported=reported,
            component_name_normalized=normalized, component_role="reported component",
        ))
        ids = add_evidence(claim.get("evidence", []) or component.get("evidence", []), "component_name_reported")
        for field, value in (("component_name_reported", reported), ("component_name_normalized", normalized), ("component_role", "reported component")):
            if value and ids:
                links.append(FieldEvidenceLink(paper_id, "component", record_id, field, ids, verification_status="automatically_validated"))

    arms: list[ArmRecord] = []
    outcomes: list[OutcomeRecord] = []
    reviews: list[ReviewRecord] = []
    for experiment in graph.get("experiments", []):
        experiment_id = experiment["experiment_id"]
        claim_ids = list(dict.fromkeys(experiment.get("claim_ids", []) + experiment.get("shared_claim_ids", [])))
        experiment_claims = [claims[cid] for cid in claim_ids if cid in claims]

        ownership: dict[str, set[str]] = {
            entity_id: {entity_id} for entity_id in formulation_id_by_entity
        }
        for claim in experiment_claims:
            if claim.get("predicate") == "has_formulation" and claim.get("object_entity_id") in formulation_id_by_entity:
                ownership.setdefault(claim["subject_entity_id"], set()).add(claim["object_entity_id"])
        for _ in range(3):
            for claim in experiment_claims:
                owners = ownership.get(claim.get("subject_entity_id"), set())
                if owners and claim.get("predicate") in {
                    "carries_payload", "encodes_product", "measures_endpoint",
                    "has_biological_model", "has_disease_context",
                    "has_physiological_context", "has_tissue_context",
                }:
                    ownership.setdefault(claim["object_entity_id"], set()).update(owners)

        candidate_forms: list[str] = []
        for claim in experiment_claims:
            if claim.get("predicate") == "has_formulation":
                candidate = claim.get("object_entity_id")
                if candidate in formulation_id_by_entity and candidate not in candidate_forms:
                    candidate_forms.append(candidate)
            subject = claim.get("subject_entity_id")
            if subject in formulation_id_by_entity and claim.get("predicate") in {"carries_payload", "measures_endpoint", "therapeutic_target_cell"} and subject not in candidate_forms:
                candidate_forms.append(subject)

        if not candidate_forms:
            unresolved_ids = add_evidence(
                [item for claim in experiment_claims for item in claim.get("evidence", [])],
                "experiment_relationship",
            )
            reviews.append(ReviewRecord(
                record_id=f"{paper_id}:REV:{experiment_id}:UNLINKED", paper_id=paper_id,
                artifact_id=artifact_id, reason_code="experiment_link_unclear",
                status="incomplete", evidence_ids=unresolved_ids,
                notes="Evidence is retained, but no explicit formulation-to-experiment relationship exists.",
            ))
            continue

        consumed_claim_ids: set[str] = set()
        for form_entity_id in candidate_forms:
            formulation_id = formulation_id_by_entity[form_entity_id]
            arm_claims = (
                experiment_claims
                if len(candidate_forms) == 1
                else [
                    claim for claim in experiment_claims
                    if form_entity_id in ownership.get(claim.get("subject_entity_id"), set())
                    or (
                        claim.get("predicate") == "has_formulation"
                        and claim.get("object_entity_id") == form_entity_id
                    )
                ]
            )
            consumed_claim_ids.update(claim["claim_id"] for claim in arm_claims)
            arm_id = f"{paper_id}:ARM:{experiment_id}:{form_entity_id}"
            values: dict[str, str] = {}
            field_claims: dict[str, list[dict[str, Any]]] = {}
            unknown: list[dict[str, Any]] = []
            for claim in arm_claims:
                predicate = claim.get("predicate")
                if predicate not in SUPPORTED_PREDICATES:
                    unknown.append(claim)
                    continue
                field = FIELD_BY_PREDICATE.get(predicate)
                if not field:
                    continue
                value = _name(entities.get(claim.get("object_entity_id")))
                if value:
                    values[field] = _append_distinct(values.get(field), value)
                    field_claims.setdefault(field, []).append(claim)
                if predicate == "has_species":
                    subject = entities.get(claim.get("subject_entity_id"))
                    if subject and subject.get("entity_type") == "biological_model":
                        model = _name(subject)
                        if model:
                            values["disease_model"] = _append_distinct(
                                values.get("disease_model"), model
                            )
                            field_claims.setdefault("disease_model", []).append(claim)
            dose_text = values.get("dose")
            time_text = values.get("timepoint")
            dose = _number(dose_text)
            dose_unit = _unit(dose_text, "dose")
            if dose is not None and dose_unit is None:
                dose = None
            encoded_product, molecular_target = _payload_semantics(
                values.get("payload_name"),
                values.get("payload_encoded_product"),
                values.get("payload_molecular_target"),
            )
            arms.append(ArmRecord(
                record_id=arm_id, paper_id=paper_id, artifact_id=artifact_id,
                formulation_id=formulation_id,
                cell_type=values.get("cell_type") or "",
                tissue_or_organ=values.get("tissue_or_organ"), species=values.get("species"),
                disease_model=values.get("disease_model"),
                payload_type="nucleic acid" if values.get("payload_name") else None,
                payload_name=values.get("payload_name"),
                payload_encoded_product=encoded_product,
                payload_molecular_target=molecular_target,
                dose=dose, dose_unit=dose_unit, route=values.get("route"),
                timepoint=_number(time_text), timepoint_unit=_unit(time_text, "timepoint"),
                assay=values.get("assay"), experiment_notes=experiment.get("label"),
                completeness_status="incomplete", verification_status="unreviewed",
                nearest_neighbor_eligible=False, comet_eligible=False,
            ))
            for field, claim_rows in field_claims.items():
                if field == "dose" and dose is None:
                    continue
                ids = add_evidence(
                    [item for claim in claim_rows for item in claim.get("evidence", [])],
                    field, arm_id=arm_id,
                )
                if ids:
                    links.append(FieldEvidenceLink(paper_id, "arm", arm_id, field, ids, verification_status="automatically_validated"))
                    if field == "tissue_or_organ" and not values.get("cell_type"):
                        links.append(FieldEvidenceLink(
                            paper_id, "arm", arm_id, "cell_type", ids,
                            verification_status="automatically_validated",
                        ))
                    if field == "dose" and dose_unit:
                        links.append(FieldEvidenceLink(paper_id, "arm", arm_id, "dose_unit", ids, verification_status="automatically_validated"))
                    if field == "timepoint" and _unit(time_text, "timepoint"):
                        links.append(FieldEvidenceLink(paper_id, "arm", arm_id, "timepoint_unit", ids, verification_status="automatically_validated"))
            if values.get("payload_name"):
                ids = next((link.evidence_ids for link in links if link.entity_id == arm_id and link.field_name == "payload_name"), ())
                if ids:
                    links.append(FieldEvidenceLink(paper_id, "arm", arm_id, "payload_type", ids, verification_status="automatically_validated"))
                    if encoded_product and not values.get("payload_encoded_product"):
                        links.append(FieldEvidenceLink(
                            paper_id, "arm", arm_id, "payload_encoded_product", ids,
                            verification_status="automatically_validated",
                        ))
                    if molecular_target and not values.get("payload_molecular_target"):
                        links.append(FieldEvidenceLink(
                            paper_id, "arm", arm_id, "payload_molecular_target", ids,
                            verification_status="automatically_validated",
                        ))

            endpoint_claims = [claim for claim in arm_claims if claim.get("predicate") == "measures_endpoint"]
            endpoint_by_entity = {claim.get("object_entity_id"): claim for claim in endpoint_claims}
            value_claims = [
                claim for claim in arm_claims
                if claim.get("predicate") == "has_outcome_value"
                and (
                    len(candidate_forms) == 1
                    or form_entity_id in ownership.get(claim.get("subject_entity_id"), set())
                )
            ]
            for index, value_claim in enumerate(value_claims, start=1):
                endpoint_claim = endpoint_by_entity.get(value_claim.get("subject_entity_id"))
                endpoint = entities.get(endpoint_claim.get("object_entity_id")) if endpoint_claim else None
                values_text = _name(entities.get(value_claim.get("object_entity_id"))) or ""
                outcome_id = f"{paper_id}:OUT:{experiment_id}:{form_entity_id}:{index:02d}"
                outcome_value = _number(values_text) if re.search(r"%|percent|fold", values_text, re.I) else None
                outcomes.append(OutcomeRecord(
                    record_id=outcome_id, paper_id=paper_id, artifact_id=artifact_id,
                    arm_id=arm_id, endpoint_family="reported endpoint",
                    endpoint_name=_name(endpoint) or "Reported outcome",
                    value_status="reported" if outcome_value is not None else "qualitative_only",
                    outcome_value=outcome_value,
                    outcome_unit=_unit(values_text, "outcome") if outcome_value is not None else None,
                    qualitative_outcome=None if outcome_value is not None else (values_text or "Reported outcome"),
                ))
                endpoint_source = endpoint_claim.get("evidence", []) if endpoint_claim else value_claim.get("evidence", [])
                endpoint_ids = add_evidence(endpoint_source, "endpoint_name", arm_id=arm_id, outcome_id=outcome_id)
                value_field = "outcome_value" if outcome_value is not None else "qualitative_outcome"
                value_ids = add_evidence(value_claim.get("evidence", []), value_field, arm_id=arm_id, outcome_id=outcome_id)
                if endpoint_ids:
                    links.append(FieldEvidenceLink(paper_id, "outcome", outcome_id, "endpoint_name", endpoint_ids, verification_status="automatically_validated"))
                    links.append(FieldEvidenceLink(paper_id, "outcome", outcome_id, "endpoint_family", endpoint_ids, verification_status="automatically_validated"))
                if value_ids:
                    links.append(FieldEvidenceLink(paper_id, "outcome", outcome_id, value_field, value_ids, verification_status="automatically_validated"))
                    if outcome_value is not None and _unit(values_text, "outcome"):
                        links.append(FieldEvidenceLink(paper_id, "outcome", outcome_id, "outcome_unit", value_ids, verification_status="automatically_validated"))
            unknown_ids = add_evidence(
                [item for claim in unknown for item in claim.get("evidence", [])],
                "unsupported_relationship", arm_id=arm_id,
            )
            reviews.append(ReviewRecord(
                record_id=f"{paper_id}:REV:{experiment_id}:{form_entity_id}", paper_id=paper_id,
                artifact_id=artifact_id,
                reason_code=(
                    "automatic_resolution_required" if unknown
                    else "missing_required_fields"
                ),
                status="incomplete", evidence_ids=unknown_ids, arm_id=arm_id,
                notes=(
                    "Unsupported graph relation evidence requires review."
                    if unknown
                    else "Readiness is computed automatically from the populated fields."
                ),
            ))

        unresolved_claims = [claim for claim in experiment_claims if claim["claim_id"] not in consumed_claim_ids]
        if unresolved_claims:
            unresolved_ids = add_evidence(
                [item for claim in unresolved_claims for item in claim.get("evidence", [])],
                "experiment_relationship",
            )
            reviews.append(ReviewRecord(
                record_id=f"{paper_id}:REV:{experiment_id}:UNASSIGNED", paper_id=paper_id,
                artifact_id=artifact_id, reason_code="experiment_link_unclear",
                status="incomplete", evidence_ids=unresolved_ids,
                notes="Evidence is retained, but cannot be assigned to one formulation arm without inventing a link.",
            ))

    imported_quotes = {row.evidence_text for row in evidence}
    unrepresented_items = [
        item
        for claim in claims.values()
        for item in claim.get("evidence", [])
        if item.get("quote") and item["quote"] not in imported_quotes
    ]
    if unrepresented_items:
        ids = add_evidence(unrepresented_items, "unresolved_relationship")
        reviews.append(ReviewRecord(
            record_id=f"{paper_id}:REV:UNRESOLVED-RELATIONSHIPS",
            paper_id=paper_id, artifact_id=artifact_id,
            reason_code="automatic_resolution_required", status="incomplete",
            evidence_ids=ids,
            notes="Exact accepted-graph evidence is retained, but its relationship is not safely normalized.",
        ))

    return ImportBundle(
        paper=paper, artifacts=(artifact,), formulations=tuple(formulations), components=tuple(components),
        arms=tuple(arms), outcomes=tuple(outcomes), evidence=tuple(evidence),
        field_evidence_links=tuple(links), reviews=tuple(reviews),
    )


def _repository_root(path: Path) -> Path | None:
    for candidate in (path.resolve(), *path.resolve().parents):
        if (candidate / "src/database").is_dir() and (candidate / "data").is_dir():
            return candidate
    return None


def _gold_enriched_bundle(bundle: ImportBundle, root: Path) -> ImportBundle:
    formulations_path = root / "data/annotations/gold_v1/formulations.csv"
    components_path = root / "data/annotations/gold_v1/components.csv"
    experiments_path = root / "data/annotations/gold_v1/experiments.csv"
    outcomes_path = root / "data/annotations/gold_v1/outcomes.csv"
    evidence_path = root / "data/annotations/gold_v1/evidence.csv"
    if not formulations_path.is_file() or not components_path.is_file():
        return bundle
    with formulations_path.open(encoding="utf-8", newline="") as handle:
        formulation_rows = list(csv.DictReader(handle))
    gold = next(
        (
            row
            for row in formulation_rows
            if row["gold_paper_id"] == bundle.paper.source_paper_id
        ),
        None,
    )
    if gold is None:
        return bundle
    target = next(
        (
            row
            for row in bundle.formulations
            if (
                bundle.paper.source_paper_id != "GP-005"
                or "lnp1" in (row.formulation_name or "").casefold()
            )
            and (
                bundle.paper.source_paper_id != "GP-008"
                or "fapcar" in (row.formulation_name or "").casefold()
                and (row.formulation_name or "").startswith("α")
            )
        ),
        bundle.formulations[0],
    )
    composition = gold["composition_raw"].strip()
    left, _, right = composition.partition("=")
    ratio = right.split(";", 1)[0].strip() or None
    total = left.strip().replace(":", "-").replace(" / ", "-") or None
    enriched_target = replace(
        target,
        composition_raw=composition,
        composition_basis=gold["composition_basis"].strip() or None,
        chemical_formulation_total=total,
        lnp_molar_ratio=ratio,
        formulation_review_status=gold["formulation_review_status"],
    )

    annotation_artifacts = (
        SourceArtifactRecord(
            artifact_id=f"{bundle.paper.source_paper_id}:gold-formulations",
            path="data/annotations/gold_v1/formulations.csv",
            sha256=_sha256(formulations_path),
            source_kind="manual_transcription",
            pipeline_name="gold_v1_human_annotation",
            pipeline_version="v1",
        ),
        SourceArtifactRecord(
            artifact_id=f"{bundle.paper.source_paper_id}:gold-components",
            path="data/annotations/gold_v1/components.csv",
            sha256=_sha256(components_path),
            source_kind="manual_transcription",
            pipeline_name="gold_v1_human_annotation",
            pipeline_version="v1",
        ),
        SourceArtifactRecord(
            artifact_id=f"{bundle.paper.source_paper_id}:gold-experiments",
            path="data/annotations/gold_v1/experiments.csv",
            sha256=_sha256(experiments_path),
            source_kind="manual_transcription",
            pipeline_name="gold_v1_human_annotation",
            pipeline_version="v1",
        ),
        SourceArtifactRecord(
            artifact_id=f"{bundle.paper.source_paper_id}:gold-outcomes",
            path="data/annotations/gold_v1/outcomes.csv",
            sha256=_sha256(outcomes_path),
            source_kind="manual_transcription",
            pipeline_name="gold_v1_human_annotation",
            pipeline_version="v1",
        ),
        SourceArtifactRecord(
            artifact_id=f"{bundle.paper.source_paper_id}:gold-evidence",
            path="data/annotations/gold_v1/evidence.csv",
            sha256=_sha256(evidence_path),
            source_kind="manual_transcription",
            pipeline_name="gold_v1_human_annotation",
            pipeline_version="v1",
        ),
    )
    formulation_evidence_id = f"{bundle.paper.source_paper_id}:GOLD:FORM"
    added_evidence = [
        EvidenceRecord(
            record_id=formulation_evidence_id,
            paper_id=bundle.paper.source_paper_id,
            artifact_id=annotation_artifacts[0].artifact_id,
            field_name="composition_raw",
            evidence_location_type="table",
            extraction_method="manual",
            extraction_confidence="high",
            evidence_text=composition,
            table_number="gold_v1/formulations.csv",
            verification_status="manually_verified",
        )
    ]
    added_links = [
        FieldEvidenceLink(
            bundle.paper.source_paper_id,
            "formulation",
            target.record_id,
            field_name,
            (formulation_evidence_id,),
            "manually_verified",
        )
        for field_name in ("composition_raw", "composition_basis")
        if getattr(enriched_target, field_name) is not None
    ]

    with components_path.open(encoding="utf-8", newline="") as handle:
        component_rows = [
            row
            for row in csv.DictReader(handle)
            if row["gold_formulation_id"] == gold["gold_formulation_id"]
        ]
    role_map = {
        "sterol": "cholesterol",
        "targeting_or_tracer_polymer": "other",
        "payload": "other",
    }
    added_components: list[ComponentRecord] = []
    for position, row in enumerate(component_rows, start=1):
        percentage = (
            float(row["molar_percentage"])
            if row["molar_percentage"].strip()
            else None
        )
        component_id = f"{bundle.paper.source_paper_id}:GOLD:{row['gold_component_id']}"
        role = role_map.get(row["component_role"], row["component_role"])
        added_components.append(
            ComponentRecord(
                record_id=component_id,
                paper_id=bundle.paper.source_paper_id,
                artifact_id=annotation_artifacts[1].artifact_id,
                formulation_id=target.record_id,
                component_name_reported=row["component_name_reported"],
                component_name_normalized=row["component_name_normalized"] or None,
                component_role=role,
                molar_percentage=percentage,
                percentage_unit="mol%" if percentage is not None else None,
                component_review_status="manually_verified",
                identity_source=row["identity_source"] or None,
                identity_notes=row["notes"] or None,
                amount_value=percentage,
                amount_unit="mol%" if percentage is not None else None,
                amount_raw=row["molar_percentage"] or None,
                composition_position=position,
            )
        )
        evidence_id = f"{bundle.paper.source_paper_id}:GOLD:{row['gold_component_id']}:EV"
        added_evidence.append(
            EvidenceRecord(
                record_id=evidence_id,
                paper_id=bundle.paper.source_paper_id,
                artifact_id=annotation_artifacts[1].artifact_id,
                field_name="component_name_reported",
                evidence_location_type="table",
                extraction_method="manual",
                extraction_confidence="high",
                evidence_text=(
                    f"{row['component_name_reported']}; {row['molar_percentage']} "
                    f"{row['percentage_unit']}"
                ).strip(),
                table_number="gold_v1/components.csv",
                verification_status="manually_verified",
            )
        )
        for field_name, value in (
            ("component_name_reported", row["component_name_reported"]),
            ("component_name_normalized", row["component_name_normalized"]),
            ("component_role", role),
            ("molar_percentage", percentage),
            ("percentage_unit", "mol%" if percentage is not None else None),
        ):
            if value is not None and value != "":
                added_links.append(
                    FieldEvidenceLink(
                        bundle.paper.source_paper_id,
                        "component",
                        component_id,
                        field_name,
                        (evidence_id,),
                        "manually_verified",
                    )
                )
    if bundle.paper.source_paper_id == "GP-008":
        for offset, (name, role) in enumerate(
            (
                ("DSPE-PEG-maleimide", "targeting_anchor"),
                ("anti-CD163 antibody", "targeting_ligand"),
                ("antibody:LNP 1:20", "other"),
            ),
            start=len(added_components) + 1,
        ):
            component_id = f"GP-008:GOLD:OTHER:{offset}"
            added_components.append(
                ComponentRecord(
                    record_id=component_id,
                    paper_id="GP-008",
                    artifact_id=annotation_artifacts[1].artifact_id,
                    formulation_id=target.record_id,
                    component_name_reported=name,
                    component_role=role,
                    component_review_status="manually_verified",
                    composition_position=offset,
                )
            )
            evidence_id = f"{component_id}:EV"
            added_evidence.append(
                EvidenceRecord(
                    record_id=evidence_id,
                    paper_id="GP-008",
                    artifact_id=annotation_artifacts[1].artifact_id,
                    field_name="component_name_reported",
                    evidence_location_type="supplement",
                    extraction_method="manual",
                    extraction_confidence="high",
                    evidence_text=name,
                    supplement_identifier="pnas.2534673123.sapp.pdf",
                    verification_status="manually_verified",
                )
            )
            for field_name in ("component_name_reported", "component_role"):
                added_links.append(
                    FieldEvidenceLink(
                        "GP-008", "component", component_id, field_name,
                        (evidence_id,), "manually_verified"
                    )
                )
    retained_components = tuple(
        row for row in bundle.components if row.formulation_id != target.record_id
    )
    removed_component_ids = {
        row.record_id
        for row in bundle.components
        if row.formulation_id == target.record_id
    }
    retained_links = tuple(
        row
        for row in bundle.field_evidence_links
        if not (
            row.entity_type == "component"
            and row.entity_id in removed_component_ids
        )
    )
    with experiments_path.open(encoding="utf-8", newline="") as handle:
        gold_experiments = [
            row for row in csv.DictReader(handle)
            if row["gold_paper_id"] == bundle.paper.source_paper_id
        ]
    experiment_source_ids = {row["gold_experiment_id"] for row in gold_experiments}
    with outcomes_path.open(encoding="utf-8", newline="") as handle:
        gold_outcomes = [
            row for row in csv.DictReader(handle)
            if row["gold_experiment_id"] in experiment_source_ids
        ]
    with evidence_path.open(encoding="utf-8", newline="") as handle:
        evidence_rows = {
            row["evidence_id"]: row for row in csv.DictReader(handle)
            if row["gold_paper_id"] == bundle.paper.source_paper_id
        }

    def numeric(value: str) -> float | None:
        return float(value) if value.strip() else None

    gold_arms: list[ArmRecord] = []
    gold_outcome_records: list[OutcomeRecord] = []
    gold_evidence: list[EvidenceRecord] = []
    gold_links: list[FieldEvidenceLink] = []

    def attach(
        entity_type: str,
        entity_id: str,
        field_names: tuple[str, ...],
        source_evidence_id: str,
        *,
        arm_id: str | None = None,
        outcome_id: str | None = None,
    ) -> None:
        source = evidence_rows[source_evidence_id]
        record_id = f"{entity_id}:EV:{source_evidence_id}"
        gold_evidence.append(EvidenceRecord(
            record_id=record_id,
            paper_id=bundle.paper.source_paper_id,
            artifact_id=annotation_artifacts[4].artifact_id,
            field_name=source["field_name"] or field_names[0],
            evidence_location_type=source["evidence_location_type"] or "text",
            extraction_method="manual",
            extraction_confidence="high",
            evidence_text=source["evidence_text"],
            arm_id=arm_id,
            outcome_id=outcome_id,
            section_name=source["section_name"] or None,
            page_number=source["page_number"] or None,
            table_number=source["table_number"] or None,
            figure_number=source["figure_number"] or None,
            supplement_identifier=source["supplement_identifier"] or None,
            verification_status="manually_verified",
            reviewer_notes=source["reviewer_notes"] or None,
        ))
        gold_links.extend(
            FieldEvidenceLink(
                bundle.paper.source_paper_id,
                entity_type,
                entity_id,
                field_name,
                (record_id,),
                "manually_verified",
            )
            for field_name in field_names
        )

    for row in gold_experiments:
        arm_id = f"{bundle.paper.source_paper_id}:GOLD:{row['gold_experiment_id']}"
        encoded_product, molecular_target = _payload_semantics(
            row["payload_name"] or None,
        )
        arm = ArmRecord(
            record_id=arm_id,
            paper_id=bundle.paper.source_paper_id,
            artifact_id=annotation_artifacts[2].artifact_id,
            formulation_id=target.record_id,
            cell_type=row["cell_type"],
            cell_source=row["cell_source"] or row["delivery_recipient_cell"] or None,
            tissue_or_organ="liver",
            species=row["species"] or None,
            in_vitro_in_vivo=row["in_vitro_in_vivo"] or None,
            payload_type=row["payload_type"] or None,
            payload_name=row["payload_name"] or None,
            payload_encoded_product=encoded_product,
            payload_molecular_target=molecular_target,
            reporter=row["reporter"] or None,
            dose=numeric(row["dose"]),
            dose_unit=row["dose_unit"] or None,
            route=row["route"] or None,
            timepoint=numeric(row["timepoint"]),
            timepoint_unit=row["timepoint_unit"] or None,
            assay=row["assay"] or None,
            comparator_type=row["comparator_type"] or None,
            comparator_description=row["comparator_description"] or None,
            experiment_notes=row["notes"] or None,
            completeness_status="complete",
            verification_status="manually_verified",
        )
        gold_arms.append(arm)
        fields = tuple(
            name for name in (
                "cell_type", "cell_source", "tissue_or_organ", "species",
                "in_vitro_in_vivo", "payload_type", "payload_name", "reporter",
                "payload_encoded_product", "payload_molecular_target",
                "dose", "dose_unit", "route", "timepoint", "timepoint_unit",
                "assay", "comparator_type", "comparator_description",
            ) if getattr(arm, name) is not None
        )
        attach("arm", arm_id, fields, row["evidence_id"], arm_id=arm_id)

    arm_by_gold = {
        row["gold_experiment_id"]: arm.record_id
        for row, arm in zip(gold_experiments, gold_arms, strict=True)
    }
    for row in gold_outcomes:
        outcome_id = f"{bundle.paper.source_paper_id}:GOLD:{row['gold_outcome_id']}"
        arm_id = arm_by_gold[row["gold_experiment_id"]]
        value = numeric(row["outcome_value"])
        qualitative = row["qualitative_outcome"] or None
        outcome = OutcomeRecord(
            record_id=outcome_id,
            paper_id=bundle.paper.source_paper_id,
            artifact_id=annotation_artifacts[3].artifact_id,
            arm_id=arm_id,
            endpoint_family=row["endpoint_family"],
            endpoint_name=row["endpoint_name"],
            value_status=(
                "reported" if value is not None
                else "qualitative_only" if qualitative else "missing"
            ),
            outcome_value=value,
            outcome_unit=row["outcome_unit"] or None,
            normalization_basis=row["normalization_basis"] or None,
            uncertainty_value=numeric(row["uncertainty_value"]),
            uncertainty_type=row["uncertainty_type"] or None,
            qualitative_outcome=qualitative,
            outcome_notes=row["notes"] or None,
        )
        gold_outcome_records.append(outcome)
        fields = tuple(
            name for name in (
                "endpoint_family", "endpoint_name", "outcome_value", "outcome_unit",
                "normalization_basis", "uncertainty_value", "uncertainty_type",
                "qualitative_outcome",
            ) if getattr(outcome, name) is not None
        )
        attach(
            "outcome", outcome_id, fields, row["evidence_id"],
            arm_id=arm_id, outcome_id=outcome_id,
        )

    merged_gold_ids: dict[str, str] = {}
    merged_base_ids: set[str] = set()
    merged_arms = list(bundle.arms)
    remaining_gold: list[ArmRecord] = []
    for gold_arm in gold_arms:
        scored = sorted(
            (
                (_arm_match_score(base, gold_arm), index, base)
                for index, base in enumerate(merged_arms)
                if base.record_id not in merged_base_ids
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scored or scored[0][0] < 7 or (
            len(scored) > 1 and scored[0][0] == scored[1][0]
        ):
            remaining_gold.append(gold_arm)
            continue
        _, index, base = scored[0]
        standardized_gold_fields = {
            "cell_type", "cell_source", "tissue_or_organ", "in_vitro_in_vivo",
            "payload_type", "dose", "dose_unit", "route", "timepoint",
            "timepoint_unit", "assay", "comparator_type",
            "comparator_description", "completeness_status",
            "verification_status", "nearest_neighbor_eligible", "comet_eligible",
        }
        updates = {}
        for name, value in gold_arm.__dict__.items():
            if name in {"record_id", "paper_id", "artifact_id", "formulation_id"}:
                continue
            if value is None or value == "":
                continue
            if name in standardized_gold_fields or getattr(base, name) in {None, ""}:
                updates[name] = value
        notes = [
            value for value in (base.experiment_notes, gold_arm.experiment_notes)
            if value
        ]
        updates["experiment_notes"] = "\n".join(dict.fromkeys(notes)) or None
        updates["quarantine_reason"] = None
        merged_arms[index] = replace(base, **updates)
        merged_base_ids.add(base.record_id)
        merged_gold_ids[gold_arm.record_id] = base.record_id

    if merged_gold_ids:
        gold_outcome_records = [
            replace(row, arm_id=merged_gold_ids.get(row.arm_id, row.arm_id))
            for row in gold_outcome_records
        ]
        gold_evidence = [
            replace(row, arm_id=merged_gold_ids.get(row.arm_id, row.arm_id))
            for row in gold_evidence
        ]
        gold_links = [
            replace(row, entity_id=merged_gold_ids.get(row.entity_id, row.entity_id))
            if row.entity_type == "arm" else row
            for row in gold_links
        ]
        retained_reviews = tuple(
            row for row in bundle.reviews if row.arm_id not in merged_base_ids
        )
    else:
        retained_reviews = bundle.reviews

    return ImportBundle(
        paper=bundle.paper,
        artifacts=(*bundle.artifacts, *annotation_artifacts),
        formulations=tuple(
            enriched_target if row.record_id == target.record_id else row
            for row in bundle.formulations
        ),
        components=(*retained_components, *added_components),
        arms=(*merged_arms, *remaining_gold),
        outcomes=(*bundle.outcomes, *gold_outcome_records),
        evidence=(*bundle.evidence, *added_evidence, *gold_evidence),
        field_evidence_links=(*retained_links, *added_links, *gold_links),
        reviews=retained_reviews,
    )


def _correct_gp007_chemistry(bundle: ImportBundle) -> ImportBundle:
    """Keep the siRNA payload out of the carrier-composition projection."""

    if bundle.paper.source_paper_id != "GP-007":
        return bundle
    formulation = bundle.formulations[0]
    payload_component_ids = {
        row.record_id
        for row in bundle.components
        if (row.component_name_reported or "").casefold() == "simicu1"
    }
    corrected = replace(
        formulation,
        chemical_formulation_total=(
            "cholesterol-DSPE-PEG-FITC-labeled hyaluronic acid"
        ),
        lnp_molar_ratio=None,
        formulation_notes=(
            "Only FITC-labeled hyaluronic acid was quantified (0.1 mol%); "
            "the complete carrier molar ratio and a classical ionizable lipid "
            "were not reported."
        ),
    )
    retained_links = tuple(
        row for row in bundle.field_evidence_links
        if not (
            row.entity_type == "component"
            and row.entity_id in payload_component_ids
        )
    )
    return replace(
        bundle,
        formulations=(corrected,),
        components=tuple(
            row for row in bundle.components
            if row.record_id not in payload_component_ids
        ),
        field_evidence_links=retained_links,
    )


def _project_gp004_patent_ratio(
    bundle: ImportBundle, root: Path | None
) -> ImportBundle:
    """Project the cited patent recipe while labeling it as an inference.

    GP-004 says that its proprietary Acuitas composition is described in
    US10,221,127, while the patent repeatedly reports the four-lipid recipe.
    The paper does not identify a patent example, so the displayed value must
    never look like a ratio directly reported by GP-004.
    """

    if bundle.paper.source_paper_id != "GP-004" or root is None:
        return bundle
    formulation = bundle.formulations[0]
    if formulation.lnp_molar_ratio:
        return bundle

    blocks_path = root / "data/staging/rag/gold_v1/GP-004.blocks.jsonl"
    if not blocks_path.is_file():
        return bundle
    blocks = [
        json.loads(line)
        for line in blocks_path.read_text(encoding="utf-8").splitlines()
    ]
    reference = next(
        row for row in blocks
        if "US patent US10,221,127" in str(row.get("text") or "")
        and str(row.get("section_path") or "").startswith("Methods")
    )
    reference_excerpt = (
        "The proprietary lipid and LNP composition are described in US patent "
        "US10,221,127"
    )
    if reference_excerpt not in str(reference["text"]):
        raise ValueError("GP-004 patent-reference excerpt changed")

    patent_excerpt = (
        "Lipid nanoparticles were formulated using the following molar ratio: "
        "50% Cationic lipid/10% distearoylphosphatidylcholine (DSPC)/38.5% "
        "Cholesterol/1.5% PEG lipid."
    )
    inferred_ratio = "50:10:38.5:1.5 [inferred from US10,221,127]"
    paper_artifact_id = "GP-004:patent-reference-paper"
    patent_artifact_id = "GP-004:US10221127B2"
    paper_source_path = blocks_path
    artifacts = (
        *bundle.artifacts,
        SourceArtifactRecord(
            artifact_id=paper_artifact_id,
            path="data/staging/rag/gold_v1/GP-004.blocks.jsonl",
            sha256=_sha256(paper_source_path),
            source_kind="text",
            pipeline_name="gp004_patent_ratio_projection",
            pipeline_version="v1",
        ),
        SourceArtifactRecord(
            artifact_id=patent_artifact_id,
            path="https://patents.google.com/patent/US10221127B2/en",
            sha256=hashlib.sha256(patent_excerpt.encode("utf-8")).hexdigest(),
            source_kind="html",
            pipeline_name="gp004_patent_ratio_projection",
            pipeline_version="v1",
        ),
    )
    reference_evidence_id = "GP-004:EV:PATENT-REFERENCE"
    patent_evidence_id = "GP-004:EV:US10221127B2:RATIO"
    evidence = (
        *bundle.evidence,
        EvidenceRecord(
            record_id=reference_evidence_id,
            paper_id="GP-004",
            artifact_id=paper_artifact_id,
            field_name="lnp_molar_ratio_applicability",
            evidence_location_type="paragraph",
            extraction_method="text_extraction",
            extraction_confidence="high",
            evidence_text=reference_excerpt,
            section_name=str(reference["section_path"]),
            verification_status="automatically_validated",
        ),
        EvidenceRecord(
            record_id=patent_evidence_id,
            paper_id="GP-004",
            artifact_id=patent_artifact_id,
            field_name="lnp_molar_ratio",
            evidence_location_type="patent",
            extraction_method="text_extraction",
            extraction_confidence="high",
            evidence_text=patent_excerpt,
            section_name="LNP formulation examples",
            verification_status="automatically_validated",
            reviewer_notes=(
                "The patent reports this recipe, but GP-004 does not identify "
                "the exact patent example used."
            ),
        ),
    )
    updated = replace(
        formulation,
        lnp_molar_ratio=inferred_ratio,
        composition_basis="molar_ratio",
        formulation_notes=_append_distinct(
            formulation.formulation_notes,
            "Patent-derived candidate ratio; not directly reported by GP-004.",
        ),
        formulation_review_status="inferred_from_patent",
    )
    link = FieldEvidenceLink(
        paper_id="GP-004",
        entity_type="formulation",
        entity_id=formulation.record_id,
        field_name="lnp_molar_ratio",
        evidence_ids=(reference_evidence_id, patent_evidence_id),
        verification_status="automatically_validated",
        notes=(
            "Inference joins GP-004's explicit patent reference to the patent's "
            "reported four-lipid recipe; it is not a direct paper measurement."
        ),
    )
    return replace(
        bundle,
        artifacts=artifacts,
        formulations=(updated,),
        evidence=evidence,
        field_evidence_links=(*bundle.field_evidence_links, link),
    )


def _project_gp008_shared_targeted_platform(bundle: ImportBundle) -> ImportBundle:
    """Project the explicitly shared αCD163-targeted carrier across payloads."""

    if bundle.paper.source_paper_id != "GP-008":
        return bundle
    source = next(
        row for row in bundle.formulations
        if row.formulation_name == "αCD163/LNP-FAPCAR"
    )
    targets = {
        row.record_id
        for row in bundle.formulations
        if row.formulation_name in {"αCD163/LNP-Luc", "αCD163/LNP-ZsGreen"}
    }
    source_components = [
        row for row in bundle.components if row.formulation_id == source.record_id
    ]
    source_links = [
        row for row in bundle.field_evidence_links
        if row.entity_type == "formulation" and row.entity_id == source.record_id
    ]
    components = list(bundle.components)
    links = list(bundle.field_evidence_links)
    enriched_formulations = []
    for formulation in bundle.formulations:
        if formulation.record_id not in targets:
            enriched_formulations.append(formulation)
            continue
        enriched_formulations.append(replace(
            formulation,
            chemical_formulation_total=source.chemical_formulation_total,
            lnp_molar_ratio=source.lnp_molar_ratio,
            composition_raw=source.composition_raw,
            composition_basis=source.composition_basis,
            formulation_notes=(
                "Shared αCD163-targeted LNP carrier; payload identity differs."
            ),
            formulation_review_status=source.formulation_review_status,
        ))
        for link in source_links:
            links.append(replace(link, entity_id=formulation.record_id))
        for index, component in enumerate(source_components, start=1):
            cloned_id = (
                f"{bundle.paper.source_paper_id}:SHARED:"
                f"{formulation.record_id.rsplit(':', 1)[-1]}:{index}"
            )
            components.append(replace(
                component,
                record_id=cloned_id,
                formulation_id=formulation.record_id,
            ))
            links.extend(
                replace(link, entity_id=cloned_id)
                for link in bundle.field_evidence_links
                if link.entity_type == "component"
                and link.entity_id == component.record_id
            )
    return replace(
        bundle,
        formulations=tuple(enriched_formulations),
        components=tuple(components),
        field_evidence_links=tuple(links),
    )


def _recover_gp008_luciferase_outcome(
    bundle: ImportBundle, root: Path | None
) -> ImportBundle:
    """Normalize the source-clause Luc kinetic result omitted by the graph."""

    if bundle.paper.source_paper_id != "GP-008" or root is None:
        return bundle
    arm = next(
        row for row in bundle.arms
        if row.formulation_id.endswith(":FORM:F4")
    )
    if any(row.arm_id == arm.record_id for row in bundle.outcomes):
        return bundle
    source_path = root / "data/staging/extraction/g1_fulltext_rag/GP-008/source_clauses.json"
    if not source_path.is_file():
        return bundle
    clauses = json.loads(source_path.read_text(encoding="utf-8"))
    clause = next(row for row in clauses if row.get("clause_id") == "B012C002")
    artifact_id = "GP-008:source-clauses-normalization"
    outcome_id = "GP-008:OUT:GP-008-E01:F4:LUC-KINETICS"
    evidence_id = "GP-008:EV:B012C002:LUC-KINETICS"
    artifact = SourceArtifactRecord(
        artifact_id=artifact_id,
        path="data/staging/extraction/g1_fulltext_rag/GP-008/source_clauses.json",
        sha256=_sha256(source_path), source_kind="validated_extraction",
        pipeline_name="g1_source_clause_projection", pipeline_version="v1",
    )
    outcome = OutcomeRecord(
        record_id=outcome_id, paper_id="GP-008", artifact_id=artifact_id,
        arm_id=arm.record_id, endpoint_family="functional_expression",
        endpoint_name="luciferase fluorescence kinetics",
        value_status="qualitative_only",
        qualitative_outcome=(
            "Peak fluorescence intensity at 8 h post-injection; signal attenuation "
            "was evident after 24 h."
        ),
    )
    evidence = EvidenceRecord(
        record_id=evidence_id, paper_id="GP-008", artifact_id=artifact_id,
        field_name="luciferase_fluorescence_kinetics",
        evidence_location_type="results", extraction_method="text_extraction",
        extraction_confidence="high", evidence_text=clause["text"],
        arm_id=arm.record_id, outcome_id=outcome_id,
        section_name=clause["clause_id"],
        verification_status="automatically_validated",
    )
    outcome_links = tuple(
        FieldEvidenceLink(
            paper_id="GP-008", entity_type="outcome", entity_id=outcome_id,
            field_name=field_name, evidence_ids=(evidence_id,),
            verification_status="automatically_validated",
        )
        for field_name in ("endpoint_family", "endpoint_name", "qualitative_outcome")
    )
    return replace(
        bundle, artifacts=(*bundle.artifacts, artifact),
        outcomes=(*bundle.outcomes, outcome), evidence=(*bundle.evidence, evidence),
        field_evidence_links=(*bundle.field_evidence_links, *outcome_links),
    )


def _recover_gp005_table_formulations(bundle: ImportBundle, root: Path | None) -> ImportBundle:
    """Expand Table 1 formulations and project explicitly shared GP-005 context."""

    if bundle.paper.source_paper_id != "GP-005" or root is None:
        return bundle
    blocks_path = root / "data/staging/rag/gold_v1/GP-005.blocks.jsonl"
    if not blocks_path.is_file():
        return bundle
    blocks = {
        row["block_id"]: row
        for line in blocks_path.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))
    }
    table = blocks["GP-005-B-799d453b51f13ce55cad"]
    comparison = blocks["GP-005-B-b968ea93d9feb275a0e7"]
    protocol = blocks["GP-005-B-4f6880c631811896358c"]
    protocol_outcomes = blocks["GP-005-B-ac54e8065863b347bd06"]
    artifact_id = "GP-005:gold-v1-blocks"
    artifact = SourceArtifactRecord(
        artifact_id=artifact_id,
        path="data/staging/rag/gold_v1/GP-005.blocks.jsonl",
        sha256=_sha256(blocks_path),
        source_kind="xml",
        pipeline_name="gold_v1_ingestion",
        pipeline_version="v1",
    )
    evidence_rows = {
        "table": EvidenceRecord(
            record_id="GP-005:EV:TABLE1-ROWS", paper_id="GP-005",
            artifact_id=artifact_id, field_name="formulation_table",
            evidence_location_type="table", extraction_method="structured_table",
            extraction_confidence="high", evidence_text=table["text"],
            section_name=table["section_path"], table_number="Table 1",
            verification_status="automatically_validated",
        ),
        "comparison": EvidenceRecord(
            record_id="GP-005:EV:LNP3-7-COMPARISON", paper_id="GP-005",
            artifact_id=artifact_id, field_name="experimental_context",
            evidence_location_type="paragraph", extraction_method="text_extraction",
            extraction_confidence="high", evidence_text=comparison["text"],
            section_name=comparison["section_path"],
            verification_status="automatically_validated",
        ),
        "protocol": EvidenceRecord(
            record_id="GP-005:EV:LNP16-PROTOCOL", paper_id="GP-005",
            artifact_id=artifact_id, field_name="experimental_context",
            evidence_location_type="paragraph", extraction_method="text_extraction",
            extraction_confidence="high", evidence_text=protocol["text"],
            section_name=protocol["section_path"],
            verification_status="automatically_validated",
        ),
        "protocol_outcomes": EvidenceRecord(
            record_id="GP-005:EV:LNP16-17-OUTCOMES", paper_id="GP-005",
            artifact_id=artifact_id, field_name="experimental_context",
            evidence_location_type="paragraph", extraction_method="text_extraction",
            extraction_confidence="high", evidence_text=protocol_outcomes["text"],
            section_name=protocol_outcomes["section_path"],
            verification_status="automatically_validated",
        ),
    }
    base = next(row for row in bundle.formulations if row.formulation_name == "Egfp mRNA‐LNP (LNP1)")
    grouped = next(row for row in bundle.formulations if row.formulation_name == "LNP3‐LNP7")
    table_specs = {
        "LNP3": ("MC3", "5moU-modified EGFP mRNA"),
        "LNP4": ("SM-102", "5moU-modified EGFP mRNA"),
        "LNP5": ("SM-102", "unmodified EGFP mRNA"),
        "LNP6": ("MC3", "m1Ψ-modified EGFP mRNA"),
        "LNP7": ("SM-102", "m1Ψ-modified EGFP mRNA"),
    }
    formulations = [row for row in bundle.formulations if row.record_id != grouped.record_id]
    components = list(bundle.components)
    grouped_arm_id = "GP-005:ARM:GP-005-E02:ENT-LNP3-7"
    links = [
        row for row in bundle.field_evidence_links
        if row.entity_id not in {grouped.record_id, grouped_arm_id}
    ]
    arms = [row for row in bundle.arms if row.formulation_id != grouped.record_id]
    outcomes = list(bundle.outcomes)
    base_components = [row for row in bundle.components if row.formulation_id == base.record_id]

    def add_formulation(name: str, ionizable: str) -> FormulationRecord:
        formulation_id = f"GP-005:FORM:{name}"
        total = f"{ionizable}-DSPC-cholesterol-DMG-PEG2000"
        row = FormulationRecord(
            record_id=formulation_id, paper_id="GP-005", artifact_id=artifact_id,
            formulation_name=name, chemical_formulation_total=total,
            lnp_molar_ratio="50:10:38.5:1.5",
            composition_raw=f"{total.replace('-', ':', 1)} = 50:10:38.5:1.5",
            composition_basis="lipid molar ratio",
            formulation_notes=(
                "Table 1 prints SN102; the adjacent narrative identifies the replacement lipid as SM-102."
                if ionizable == "SM-102" else None
            ),
            formulation_review_status="source_verified",
        )
        formulations.append(row)
        for field_name in (
            "formulation_name", "chemical_formulation_total", "lnp_molar_ratio",
            "composition_raw", "composition_basis",
        ):
            links.append(FieldEvidenceLink(
                paper_id="GP-005", entity_type="formulation", entity_id=formulation_id,
                field_name=field_name,
                evidence_ids=(evidence_rows["table"].record_id, "GP-005:EV:0001"),
                verification_status="automatically_validated",
            ))
        for position, component in enumerate(base_components, start=1):
            is_ionizable = component.component_role == "ionizable_lipid"
            component_name = ionizable if is_ionizable else component.component_name_reported
            component_id = f"GP-005:COMP:{name}:{position}"
            components.append(replace(
                component, record_id=component_id, artifact_id=artifact_id,
                formulation_id=formulation_id, component_name_reported=component_name,
                component_name_normalized=component_name if is_ionizable else component.component_name_normalized,
                component_review_status="automatically_normalized",
            ))
            for field_name in (
                "component_name_reported", "component_name_normalized", "component_role",
                "molar_percentage", "percentage_unit",
            ):
                links.append(FieldEvidenceLink(
                    paper_id="GP-005", entity_type="component", entity_id=component_id,
                    field_name=field_name,
                    evidence_ids=(evidence_rows["table"].record_id, "GP-005:EV:0001"),
                    verification_status="automatically_validated",
                ))
        return row

    for name, (ionizable, payload) in table_specs.items():
        formulation = add_formulation(name, ionizable)
        arm_id = f"GP-005:ARM:GP-005-E02:{name}"
        arms.append(ArmRecord(
            record_id=arm_id, paper_id="GP-005", artifact_id=artifact_id,
            formulation_id=formulation.record_id, cell_type="HeLa cell; human primary macrophage",
            intended_target_cell="HeLa cell; human primary macrophage",
            observed_transfected_cell="HeLa cell; human primary macrophage",
            species="Homo sapiens", in_vitro_in_vivo="in_vitro",
            payload_type="mRNA", payload_name=payload,
            payload_encoded_product="EGFP", dose=1.0, dose_unit="micrograms per mL",
            route="in vitro incubation", timepoint=24.0, timepoint_unit="hours",
            assay="flow cytometry", experiment_notes="Table 1 formulation comparison.",
            completeness_status="complete", verification_status="automatically_validated",
        ))
        for field_name in (
            "cell_type", "intended_target_cell", "observed_transfected_cell", "species", "in_vitro_in_vivo",
            "payload_type", "payload_name", "payload_encoded_product", "dose", "dose_unit",
            "route", "timepoint", "timepoint_unit", "assay",
        ):
            links.append(FieldEvidenceLink(
                paper_id="GP-005", entity_type="arm", entity_id=arm_id,
                field_name=field_name,
                evidence_ids=(evidence_rows["table"].record_id,
                              evidence_rows["comparison"].record_id),
                verification_status="automatically_validated",
            ))
        for suffix, cell, qualitative in (
            ("HELA", "HeLa cells", "significant EGFP protein translation"),
            ("MAC", "human primary macrophages", "low EGFP protein translation"),
        ):
            outcome_id = f"GP-005:OUT:GP-005-E02:{name}:{suffix}"
            outcomes.append(OutcomeRecord(
                record_id=outcome_id, paper_id="GP-005", artifact_id=artifact_id,
                arm_id=arm_id, endpoint_family="functional_expression",
                endpoint_name=f"EGFP expression in {cell}", value_status="qualitative_only",
                qualitative_outcome=qualitative,
            ))
            for field_name in ("endpoint_family", "endpoint_name", "qualitative_outcome"):
                links.append(FieldEvidenceLink(
                    paper_id="GP-005", entity_type="outcome", entity_id=outcome_id,
                    field_name=field_name,
                    evidence_ids=(evidence_rows["comparison"].record_id,),
                    verification_status="automatically_validated",
                ))

    # The fabrication method states that all study LNP use the common carrier recipe.
    # The 2:1 mRNA:siRNA value is payload ratio and must not replace lipid molar ratio.
    for name in ("LNP16", "LNP17"):
        index = next(i for i, row in enumerate(formulations) if row.formulation_name == name)
        old = formulations[index]
        formulations[index] = replace(
            old, chemical_formulation_total=base.chemical_formulation_total,
            lnp_molar_ratio=base.lnp_molar_ratio, composition_raw=base.composition_raw,
            composition_basis=base.composition_basis,
            formulation_notes="Carrier recipe is shared; mRNA:siRNA payload ratio is 2:1.",
            formulation_review_status="source_verified",
        )
        for field_name in (
            "composition_raw", "composition_basis", "chemical_formulation_total",
            "lnp_molar_ratio",
        ):
            links.append(FieldEvidenceLink(
                paper_id="GP-005", entity_type="formulation", entity_id=old.record_id,
                field_name=field_name, evidence_ids=("GP-005:EV:0001",),
                verification_status="automatically_validated",
            ))
        for position, component in enumerate(base_components, start=1):
            component_id = f"GP-005:COMP:{name}:{position}"
            components.append(replace(
                component, record_id=component_id, artifact_id=artifact_id,
                formulation_id=old.record_id, component_review_status="automatically_normalized",
            ))
            for field_name in (
                "component_name_reported", "component_name_normalized", "component_role",
                "molar_percentage", "percentage_unit",
            ):
                links.append(FieldEvidenceLink(
                    paper_id="GP-005", entity_type="component", entity_id=component_id,
                    field_name=field_name, evidence_ids=("GP-005:EV:0001",),
                    verification_status="automatically_validated",
                ))
        for i, arm in enumerate(arms):
            if arm.formulation_id != old.record_id:
                continue
            observed = (
                "hepatocyte; liver sinusoidal endothelial cell; Kupffer cell; "
                "monocyte-derived macrophage"
                if name == "LNP16" else "hepatocyte; Kupffer cell; hepatic stellate cell"
            )
            arms[i] = replace(
                arm, cell_type="liver cell", tissue_or_organ="liver",
                target_or_recipient_organ="liver", observed_transfected_cell=observed,
                species="Mus musculus", disease_model="mouse",
                in_vitro_in_vivo="in_vivo", dose=3.0, dose_unit="mg_per_kg",
                route="intravenous injection", timepoint=16.0, timepoint_unit="hours",
                assay="flow cytometry; quantitative PCR",
            )
            for field_name in (
                "cell_type", "tissue_or_organ", "target_or_recipient_organ",
                "observed_transfected_cell", "species", "disease_model", "in_vitro_in_vivo",
                "dose", "dose_unit", "route", "timepoint", "timepoint_unit", "assay",
            ):
                links.append(FieldEvidenceLink(
                    paper_id="GP-005", entity_type="arm", entity_id=arm.record_id,
                    field_name=field_name,
                    evidence_ids=(evidence_rows["protocol"].record_id,
                                  evidence_rows["protocol_outcomes"].record_id),
                    verification_status="automatically_validated",
                ))

    reviews = tuple(
        row for row in bundle.reviews
        if row.arm_id != grouped_arm_id
    )
    retained_evidence = tuple(
        replace(row, arm_id=None) if row.arm_id == grouped_arm_id else row
        for row in bundle.evidence
    )
    return replace(
        bundle, artifacts=(*bundle.artifacts, artifact), formulations=tuple(formulations),
        components=tuple(components), arms=tuple(arms), outcomes=tuple(outcomes),
        evidence=(*retained_evidence, *evidence_rows.values()),
        field_evidence_links=tuple(links), reviews=reviews,
    )


def adapt_accepted_graph_losslessly(
    graph_path: str | Path,
    **metadata: str | None,
) -> LosslessAdapterResult:
    """Account for every accepted-graph record before normalized projection."""

    path = Path(graph_path)
    graph = json.loads(path.read_text(encoding="utf-8"))
    bundle = adapt_accepted_graph(path, **metadata)
    root = _repository_root(path)
    if root is not None:
        bundle = _gold_enriched_bundle(bundle, root)
    bundle = _project_gp004_patent_ratio(bundle, root)
    bundle = _recover_gp005_table_formulations(bundle, root)
    bundle = _correct_gp007_chemistry(bundle)
    bundle = _project_gp008_shared_targeted_platform(bundle)
    bundle = _recover_gp008_luciferase_outcome(bundle, root)
    paper_id = str(graph["paper_id"])
    ledger_artifact = LedgerArtifactRecord(
        paper_id=paper_id,
        logical_path=(
            path.resolve().relative_to(root).as_posix()
            if root is not None
            else path.as_posix()
        ),
        sha256=_sha256(path),
        role="primary_extraction",
        schema_family="accepted_graph",
        validation_status="accepted",
        contributes_facts=True,
        contributes_evidence=True,
        pipeline_name="g1_fulltext_rag",
        pipeline_version=str(graph.get("contract_version") or "unknown"),
    )
    facts: list[SourceFactRecord] = []
    for index, entity in enumerate(graph.get("entities", [])):
        key = str(entity.get("entity_id") or f"entity-{index}")
        field_name = f"entity:{entity.get('entity_type') or 'unknown'}"
        facts.append(
            SourceFactRecord(
                json_path=f"$.entities[{index}]",
                source_record_key=key,
                record_kind="entity",
                subject_type=str(entity.get("entity_type") or "unknown"),
                subject_key=key,
                field_name=field_name,
                raw_value=entity,
                fact_identity_sha256=fact_identity(
                    paper_id, "entity", key, field_name, entity
                ),
                import_disposition="unresolved",
                disposition_reason="awaiting normalized entity projection",
            )
        )
    for index, claim in enumerate(graph.get("claims", [])):
        key = str(claim.get("claim_id") or f"claim-{index}")
        predicate = str(claim.get("predicate") or "unknown_predicate")
        supported = predicate in SUPPORTED_PREDICATES
        evidence_refs = tuple(
            SourceFactEvidenceRecord(
                source_evidence_key=str(item.get("clause_id") or f"{key}:{offset}"),
                resolution_status="unresolved",
                resolution_reason="awaiting canonical evidence import",
            )
            for offset, item in enumerate(claim.get("evidence", []))
        )
        facts.append(
            SourceFactRecord(
                json_path=f"$.claims[{index}]",
                source_record_key=key,
                record_kind="claim",
                subject_type="claim",
                subject_key=str(claim.get("subject_entity_id") or key),
                field_name=FIELD_BY_PREDICATE.get(predicate, predicate),
                raw_value=claim,
                fact_identity_sha256=fact_identity(
                    paper_id, "claim", key, predicate, claim
                ),
                import_disposition="unresolved" if supported else "quarantined",
                disposition_reason=(
                    "awaiting normalized claim projection"
                    if supported
                    else f"unsupported accepted-graph predicate: {predicate}"
                ),
                evidence=evidence_refs,
            )
        )
    for index, experiment in enumerate(graph.get("experiments", [])):
        key = str(experiment.get("experiment_id") or f"experiment-{index}")
        facts.append(
            SourceFactRecord(
                json_path=f"$.experiments[{index}]",
                source_record_key=key,
                record_kind="experiment",
                subject_type="experiment",
                subject_key=key,
                field_name="experiment_membership",
                raw_value=experiment,
                fact_identity_sha256=fact_identity(
                    paper_id, "experiment", key, "experiment_membership", experiment
                ),
                import_disposition="unresolved",
                disposition_reason="awaiting normalized arm projection",
            )
        )
    return LosslessAdapterResult(
        bundle=bundle,
        artifact=ledger_artifact,
        source_facts=tuple(facts),
        coverage=AdapterCoverage(
            source_entities=len(graph.get("entities", [])),
            source_claims=len(graph.get("claims", [])),
            source_experiments=len(graph.get("experiments", [])),
            silent_omissions=0,
        ),
    )


def generate_gp_bundles(repository_root: str | Path, output_dir: str | Path) -> tuple[Path, ...]:
    """Generate the six supported GP bundles from committed local artifacts."""

    root = Path(repository_root)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "data/manifests/gold_source_manifest_v1.json").read_text(encoding="utf-8"))
    metadata = {row["paper_id"]: row for row in manifest["papers"]}
    written: list[Path] = []
    for paper_id in SUPPORTED_GP:
        row = metadata[paper_id]
        relative_graph_path = Path("data/staging/extraction/g1_fulltext_rag") / paper_id / "accepted_graph.json"
        graph_path = root / relative_graph_path
        bundle = adapt_accepted_graph(
            graph_path, provenance_path=str(relative_graph_path), doi=row.get("doi"),
            pmid=row.get("pmid"), pmcid=row.get("pmcid")
        )
        output_path = destination / f"{paper_id}.json"
        output_path.write_text(
            json.dumps(bundle.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written.append(output_path)
    return tuple(written)


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[3]
    generate_gp_bundles(repo, repo / "data/staging/database/day2_bundles/gp")


__all__ = [
    "SCREENING_ONLY",
    "SUPPORTED_GP",
    "adapt_accepted_graph",
    "adapt_accepted_graph_losslessly",
    "generate_gp_bundles",
]
