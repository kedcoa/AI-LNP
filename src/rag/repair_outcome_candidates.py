"""Focused, additive repair of omitted result candidates in accepted v4 graphs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from src.extraction.contracts_v4 import EvidenceGraphV4
from src.extraction.outcome_contracts_v41 import OutcomeSidecarV41, apply_graph_patch
from src.extraction.run_abstract_first import ROOT
from src.rag.result_candidates import validate_sidecar_against_graph
from src.rag.run_experiment_extraction import (
    audit_rag_graph,
    call_openai_structured,
    clauses_from_packet,
    provider_configuration,
)


def repair(
    paper_id: str,
    graph_path: Path,
    packet_path: Path,
    candidate_ids: list[str],
    output_dir: Path,
) -> EvidenceGraphV4:
    load_dotenv(ROOT / ".env")
    provider, _, verifier_model, client = provider_configuration()
    if provider != "openai":
        raise RuntimeError("focused v4.1 repair currently requires OpenAI structured output")
    graph = EvidenceGraphV4.model_validate_json(graph_path.read_text())
    packet = json.loads(packet_path.read_text())
    clauses, provenance = clauses_from_packet(packet, max_characters=100_000)
    from src.rag.result_candidates import split_result_candidates
    selected = [row for row in split_result_candidates(clauses) if row.candidate_id in candidate_ids]
    missing = set(candidate_ids) - {row.candidate_id for row in selected}
    if missing:
        raise ValueError(f"candidate IDs not found: {sorted(missing)}")
    selected_blocks = {provenance[row.clause_id]["block_id"] for row in selected}
    context_clauses = [
        row for row in clauses
        if provenance.get(row.clause_id, {}).get("block_id") in selected_blocks
    ]
    payload = {
        "paper_id": paper_id,
        "existing_graph": graph.model_dump(mode="json"),
        "selected_atomic_result_candidates": [row.model_dump(mode="json") for row in selected],
        "same_block_source_context": [row.model_dump(mode="json") for row in context_clauses],
        "task": "Return the smallest additive patch that represents every selected result candidate.",
        "rules": [
            "Never delete or rewrite existing graph content.",
            "Use exact contiguous evidence quotes only.",
            "Every retained candidate must map to a newly added has_outcome_value claim.",
            "Add a separate endpoint and outcome_value entity for each semantically distinct result.",
            "Add a same-block assay entity as the subject of measures_endpoint when existing graph subjects lack evidence in the candidate's source block.",
            "Add every newly cited candidate clause to the linked experiment's source_scope_clause_ids through experiment_claim_additions.",
            "Preserve negative, below-detection, qualitative, population-specific, and comparative meaning in reported_name.",
            "Link claims to the exact existing experiment; never invent an experiment.",
            "Use an existing or newly evidenced assay/intervention/formulation as measures_endpoint subject.",
            "For mechanisms, record ordered delivery, effector, and therapeutic-target steps without claiming direct LNP delivery to the therapeutic target.",
            "If a candidate is unsupported or not an LNP experiment result, give it a non-retained disposition and add no outcome claim.",
        ],
    }
    response, patch = call_openai_structured(
        client, verifier_model,
        "You are a conservative biomedical graph patcher. Return a minimal validated additive patch.",
        payload,
        __import__("src.extraction.outcome_contracts_v41", fromlist=["GraphPatchV41"]).GraphPatchV41,
    )
    updated = apply_graph_patch(graph, patch)
    sidecar = OutcomeSidecarV41(
        paper_id=paper_id,
        candidates=selected,
        dispositions=patch.dispositions,
        mechanism_steps=patch.mechanism_steps,
    )
    sidecar_findings = validate_sidecar_against_graph(sidecar, updated)
    graph_findings = audit_rag_graph(updated, clauses, provenance)
    if sidecar_findings or graph_findings:
        raise ValueError(json.dumps({
            "sidecar_findings": sidecar_findings,
            "graph_findings": graph_findings,
        }))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "accepted_graph.json").write_text(updated.model_dump_json(indent=2) + "\n")
    (output_dir / "outcome_sidecar.v4.1.json").write_text(sidecar.model_dump_json(indent=2) + "\n")
    (output_dir / "graph_patch.v4.1.json").write_text(patch.model_dump_json(indent=2) + "\n")
    (output_dir / "repair.response.json").write_text(
        response.model_dump_json(indent=2, warnings=False) + "\n"
    )
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--graph-path", type=Path, required=True)
    parser.add_argument("--packet-path", type=Path, required=True)
    parser.add_argument("--candidate-id", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repaired = repair(
        args.paper_id, args.graph_path, args.packet_path, args.candidate_id, args.output_dir
    )
    print(json.dumps({"paper_id": repaired.paper_id, "claims": len(repaired.claims)}, indent=2))
