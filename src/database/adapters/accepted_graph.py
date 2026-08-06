"""Convert evidence-linked accepted graphs into conservative import bundles."""

from __future__ import annotations

import hashlib
import json
import re
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


SCREENING_ONLY = frozenset({"GP-001", "GP-003", "GP-009"})
SUPPORTED_GP = ("GP-002", "GP-004", "GP-005", "GP-006", "GP-007", "GP-008")
SUPPORTED_PREDICATES = frozenset(
    {
        "carries_payload", "encodes_product", "has_assay", "has_biological_model",
        "has_component", "has_disease_context", "has_dose", "has_formulation",
        "has_molecular_target", "has_outcome_value", "has_physiological_context",
        "has_route", "has_species", "has_targeting_ligand", "has_timepoint",
        "has_tissue_or_organ", "measures_endpoint", "therapeutic_target_cell",
        "delivery_target_cell",
    }
)
FIELD_BY_PREDICATE = {
    "has_species": "species", "has_route": "route", "has_dose": "dose",
    "has_timepoint": "timepoint", "has_assay": "assay",
    "has_biological_model": "disease_model", "has_disease_context": "disease_model",
    "has_tissue_or_organ": "tissue_or_organ", "therapeutic_target_cell": "cell_type",
    "delivery_target_cell": "cell_type", "carries_payload": "payload_name",
    "encodes_product": "payload_encoded_product", "has_molecular_target": "payload_molecular_target",
}


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
                section_name=item.get("clause_id"), verification_status="unreviewed",
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
            links.append(FieldEvidenceLink(paper_id, "formulation", record_id, "formulation_name", ids))
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
                links.append(FieldEvidenceLink(paper_id, "component", record_id, field, ids))

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
                if owners and claim.get("predicate") in {"carries_payload", "encodes_product", "measures_endpoint"}:
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
                    values[field] = value if field not in values else f"{values[field]}; {value}"
                    field_claims.setdefault(field, []).append(claim)
            dose_text = values.get("dose")
            time_text = values.get("timepoint")
            dose = _number(dose_text)
            dose_unit = _unit(dose_text, "dose")
            if dose is not None and dose_unit is None:
                dose = None
            arms.append(ArmRecord(
                record_id=arm_id, paper_id=paper_id, artifact_id=artifact_id,
                formulation_id=formulation_id,
                cell_type=values.get("cell_type") or values.get("tissue_or_organ") or "",
                tissue_or_organ=values.get("tissue_or_organ"), species=values.get("species"),
                disease_model=values.get("disease_model"),
                payload_type="nucleic acid" if values.get("payload_name") else None,
                payload_name=values.get("payload_name"),
                payload_encoded_product=values.get("payload_encoded_product"),
                payload_molecular_target=values.get("payload_molecular_target"),
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
                    links.append(FieldEvidenceLink(paper_id, "arm", arm_id, field, ids))
                    if field == "dose" and dose_unit:
                        links.append(FieldEvidenceLink(paper_id, "arm", arm_id, "dose_unit", ids))
                    if field == "timepoint" and _unit(time_text, "timepoint"):
                        links.append(FieldEvidenceLink(paper_id, "arm", arm_id, "timepoint_unit", ids))
            if values.get("payload_name"):
                ids = next((link.evidence_ids for link in links if link.entity_id == arm_id and link.field_name == "payload_name"), ())
                if ids:
                    links.append(FieldEvidenceLink(paper_id, "arm", arm_id, "payload_type", ids))

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
                    links.append(FieldEvidenceLink(paper_id, "outcome", outcome_id, "endpoint_name", endpoint_ids))
                    links.append(FieldEvidenceLink(paper_id, "outcome", outcome_id, "endpoint_family", endpoint_ids))
                if value_ids:
                    links.append(FieldEvidenceLink(paper_id, "outcome", outcome_id, value_field, value_ids))
                    if outcome_value is not None and _unit(values_text, "outcome"):
                        links.append(FieldEvidenceLink(paper_id, "outcome", outcome_id, "outcome_unit", value_ids))
            unknown_ids = add_evidence(
                [item for claim in unknown for item in claim.get("evidence", [])],
                "unsupported_relationship", arm_id=arm_id,
            )
            reviews.append(ReviewRecord(
                record_id=f"{paper_id}:REV:{experiment_id}:{form_entity_id}", paper_id=paper_id,
                artifact_id=artifact_id,
                reason_code="needs_human_verification" if unknown else "missing_dose" if not dose_text else "missing_evidence_excerpt",
                status="incomplete", evidence_ids=unknown_ids, arm_id=arm_id,
                notes="Unsupported graph relation evidence requires review." if unknown else "Arm is retained but is not complete enough for training.",
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
            reason_code="needs_human_verification", status="incomplete",
            evidence_ids=ids,
            notes="Exact accepted-graph evidence is retained, but its relationship is not safely normalized.",
        ))

    return ImportBundle(
        paper=paper, artifacts=(artifact,), formulations=tuple(formulations), components=tuple(components),
        arms=tuple(arms), outcomes=tuple(outcomes), evidence=tuple(evidence),
        field_evidence_links=tuple(links), reviews=tuple(reviews),
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


__all__ = ["SCREENING_ONLY", "SUPPORTED_GP", "adapt_accepted_graph", "generate_gp_bundles"]
