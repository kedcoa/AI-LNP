"""Evidence-graph-first extraction with verifier corrections applied."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .contracts_v4 import EvidenceGraphV4, SourceClauseV4, VerifiedEvidenceGraphV4
from .run_abstract_first import ROOT, gold_inputs


OUTPUT = ROOT / "data" / "staging" / "extraction" / "g1_v4"
FROZEN_BOUNDARIES = ROOT / "data" / "staging" / "extraction" / "g1_v3_frozen_boundaries"

PREDICATE_TYPES: dict[str, tuple[set[str], set[str]]] = {
    "has_formulation": ({"intervention", "biological_model"}, {"lnp_formulation"}),
    "has_component": ({"lnp_formulation"}, {"lnp_component"}),
    "has_component_role": ({"lnp_component"}, {"intervention"}),
    "has_component_amount": ({"lnp_component"}, {"dose"}),
    "carries_payload": ({"lnp_formulation"}, {"payload"}),
    "encodes_product": ({"payload"}, {"encoded_product"}),
    "targets_molecule": ({"payload", "encoded_product", "intervention"}, {"molecular_target"}),
    "has_targeting_ligand": ({"lnp_formulation"}, {"targeting_ligand"}),
    "delivered_to_cell": ({"lnp_formulation", "payload", "intervention"}, {"cell"}),
    "therapeutic_target_cell": ({"lnp_formulation", "payload", "encoded_product", "intervention"}, {"cell"}),
    "has_tissue_context": ({"intervention", "biological_model", "lnp_formulation"}, {"tissue_or_organ"}),
    "has_disease_context": ({"intervention", "biological_model", "lnp_formulation"}, {"disease"}),
    "has_physiological_context": ({"intervention", "biological_model", "lnp_formulation"}, {"physiological_state"}),
    "has_species": ({"biological_model", "intervention"}, {"species"}),
    "has_biological_model": ({"intervention", "lnp_formulation"}, {"biological_model"}),
    "has_intervention": ({"biological_model", "lnp_formulation"}, {"intervention", "lnp_formulation"}),
    "has_assay": ({"intervention", "lnp_formulation"}, {"assay"}),
    "has_route": ({"intervention", "lnp_formulation"}, {"route"}),
    "has_dose": ({"intervention", "lnp_formulation"}, {"dose"}),
    "has_timepoint": ({"intervention", "endpoint"}, {"timepoint"}),
    "measures_endpoint": ({"intervention", "lnp_formulation", "payload", "assay"}, {"endpoint"}),
    "has_outcome_value": ({"endpoint"}, {"outcome_value"}),
    "compared_with": ({"intervention", "endpoint", "biological_model"}, {"intervention", "endpoint", "biological_model", "cell"}),
}


def split_source(text: str) -> list[SourceClauseV4]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if part.strip()]
    clauses: list[SourceClauseV4] = []
    count = 0
    for sentence_index, sentence in enumerate(sentences, 1):
        # Conservative punctuation split. Coordinating conjunctions remain for the
        # claim extractor to expand without destroying their shared grammatical head.
        parts = [part.strip() for part in re.split(r"(?<=[;:])\s+", sentence) if part.strip()]
        for part in parts:
            count += 1
            clauses.append(SourceClauseV4(clause_id=f"C{count:03d}", sentence_id=f"S{sentence_index:02d}", text=part))
    return clauses


def response_envelope(response: Any) -> dict[str, Any]:
    choice = response.choices[0]
    return {
        "model": response.model,
        "finish_reason": choice.finish_reason,
        "content": choice.message.content,
        "usage": response.usage.model_dump() if response.usage else None,
    }


def call_json(client: OpenAI, model: str, system: str, payload: dict[str, Any], max_tokens: int):
    return client.chat.completions.create(
        model=model,
        temperature=0,
        max_completion_tokens=max_tokens,
        timeout=240.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )


def audit_graph(graph: EvidenceGraphV4, clauses: list[SourceClauseV4]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    clause_lookup = {row.clause_id: row.text for row in clauses}
    entity_lookup = {row.entity_id: row for row in graph.entities}
    experiment_lookup = {row.experiment_id: row for row in graph.experiments}

    def check_evidence(owner: str, evidence):
        for span in evidence:
            source = clause_lookup.get(span.clause_id)
            if source is None:
                issues.append({"owner": owner, "issue": "unknown_clause", "detail": span.clause_id})
            elif re.sub(r"\s+", " ", span.quote).strip().lower() not in re.sub(r"\s+", " ", source).strip().lower():
                issues.append({"owner": owner, "issue": "non_verbatim_quote", "detail": span.quote})

    for entity in graph.entities:
        check_evidence(entity.entity_id, entity.evidence)
        if entity.entity_type == "lnp_component" and re.search(r"\b(mrna|sirna|sgrna|rna)\b", entity.reported_name, re.I):
            issues.append({"owner": entity.entity_id, "issue": "payload_as_component", "detail": entity.reported_name})
        if entity.entity_type == "disease" and entity.reported_name.strip().lower() in {"healthy", "homeostasis", "healthy liver"}:
            issues.append({"owner": entity.entity_id, "issue": "physiology_as_disease", "detail": entity.reported_name})
    for claim in graph.claims:
        check_evidence(claim.claim_id, claim.evidence)
        subject = entity_lookup[claim.subject_entity_id].entity_type
        obj = entity_lookup[claim.object_entity_id].entity_type
        allowed_subjects, allowed_objects = PREDICATE_TYPES[claim.predicate]
        if subject not in allowed_subjects or obj not in allowed_objects:
            issues.append({
                "owner": claim.claim_id,
                "issue": "predicate_type_violation",
                "detail": f"{subject} --{claim.predicate}--> {obj}",
            })
        if claim.experiment_id != "SHARED":
            experiment = experiment_lookup[claim.experiment_id]
            evidence_clause_ids = {span.clause_id for span in claim.evidence}
            if not evidence_clause_ids <= set(experiment.source_scope_clause_ids):
                issues.append({"owner": claim.claim_id, "issue": "evidence_outside_experiment_scope", "detail": ",".join(sorted(evidence_clause_ids))})
        subject_clause_ids = {span.clause_id for span in entity_lookup[claim.subject_entity_id].evidence}
        object_clause_ids = {span.clause_id for span in entity_lookup[claim.object_entity_id].evidence}
        claim_clause_ids = {span.clause_id for span in claim.evidence}
        if not claim_clause_ids & subject_clause_ids & object_clause_ids:
            issues.append({
                "owner": claim.claim_id,
                "issue": "relation_entities_not_co_supported",
                "detail": f"{claim.subject_entity_id} and {claim.object_entity_id} lack entity evidence in the same cited clause",
            })
    # One cell list is represented by one relation per cell, never one combined cell entity.
    for entity in graph.entities:
        if entity.entity_type == "cell" and re.search(r",|;|\band\b|\bor\b", entity.reported_name, re.I):
            issues.append({"owner": entity.entity_id, "issue": "merged_cell_entity", "detail": entity.reported_name})
    if any(experiment.experiment_id == "SHARED" for experiment in graph.experiments):
        issues.append({"owner": "SHARED", "issue": "reserved_shared_id_used_as_experiment", "detail": "SHARED is a claim scope, not an experiment"})
    return issues


def extractor_payload(item: dict[str, Any], clauses: list[SourceClauseV4], boundary_constraints: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": item["paper_id"],
        "title": item["title"],
        "source_scope": "abstract_only",
        "source_clauses": [row.model_dump() for row in clauses],
        "prior_human_approved_experiment_inventory": boundary_constraints.get("experiments", []),
        "inventory_instruction": "Use the approved inventory as an event-boundary constraint only. It is not source evidence; every entity and relation still requires support from source_clauses.",
        "task": "Build an atomic evidence graph of original LNP experiments.",
        "rules": [
            "Use only source_clauses; evidence quotes must be exact contiguous substrings of the cited clause.",
            "Create one entity per atomic biological or material entity. Never combine multiple cells in one cell entity.",
            "Expand a cell list into one delivered_to_cell claim per cell.",
            "A list of cells under identical conditions is one experiment with multiple cell relations, not automatically multiple experiments.",
            "Split experiments when formulation, payload/treatment, model, disease or physiological context, dose, route, timepoint, comparator arm, or experimental context differs.",
            "When one sentence mentions different disease/model branches, keep each cell/outcome relation inside its matching branch.",
            "Facts truly shared across experiments use experiment_id SHARED and must be explicitly linked through shared_claim_ids.",
            "Healthy/homeostasis is a physiological_state, never a disease.",
            "RNA cargo is payload, never an lnp_component.",
            "Create one endpoint entity and measures_endpoint claim per distinct outcome; never merge outcomes.",
            "Do not infer species, cells, disease, tissue, or experimental context from outside knowledge.",
            "Normalization status inferred is permitted but reported_name must remain verbatim.",
            "Abstract-only absence does not establish full-paper absence.",
        ],
        "schema": EvidenceGraphV4.model_json_schema(),
    }


def run(paper_ids: set[str] | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    extractor_model = os.getenv("G1_V4_EXTRACTOR_MODEL", "glm-5.2")
    verifier_model = os.getenv("G1_V4_VERIFIER_MODEL", "deepseek-v4-flash")
    client = OpenAI(
        api_key=os.environ["SENSENOVA_API_KEY"],
        base_url=os.getenv("SENSENOVA_BASE_URL", "https://token.sensenova.cn/v1"),
        timeout=120.0,
        max_retries=1,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "4.0.0",
        "models": {"extractor": extractor_model, "verifier_repairer": verifier_model},
        "papers": [],
    }
    for item in gold_inputs():
        paper_id = item["paper_id"]
        if paper_ids and paper_id not in paper_ids:
            continue
        paper_dir = OUTPUT / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)
        clauses = split_source(item["abstract"])
        boundary_path = FROZEN_BOUNDARIES / f"{paper_id}.json"
        boundary_constraints = json.loads(boundary_path.read_text()) if boundary_path.exists() else {"experiments": []}
        (paper_dir / "source_clauses.json").write_text(
            json.dumps([row.model_dump() for row in clauses], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if not item["eligible_records_expected"]:
            graph = EvidenceGraphV4(
                contract_version="4.0.0", paper_id=paper_id, source_scope="abstract_only",
                original_lnp_experiments_present=False, entities=[], claims=[], experiments=[],
            )
            (paper_dir / "accepted_graph.json").write_text(graph.model_dump_json(indent=2) + "\n")
            manifest["papers"].append({"paper_id": paper_id, "status": "accepted_expected_zero"})
            continue
        try:
            draft_path = paper_dir / "draft_graph.json"
            if draft_path.exists():
                draft = EvidenceGraphV4.model_validate_json(draft_path.read_text())
            else:
                response = call_json(
                    client, extractor_model,
                    "You are a conservative biomedical claim-graph extractor. Return valid JSON only.",
                    extractor_payload(item, clauses, boundary_constraints), 32000,
                )
                raw = response_envelope(response)
                (paper_dir / "extractor.response.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
                draft = EvidenceGraphV4.model_validate_json(raw["content"] or "")
                draft_path.write_text(draft.model_dump_json(indent=2) + "\n")
            draft_issues = audit_graph(draft, clauses)
            (paper_dir / "draft_audit.json").write_text(json.dumps(draft_issues, indent=2) + "\n")

            verified_path = paper_dir / "verified_graph.json"
            if verified_path.exists():
                verified = VerifiedEvidenceGraphV4.model_validate_json(verified_path.read_text())
            else:
                verification_payload = {
                    "paper_id": paper_id,
                    "title": item["title"],
                    "source_clauses": [row.model_dump() for row in clauses],
                    "prior_human_approved_experiment_inventory": boundary_constraints.get("experiments", []),
                    "inventory_instruction": "Use this only to constrain event boundaries. Do not treat its labels or mentions as source evidence.",
                    "first_graph": draft.model_dump(mode="json"),
                    "deterministic_findings": draft_issues,
                    "tasks": [
                        "Read every source clause again without trusting the first graph.",
                        "Correct or remove unsupported entities and relations.",
                        "Add explicitly supported omitted claims.",
                        "Split merged cells and outcomes.",
                        "Repair cross-experiment context leakage.",
                        "Return the complete corrected graph, not just observations.",
                        "Record every change in observations.",
                        "Use unresolved_ambiguities only when two interpretations remain defensible from the source.",
                    ],
                    "schema": VerifiedEvidenceGraphV4.model_json_schema(),
                }
                response = call_json(
                    client, verifier_model,
                    "You are an independent biomedical verifier and repairer. Apply your findings to corrected_graph. Return JSON only.",
                    verification_payload, 32000,
                )
                raw = response_envelope(response)
                (paper_dir / "verifier.response.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
                verified = VerifiedEvidenceGraphV4.model_validate_json(raw["content"] or "")
                verified_path.write_text(verified.model_dump_json(indent=2) + "\n")
            final_graph = verified.corrected_graph
            final_issues = audit_graph(final_graph, clauses)
            post_repair_observations = 0
            if final_issues:
                post_path = paper_dir / "post_audit_repair.json"
                if post_path.exists():
                    post_repair = VerifiedEvidenceGraphV4.model_validate_json(post_path.read_text())
                else:
                    post_payload = {
                        "paper_id": paper_id,
                        "source_clauses": [row.model_dump() for row in clauses],
                        "prior_human_approved_experiment_inventory": boundary_constraints.get("experiments", []),
                        "graph_requiring_final_correction": final_graph.model_dump(mode="json"),
                        "remaining_deterministic_findings": final_issues,
                        "tasks": [
                            "Apply every remaining deterministic finding to corrected_graph.",
                            "Do not merely explain or dispute a finding.",
                            "For has_outcome_value, the subject must be an endpoint.",
                            "Every evidence quote must be an exact contiguous substring of its clause.",
                            "Remove a claim if it is redundant and cannot be repaired without inference.",
                            "Return the complete corrected graph.",
                        ],
                        "schema": VerifiedEvidenceGraphV4.model_json_schema(),
                    }
                    response = call_json(
                        client, verifier_model,
                        "You are the final deterministic-audit repairer. Apply all corrections and return JSON only.",
                        post_payload, 32000,
                    )
                    raw = response_envelope(response)
                    (paper_dir / "post_audit_repair.response.json").write_text(
                        json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
                    )
                    post_repair = VerifiedEvidenceGraphV4.model_validate_json(raw["content"] or "")
                    post_path.write_text(post_repair.model_dump_json(indent=2) + "\n")
                final_graph = post_repair.corrected_graph
                post_repair_observations = len(post_repair.observations)
                final_issues = audit_graph(final_graph, clauses)
            (paper_dir / "final_audit.json").write_text(json.dumps(final_issues, indent=2) + "\n")
            if final_issues:
                status = "rejected_after_repair"
            elif verified.unresolved_ambiguities:
                status = "human_review_required"
            else:
                status = "accepted_after_repair"
                (paper_dir / "accepted_graph.json").write_text(final_graph.model_dump_json(indent=2) + "\n")
            manifest["papers"].append({
                "paper_id": paper_id,
                "status": status,
                "draft_issues": len(draft_issues),
                "repair_observations": len(verified.observations),
                "post_repair_observations": post_repair_observations,
                "final_issues": len(final_issues),
                "unresolved_ambiguities": len(verified.unresolved_ambiguities),
                "experiments": len(verified.corrected_graph.experiments),
                "claims": len(verified.corrected_graph.claims),
            })
        except Exception as error:
            manifest["papers"].append({"paper_id": paper_id, "status": "technical_failure", "error": str(error)})
        (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    args = parser.parse_args()
    print(json.dumps(run(set(args.paper_id) if args.paper_id else None), indent=2))
