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

from src.extraction.contracts_v4 import EvidenceGraphV4, SourceClauseV4, VerifiedEvidenceGraphV4
from src.extraction.run_abstract_first import ROOT, gold_inputs
from src.extraction.run_g1_v4 import audit_graph, response_envelope
from src.rag.result_candidates import (
    pending_sidecar,
    validate_candidate_cardinality,
)


PACKETS = ROOT / "data" / "staging" / "rag" / "retrieval_packets"
BOUNDARIES = ROOT / "data" / "staging" / "extraction" / "g1_v3_frozen_boundaries"
OUTPUT = ROOT / "data" / "staging" / "extraction" / "g1_fulltext_rag"


def provider_configuration() -> tuple[str, str, str, OpenAI]:
    provider = os.getenv("RAG_LLM_PROVIDER", "sensenova").lower()
    if provider == "openai":
        extractor_model = os.getenv("RAG_EXTRACTION_MODEL", "gpt-5.6-sol")
        verifier_model = os.getenv("RAG_VERIFIER_MODEL", "gpt-5.6-terra")
        client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=240.0,
            max_retries=1,
        )
    elif provider == "sensenova":
        extractor_model = os.getenv("RAG_EXTRACTION_MODEL", "deepseek-v4-flash")
        verifier_model = os.getenv("RAG_VERIFIER_MODEL", "glm-5.2")
        client = OpenAI(
            api_key=os.environ["SENSENOVA_API_KEY"],
            base_url=os.getenv("SENSENOVA_BASE_URL", "https://token.sensenova.cn/v1"),
            timeout=240.0,
            max_retries=1,
        )
    else:
        raise ValueError(f"Unsupported RAG_LLM_PROVIDER: {provider}")
    return provider, extractor_model, verifier_model, client


def call_sensenova_json(
    client: OpenAI,
    model: str,
    system: str,
    payload: dict[str, Any],
    max_tokens: int,
):
    return client.chat.completions.create(
        model=model,
        temperature=0,
        max_completion_tokens=max_tokens,
        reasoning_effort="low",
        timeout=240.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )


def call_openai_structured(
    client: OpenAI,
    model: str,
    system: str,
    payload: dict[str, Any],
    output_type,
):
    # The SDK derives the JSON schema directly from the Pydantic contract, so
    # sending the same schema inside the prompt would waste input tokens.
    model_payload = dict(payload)
    model_payload.pop("schema", None)
    response = client.responses.parse(
        model=model,
        reasoning={"effort": "low"},
        store=False,
        input=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(model_payload, ensure_ascii=False),
            },
        ],
        text_format=output_type,
    )
    if response.output_parsed is None:
        refusals = [
            item.refusal
            for output in response.output
            if output.type == "message"
            for item in output.content
            if item.type == "refusal"
        ]
        detail = "; ".join(refusals) if refusals else "no parsed output"
        raise RuntimeError(f"OpenAI structured extraction failed: {detail}")
    return response, response.output_parsed


def clauses_from_packet(
    packet_payload: dict[str, Any],
    *,
    hits_per_field: int = 6,
    max_characters: int = 30_000,
) -> tuple[list[SourceClauseV4], dict[str, dict]]:
    unique: dict[str, dict] = {}
    for field, packet in packet_payload["packets"].items():
        for hit in packet["hits"][:hits_per_field]:
            if hit["block_id"] not in unique:
                unique[hit["block_id"]] = dict(hit, _retrieval_fields=[])
            unique[hit["block_id"]]["_retrieval_fields"].append(field)
    clauses: list[SourceClauseV4] = []
    provenance: dict[str, dict] = {}
    used_characters = 0
    for block_number, hit in enumerate(unique.values(), 1):
        if used_characters >= max_characters:
            break
        block_text = hit["text"][: max_characters - used_characters]
        used_characters += len(block_text)
        sentences = [
            value.strip()
            for value in re.split(r"(?<=[.!?])\s+", " ".join(block_text.split()))
            if value.strip()
        ]
        for sentence_number, sentence in enumerate(sentences, 1):
            clause_id = f"B{block_number:03d}C{sentence_number:03d}"
            clauses.append(SourceClauseV4(
                clause_id=clause_id,
                sentence_id=f"B{block_number:03d}S{sentence_number:03d}",
                text=sentence,
            ))
            provenance[clause_id] = {
                "block_id": hit["block_id"],
                "source_path": hit["source_path"],
                "section_path": hit["section_path"],
                "page_number": hit["page_number"],
                "xml_element_id": hit.get("xml_element_id"),
                "retrieval_fields": sorted(set(hit["_retrieval_fields"])),
            }
    return clauses, provenance


