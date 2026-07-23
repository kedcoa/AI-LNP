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


PACKETS = ROOT / "data" / "staging" / "rag" / "retrieval_packets"
BOUNDARIES = ROOT / "data" / "staging" / "extraction" / "g1_v3_frozen_boundaries"
OUTPUT = ROOT / "data" / "staging" / "extraction" / "g1_fulltext_rag"


def call_json(
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


def clauses_from_packet(
    packet_payload: dict[str, Any],
    *,
    hits_per_field: int = 4,
    max_characters: int = 30_000,
) -> tuple[list[SourceClauseV4], dict[str, dict]]:
    unique: dict[str, dict] = {}
    for packet in packet_payload["packets"].values():
        for hit in packet["hits"][:hits_per_field]:
            unique.setdefault(hit["block_id"], hit)
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
            }
    return clauses, provenance


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
            "Distinguish uptake, delivery, expression/transfection, and therapeutic effect.",
            "Healthy/homeostasis is physiological_state, not disease.",
            "HSC must retain the meaning supported in this paper; never assume hepatic stellate cells.",
            "If retrieved evidence is insufficient for a field, omit the claim rather than infer it.",
        ],
        "schema": EvidenceGraphV4.model_json_schema(),
    }


def run(paper_ids: set[str], *, force: bool = False) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    extractor_model = os.getenv("RAG_EXTRACTION_MODEL", "deepseek-v4-flash")
    verifier_model = os.getenv("RAG_VERIFIER_MODEL", "glm-5.2")
    client = OpenAI(
        api_key=os.environ["SENSENOVA_API_KEY"],
        base_url=os.getenv("SENSENOVA_BASE_URL", "https://token.sensenova.cn/v1"),
        timeout=240.0,
        max_retries=1,
    )
    papers = {row["paper_id"]: row for row in gold_inputs()}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "models": {"extractor": extractor_model, "verifier": verifier_model},
        "source_scope": "full_text_with_supplement",
        "papers": [],
    }
    for paper_id in sorted(paper_ids):
        paper_dir = OUTPUT / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)
        accepted_path = paper_dir / "accepted_graph.json"
        if accepted_path.exists() and not force:
            manifest["papers"].append({"paper_id": paper_id, "status": "cached_accepted"})
            continue
        packet_payload = json.loads((PACKETS / f"{paper_id}.json").read_text())
        if packet_payload["blocked_fields"]:
            manifest["papers"].append({
                "paper_id": paper_id,
                "status": "retrieval_gate_blocked",
                "blocked_fields": packet_payload["blocked_fields"],
            })
            continue
        clauses, provenance = clauses_from_packet(packet_payload)
        inventory_path = BOUNDARIES / f"{paper_id}.json"
        inventory = json.loads(inventory_path.read_text()) if inventory_path.exists() else {"experiments": []}
        (paper_dir / "source_clauses.json").write_text(
            json.dumps([row.model_dump() for row in clauses], indent=2) + "\n"
        )
        (paper_dir / "clause_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        try:
            extractor_response = call_json(
                client,
                extractor_model,
                "You are a conservative biomedical full-text claim-graph extractor. Return valid JSON only.",
                extraction_payload(papers[paper_id], clauses, inventory),
                24000,
            )
            raw = response_envelope(extractor_response)
            (paper_dir / "extractor.response.json").write_text(json.dumps(raw, indent=2) + "\n")
            draft = EvidenceGraphV4.model_validate_json(raw["content"] or "")
            (paper_dir / "draft_graph.json").write_text(draft.model_dump_json(indent=2) + "\n")
            findings = audit_graph(draft, clauses)
            (paper_dir / "draft_audit.json").write_text(json.dumps(findings, indent=2) + "\n")

            verifier_payload = {
                "paper_id": paper_id,
                "source_clauses": [row.model_dump() for row in clauses],
                "human_approved_experiment_inventory": inventory.get("experiments", []),
                "first_graph": draft.model_dump(mode="json"),
                "deterministic_findings": findings,
                "tasks": [
                    "Read every source clause independently a second time.",
                    "Apply all corrections to corrected_graph, not merely observations.",
                    "Add supported omissions and remove unsupported claims.",
                    "Check every experiment boundary and prevent context leakage.",
                    "Check delivery recipient versus therapeutic target cells explicitly.",
                    "Check that separate endpoints and outcome values were not collapsed.",
                    "Return exact evidence quotes only.",
                ],
                "schema": VerifiedEvidenceGraphV4.model_json_schema(),
            }
            verifier_response = call_json(
                client,
                verifier_model,
                "You are an independent biomedical verifier. Return valid JSON only.",
                verifier_payload,
                24000,
            )
            verifier_raw = response_envelope(verifier_response)
            (paper_dir / "verifier.response.json").write_text(json.dumps(verifier_raw, indent=2) + "\n")
            verified = VerifiedEvidenceGraphV4.model_validate_json(verifier_raw["content"] or "")
            (paper_dir / "verified_graph.json").write_text(verified.model_dump_json(indent=2) + "\n")
            final_findings = audit_graph(verified.corrected_graph, clauses)
            (paper_dir / "final_audit.json").write_text(json.dumps(final_findings, indent=2) + "\n")
            if final_findings:
                status = "needs_repair"
            else:
                accepted_path.write_text(verified.corrected_graph.model_dump_json(indent=2) + "\n")
                status = "accepted"
            manifest["papers"].append({
                "paper_id": paper_id,
                "status": status,
                "experiments": len(verified.corrected_graph.experiments),
                "claims": len(verified.corrected_graph.claims),
                "unresolved_ambiguities": verified.unresolved_ambiguities,
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
    (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(set(args.paper_id), force=args.force), indent=2))