OUTCOME_CANDIDATE = re.compile(
    r"(%|percent|fold|no obvious|no detectable|few |absent|solely|"
    r"fewer than|over \d|colocali[sz]|significantly|improv|ameliorat|"
    r"restor|eliminat|phagocyt|reduc|increase|decrease)",
    re.I,
)


def outcome_candidate_clauses(
    clauses: list[SourceClauseV4],
    provenance: dict[str, dict],
) -> list[dict[str, str]]:
    """List outcome-like clauses from the complete consumed evidence packet."""
    return [
        {"clause_id": clause.clause_id, "text": clause.text}
        for clause in clauses
        if OUTCOME_CANDIDATE.search(clause.text)
    ][:40]


def extraction_payload(
    paper: dict[str, Any],
    clauses: list[SourceClauseV4],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    return {
        "paper_id": paper["paper_id"],
        "title": paper["title"],
        "source_scope": "full_text_with_supplement",
        "source_clauses": [row.model_dump() for row in clauses],
        "human_approved_experiment_inventory": inventory.get("experiments", []),
        "task": "Create an experiment-scoped atomic evidence graph from the retrieved full text.",
        "rules": [
            "The inventory constrains experiment boundaries but is not evidence.",
            "Every entity and claim requires an exact contiguous quote from source_clauses.",
            "Do not transfer disease, model, dose, route, cell, endpoint, or outcome across experiments.",
            "Represent every LNP lipid as a separate lnp_component entity; RNA cargo is payload, never a component.",
            "Keep delivery recipient cells distinct from therapeutic target cells.",
            "When delivery recipient and therapeutic target are explicitly the same, create both typed relations to the same cell entity.",
            "One cell list becomes one relation per cell; never create a combined cell entity.",
            "Create a separate endpoint and outcome claim for every distinct measured result.",
            "Before finishing each inventory experiment, explicitly check formulation, payload, model, recipient cell, therapeutic target, assay, endpoint, outcome, comparator, dose, route, and timepoint.",
            "Preserve negative and qualitative outcomes such as no expression, few positive cells, below detection, improvement, or elimination.",
            "A study-wide Methods statement may support multiple experiments only when its wording explicitly establishes shared scope; cite both shared Methods and experiment-specific evidence.",
            "Neighboring clauses are context only: do not transfer facts across different section paths, figure panels, cohorts, interventions, or experiments.",
            "Distinguish uptake, delivery, expression/transfection, and therapeutic effect.",
            "Healthy/homeostasis is physiological_state, not disease.",
            "HSC must retain the meaning supported in this paper; never assume hepatic stellate cells.",
            "If retrieved evidence is insufficient for a field, omit the claim rather than infer it.",
        ],
        "schema": EvidenceGraphV4.model_json_schema(),
    }


def prune_unsupported_relations(
    graph: EvidenceGraphV4,
    findings: list[dict[str, str]],
) -> tuple[EvidenceGraphV4, list[str]]:
    """Remove relations that deterministic co-evidence checks prove unsupported."""
    removable_issues = {
        "relation_entities_not_co_supported",
        "predicate_type_violation",
    }
    claim_ids = {row.claim_id for row in graph.claims}
    removed = sorted({
        row["owner"]
        for row in findings
        if row["issue"] in removable_issues and row["owner"] in claim_ids
    })
    if not removed:
        return graph, []
    removed_set = set(removed)
    payload = graph.model_dump(mode="json")
    payload["claims"] = [
        claim for claim in payload["claims"]
        if claim["claim_id"] not in removed_set
    ]
    for experiment in payload["experiments"]:
        experiment["claim_ids"] = [
            claim_id for claim_id in experiment["claim_ids"]
            if claim_id not in removed_set
        ]
        experiment["shared_claim_ids"] = [
            claim_id for claim_id in experiment["shared_claim_ids"]
            if claim_id not in removed_set
        ]
    payload["experiments"] = [
        experiment
        for experiment in payload["experiments"]
        if experiment["claim_ids"]
    ]
    if not payload["experiments"]:
        payload["original_lnp_experiments_present"] = False
    return EvidenceGraphV4.model_validate(payload), removed


def is_confirmed_negative_control(
    graph: EvidenceGraphV4,
    inventory: dict[str, Any],
) -> bool:
    """Require both extraction and the human-approved inventory to be empty."""
    return (
        not graph.original_lnp_experiments_present
        and not graph.experiments
        and not graph.claims
        and not inventory.get("experiments", [])
    )


def repair_non_verbatim_quotes(
    graph: EvidenceGraphV4,
    clauses: list[SourceClauseV4],
) -> EvidenceGraphV4:
    """Replace rewritten quotes with the exact text of their cited clause."""
    clause_text = {clause.clause_id: clause.text for clause in clauses}
    payload = graph.model_dump(mode="json")
    for owner in payload["entities"] + payload["claims"]:
        for evidence in owner["evidence"]:
            source = clause_text.get(evidence["clause_id"])
            if source is not None and evidence["quote"] not in source:
                evidence["quote"] = source
    return EvidenceGraphV4.model_validate(payload)


def audit_rag_graph(
    graph: EvidenceGraphV4,
    clauses: list[SourceClauseV4],
    provenance: dict[str, dict],
    inventory: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Accept relation co-support across adjacent clauses in one source block."""
    findings = audit_graph(graph, clauses)
    claims = {claim.claim_id: claim for claim in graph.claims}
    entities = {entity.entity_id: entity for entity in graph.entities}

    def blocks(evidence) -> set[str]:
        return {
            provenance[span.clause_id]["block_id"]
            for span in evidence
            if span.clause_id in provenance
        }

    filtered: list[dict[str, str]] = []
    for finding in findings:
        if finding["issue"] != "relation_entities_not_co_supported":
            filtered.append(finding)
            continue
        claim = claims.get(finding["owner"])
        if claim is None:
            filtered.append(finding)
            continue
        subject = entities[claim.subject_entity_id]
        obj = entities[claim.object_entity_id]
        common_blocks = (
            blocks(claim.evidence)
            & blocks(subject.evidence)
            & blocks(obj.evidence)
        )
        if not common_blocks:
            filtered.append(finding)
    if inventory is not None:
        graph_experiments = {row.experiment_id for row in graph.experiments}
        for expected in inventory.get("experiments", []):
            experiment_id = expected["experiment_id"]
            if experiment_id not in graph_experiments:
                filtered.append({
                    "owner": experiment_id,
                    "issue": "missing_inventory_experiment",
                    "detail": (
                        "The human-approved experiment inventory requires this exact "
                        "experiment ID; add supported claims or record why the supplied "
                        "clauses are insufficient."
                    ),
                })
    return filtered


def run(
    paper_ids: set[str],
    *,
    force: bool = False,
    packets_root: Path = PACKETS,
    output_root: Path = OUTPUT,
) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    provider, extractor_model, verifier_model, client = provider_configuration()
    papers = {row["paper_id"]: row for row in gold_inputs()}
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "models": {"extractor": extractor_model, "verifier": verifier_model},
        "source_scope": "full_text_with_supplement",
        "papers": [],
    }
    for paper_id in sorted(paper_ids):
        paper_dir = output_root / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)
        accepted_path = paper_dir / "accepted_graph.json"
        if accepted_path.exists() and not force:
            manifest["papers"].append({"paper_id": paper_id, "status": "cached_accepted"})
            continue
        packet_payload = json.loads((packets_root / f"{paper_id}.json").read_text())
        if packet_payload["blocked_fields"]:
            manifest["papers"].append({
                "paper_id": paper_id,
                "status": "retrieval_gate_blocked",
                "blocked_fields": packet_payload["blocked_fields"],
            })
            continue
        clauses, provenance = clauses_from_packet(packet_payload)
        outcome_candidates = outcome_candidate_clauses(clauses, provenance)
        candidate_sidecar = pending_sidecar(paper_id, clauses)
        candidate_cardinality_findings = validate_candidate_cardinality(
            clauses, candidate_sidecar.candidates
        )
        inventory_path = BOUNDARIES / f"{paper_id}.json"
        inventory = json.loads(inventory_path.read_text()) if inventory_path.exists() else {"experiments": []}
        (paper_dir / "source_clauses.json").write_text(
            json.dumps([row.model_dump() for row in clauses], indent=2) + "\n"
        )
        (paper_dir / "clause_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        (paper_dir / "outcome_candidates.pending.json").write_text(
            candidate_sidecar.model_dump_json(indent=2) + "\n"
        )
        (paper_dir / "outcome_candidate_audit.json").write_text(
            json.dumps(candidate_cardinality_findings, indent=2) + "\n"
        )
        try:
            draft_payload = extraction_payload(papers[paper_id], clauses, inventory)
            draft_payload["outcome_candidate_clauses_requiring_disposition"] = outcome_candidates
            draft_payload["atomic_result_candidates_requiring_disposition"] = [
                row.model_dump(mode="json") for row in candidate_sidecar.candidates
            ]
            draft_path = paper_dir / "draft_graph.json"
            if draft_path.exists() and not force:
                draft = EvidenceGraphV4.model_validate_json(draft_path.read_text())
            else:
                if provider == "openai":
                    extractor_response, draft = call_openai_structured(
                        client,
                        extractor_model,
                        "You are a conservative biomedical full-text claim-graph extractor.",
                        draft_payload,
                        EvidenceGraphV4,
                    )
                    (paper_dir / "extractor.response.json").write_text(
                        extractor_response.model_dump_json(indent=2, warnings=False) + "\n"
                    )
                else:
                    extractor_response = call_sensenova_json(
                        client,
                        extractor_model,
                        "You are a conservative biomedical full-text claim-graph extractor. Return valid JSON only.",
                        draft_payload,
                        24000,
                    )
                    raw = response_envelope(extractor_response)
                    (paper_dir / "extractor.response.json").write_text(json.dumps(raw, indent=2) + "\n")
                    draft = EvidenceGraphV4.model_validate_json(raw["content"] or "")
                draft_path.write_text(draft.model_dump_json(indent=2) + "\n")
            draft = repair_non_verbatim_quotes(draft, clauses)
            draft_path.write_text(draft.model_dump_json(indent=2) + "\n")
            findings = audit_rag_graph(draft, clauses, provenance, inventory)
            (paper_dir / "draft_audit.json").write_text(json.dumps(findings, indent=2) + "\n")
            if is_confirmed_negative_control(draft, inventory):
                accepted_path.write_text(draft.model_dump_json(indent=2) + "\n")
                (paper_dir / "final_audit.json").write_text(
                    json.dumps(findings, indent=2) + "\n"
                )
                manifest["papers"].append({
                    "paper_id": paper_id,
                    "status": "accepted_negative_control",
                    "experiments": 0,
                    "claims": 0,
                    "unresolved_ambiguities": [],
                    "post_repair_observations": 0,
                    "deterministically_pruned_claim_ids": [],
                    "final_audit_findings": len(findings),
                })
                continue

            verifier_payload = {
                "paper_id": paper_id,
                "source_clauses": [row.model_dump() for row in clauses],
                "human_approved_experiment_inventory": inventory.get("experiments", []),
                "first_graph": draft.model_dump(mode="json"),
                "deterministic_findings": findings,
                "outcome_candidate_clauses_requiring_disposition": outcome_candidates,
                "atomic_result_candidates_requiring_disposition": [
                    row.model_dump(mode="json") for row in candidate_sidecar.candidates
                ],
                "tasks": [
                    "Read every source clause independently a second time.",
                    "Apply all corrections to corrected_graph, not merely observations.",
                    "Add supported omissions and remove unsupported claims.",
                    "Check every experiment boundary and prevent context leakage.",
                    "Check delivery recipient versus therapeutic target cells explicitly.",
                    "Check that separate endpoints and outcome values were not collapsed.",
                    "For every inventory experiment, check all eight field groups: formulation, payload, biological model, recipient cell, therapeutic target, assay, endpoint, and outcome.",
                    "Recover explicit negative, qualitative, comparator, and cell-specific outcomes instead of silently omitting them.",
                    "Preserve every human-approved inventory experiment under its exact experiment_id whenever source support exists.",
                    "For every candidate outcome clause that explicitly reports an LNP-linked result, create each distinct supported endpoint/outcome relation; explanation without a graph claim is allowed only when the clause is not an LNP-experiment outcome or lacks an experiment link.",
                    "Return exact evidence quotes only.",
                ],
                "schema": VerifiedEvidenceGraphV4.model_json_schema(),
            }
            verified_path = paper_dir / "verified_graph.json"
            if verified_path.exists() and not force:
                verified = VerifiedEvidenceGraphV4.model_validate_json(verified_path.read_text())
            else:
                if provider == "openai":
                    verifier_response, verified = call_openai_structured(
                        client,
                        verifier_model,
                        "You are an independent biomedical verifier.",
                        verifier_payload,
                        VerifiedEvidenceGraphV4,
                    )
                    (paper_dir / "verifier.response.json").write_text(
                        verifier_response.model_dump_json(indent=2, warnings=False) + "\n"
                    )
                else:
                    verifier_response = call_sensenova_json(
                        client,
                        verifier_model,
                        "You are an independent biomedical verifier. Return valid JSON only.",
                        verifier_payload,
                        24000,
                    )
                    verifier_raw = response_envelope(verifier_response)
                    (paper_dir / "verifier.response.json").write_text(json.dumps(verifier_raw, indent=2) + "\n")
                    verified = VerifiedEvidenceGraphV4.model_validate_json(verifier_raw["content"] or "")
                verified_path.write_text(verified.model_dump_json(indent=2) + "\n")
            final_graph = repair_non_verbatim_quotes(
                verified.corrected_graph, clauses
            )
            verified = verified.model_copy(
                update={"corrected_graph": final_graph}
            )
            verified_path.write_text(verified.model_dump_json(indent=2) + "\n")
            final_findings = audit_rag_graph(final_graph, clauses, provenance, inventory)
            final_graph, pruned_claim_ids = prune_unsupported_relations(
                final_graph, final_findings
            )
            if pruned_claim_ids:
                final_findings = audit_rag_graph(final_graph, clauses, provenance, inventory)
            post_repair_observations = 0
            if final_findings:
                post_path = paper_dir / "post_audit_repair.json"
                if post_path.exists() and not force:
                    post_repair = VerifiedEvidenceGraphV4.model_validate_json(post_path.read_text())
                else:
                    post_payload = {
                        "paper_id": paper_id,
                        "source_clauses": [row.model_dump() for row in clauses],
                        "human_approved_experiment_inventory": inventory.get("experiments", []),
                        "graph_requiring_final_correction": final_graph.model_dump(mode="json"),
                        "remaining_deterministic_findings": final_findings,
                        "outcome_candidate_clauses_requiring_disposition": outcome_candidates,
                        "atomic_result_candidates_requiring_disposition": [
                            row.model_dump(mode="json") for row in candidate_sidecar.candidates
                        ],
                        "tasks": [
                            "Apply every deterministic finding to corrected_graph.",
                            "Use an intervention or LNP formulation—not a biological model—as the subject of route, dose, assay, and timepoint claims.",
                            "For every relation, ensure the claim and both linked entities cite at least one common clause.",
                            "If co-support cannot be established from an exact source quote, remove the relation.",
                            "Do not add inferred facts or merge experiments.",
                            "Return the complete corrected graph.",
                            "Restore every missing human-approved inventory experiment using its exact experiment_id when the supplied clauses support it.",
                            "For every candidate outcome clause that explicitly reports an LNP-linked result, add each distinct supported cell/value/qualitative result; exclude it only when it is not an LNP-experiment outcome or lacks an experiment link.",
                        ],
                        "schema": VerifiedEvidenceGraphV4.model_json_schema(),
                    }
                    if provider == "openai":
                        repair_response, post_repair = call_openai_structured(
                            client,
                            verifier_model,
                            "You are a final biomedical graph repairer.",
                            post_payload,
                            VerifiedEvidenceGraphV4,
                        )
                        (paper_dir / "post_audit_repair.response.json").write_text(
                            repair_response.model_dump_json(indent=2, warnings=False) + "\n"
                        )
                    else:
                        repair_response = call_sensenova_json(
                            client,
                            verifier_model,
                            "You are a final biomedical graph repairer. Return valid JSON only.",
                            post_payload,
                            24000,
                        )
                        repair_raw = response_envelope(repair_response)
                        (paper_dir / "post_audit_repair.response.json").write_text(
                            json.dumps(repair_raw, indent=2) + "\n"
                        )
                        post_repair = VerifiedEvidenceGraphV4.model_validate_json(
                            repair_raw["content"] or ""
                        )
                    post_path.write_text(post_repair.model_dump_json(indent=2) + "\n")
                final_graph = repair_non_verbatim_quotes(
                    post_repair.corrected_graph, clauses
                )
                post_repair = post_repair.model_copy(
                    update={"corrected_graph": final_graph}
                )
                post_path.write_text(post_repair.model_dump_json(indent=2) + "\n")
                post_repair_observations = len(post_repair.observations)
                final_findings = audit_rag_graph(final_graph, clauses, provenance, inventory)
            final_graph, post_repair_pruned_claim_ids = prune_unsupported_relations(
                final_graph, final_findings
            )
            pruned_claim_ids = sorted(
                set(pruned_claim_ids + post_repair_pruned_claim_ids)
            )
            if post_repair_pruned_claim_ids:
                (paper_dir / "deterministic_prune.json").write_text(json.dumps({
                    "rule": "Remove relations proven unsupported or schema-invalid by deterministic validation.",
                    "removed_claim_ids": pruned_claim_ids,
                }, indent=2) + "\n")
                final_findings = audit_rag_graph(
                    final_graph, clauses, provenance, inventory
                )
            elif pruned_claim_ids:
                (paper_dir / "deterministic_prune.json").write_text(json.dumps({
                    "rule": "Remove relations proven unsupported or schema-invalid by deterministic validation.",
                    "removed_claim_ids": pruned_claim_ids,
                }, indent=2) + "\n")
            (paper_dir / "final_audit.json").write_text(json.dumps(final_findings, indent=2) + "\n")
            if final_findings:
                status = "needs_repair"
            else:
                accepted_path.write_text(final_graph.model_dump_json(indent=2) + "\n")
                status = "accepted"
            manifest["papers"].append({
                "paper_id": paper_id,
                "status": status,
                "experiments": len(final_graph.experiments),
                "claims": len(final_graph.claims),
                "unresolved_ambiguities": verified.unresolved_ambiguities,
                "post_repair_observations": post_repair_observations,
                "deterministically_pruned_claim_ids": pruned_claim_ids,
                "final_audit_findings": len(final_findings),
            })
        except Exception as error:
            (paper_dir / "error.txt").write_text(f"{type(error).__name__}: {error}\n")
            manifest["papers"].append({
                "paper_id": paper_id,
                "status": "error",
                "error_type": type(error).__name__,
                "error": str(error),
            })
            break
    (output_root / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--packets-root", type=Path, default=PACKETS)
    parser.add_argument("--output-root", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(
        set(args.paper_id),
        force=args.force,
        packets_root=args.packets_root,
        output_root=args.output_root,
    ), indent=2))
