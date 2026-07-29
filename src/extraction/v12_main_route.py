"""Build the v1.2 recall-support envelope used by the main extractor.

Candidates are evidence navigation aids, not final records.  The envelope is
gold-blind and includes the evidence text needed to validate candidate claims
that the original token budget omitted.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.rag.compact_api_packet import CompactApiPacket, estimate_tokens
from src.rag.compact_packet import CompactEvidencePacket

from .build_provisional_experiments import _payload_signature
from .v12_structure_contracts import (
    AtomicOutcomeCandidateV12,
    ProvisionalExperimentInventoryV12,
)
from .check_atomic_coverage_v12 import _matches
from .deterministic_coverage_v12 import evaluate_structural_coverage


ROOT = Path(__file__).resolve().parents[2]
ATOMIC_ROOT = ROOT / "data/staging/extraction/v12_atomic_inventory"
COVERAGE_ROOT = ROOT / "data/staging/extraction/v12_atomic_coverage"
EXPERIMENT_ROOT = ROOT / "data/staging/extraction/v12_provisional_experiments"
FULL_PACKET_ROOT = ROOT / "data/staging/rag/compact_packets_v1"
DOCLING_CANDIDATE_ROOT = (
    ROOT / "data/staging/extraction/v12_docling_candidates"
)
DOCLING_OBJECT_ROOT = ROOT / "data/staging/extraction/v12_docling_visual"
ACCEPTED_VISUAL_REGISTRY = (
    ROOT
    / "data/staging/extraction/v12_accepted_visual_claims"
    / "qwen3-vl-8b-instruct-thinking-off.json"
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _text_candidates(paper_id: str) -> list[AtomicOutcomeCandidateV12]:
    candidate_path = ATOMIC_ROOT / paper_id / "selected_candidates.json"
    if not candidate_path.exists():
        return []
    return [
        AtomicOutcomeCandidateV12.model_validate(row)
        for row in _load_json(candidate_path)
    ]


def _docling_candidates(paper_id: str) -> list[AtomicOutcomeCandidateV12]:
    candidates: list[AtomicOutcomeCandidateV12] = []
    for path in sorted(DOCLING_CANDIDATE_ROOT.glob("*/candidates.json")):
        candidates.extend(
            candidate
            for candidate in (
                AtomicOutcomeCandidateV12.model_validate(row)
                for row in _load_json(path)
            )
            if candidate.paper_id == paper_id
        )
    return candidates


def _accepted_visual_claims(paper_id: str) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    if not ACCEPTED_VISUAL_REGISTRY.exists():
        return accepted
    registry = _load_json(ACCEPTED_VISUAL_REGISTRY)
    if not registry.get("benchmark_gate_passed"):
        return accepted
    for row in registry.get("claims", []):
        object_path = (
            DOCLING_OBJECT_ROOT / row["object_id"] / "docling_object.json"
        )
        if not object_path.exists():
            continue
        parsed = _load_json(object_path)
        if parsed.get("paper_id") == paper_id:
            accepted.append(row)
    return accepted


def _visual_predicate(text: str) -> tuple[str, str | None]:
    """Map only explicitly supported visual relations into the atomic schema."""

    if re.search(r"\b(?:co-?stain|co-?locali[sz])", text, re.I):
        match = re.search(r"\bwith\s+(.+)$", text, re.I)
        return "colocalized_with", match.group(1).strip() if match else None
    if re.search(r"\bexpress", text, re.I):
        return "expressed", None
    if re.search(r"\b(?:eliminat|kill|cytotoxic)", text, re.I):
        return "eliminated", None
    return "associated_with", None


def _visual_experiment(
    paper_id: str,
    claim: dict[str, Any],
) -> tuple[str | None, list[str]]:
    """Join a gated visual claim to a unique experiment from factual anchors."""

    path = EXPERIMENT_ROOT / paper_id / "inventory.json"
    if not path.exists():
        return None, ["visual_experiment_inventory_missing"]
    inventory = ProvisionalExperimentInventoryV12.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    claim_text = " ".join(
        str(value)
        for value in (
            claim.get("subject"),
            claim.get("predicate"),
            claim.get("endpoint"),
            claim.get("value"),
            claim.get("intervention_context"),
        )
        if value
    )
    payload = _payload_signature(claim_text)
    if payload is None:
        return None, ["visual_payload_unresolved"]
    matches = [
        row.provisional_experiment_id
        for row in inventory.experiments
        if payload
        in {
            anchor.value
            for anchor in row.anchors
            if anchor.anchor_type == "payload"
        }
    ]
    if len(matches) != 1:
        return None, [
            (
                "visual_experiment_ambiguous"
                if matches
                else "visual_experiment_unmatched"
            )
        ]
    return matches[0], []


def _visual_candidates(
    paper_id: str,
    visual_claims: list[dict[str, Any]],
) -> list[AtomicOutcomeCandidateV12]:
    """Turn accepted visual claims into facts that structural coverage can grade."""

    candidates: list[AtomicOutcomeCandidateV12] = []
    for row in visual_claims:
        claim = row["claim"]
        predicate, object_text = _visual_predicate(
            str(claim.get("predicate", ""))
        )
        experiment_id, review_reasons = _visual_experiment(paper_id, claim)
        if predicate == "associated_with":
            review_reasons.append("visual_predicate_not_safely_mapped")
        if claim.get("confidence") != "high":
            review_reasons.append("visual_claim_not_high_confidence")
        endpoint = claim.get("endpoint")
        if predicate == "colocalized_with" and not endpoint:
            endpoint = "ZsGreen colocalization"
        signature_parts = [
            paper_id,
            experiment_id or "UNASSIGNED",
            str(claim.get("claim_id", "")),
            str(claim.get("subject", "")),
            predicate,
            str(object_text or ""),
            str(endpoint or ""),
            str(claim.get("value", "")),
            str(row["evidence_id"]),
        ]
        signature = json.dumps(
            signature_parts,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
        candidates.append(
            AtomicOutcomeCandidateV12(
                candidate_id=f"AOC-VIS-{digest}",
                paper_id=paper_id,
                claim_ids=[claim["claim_id"]],
                provisional_experiment_id=experiment_id,
                subject_text=claim["subject"],
                predicate=predicate,
                object_text=object_text,
                endpoint_text=endpoint,
                qualitative_result=claim.get("value"),
                value_text=claim.get("value"),
                unit=claim.get("unit"),
                polarity="positive",
                evidence_ids=[row["evidence_id"]],
                source_ids=[row["object_id"]],
                route_hint="vision",
                confidence="medium" if review_reasons else "high",
                review_reasons=review_reasons,
                structural_signature=signature,
            )
        )
    return candidates


def _full_evidence(paper_id: str) -> dict[str, Any]:
    path = FULL_PACKET_ROOT / f"{paper_id}.json"
    if not path.exists():
        return {}
    packet = CompactEvidencePacket.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    return {row.evidence_id: row for row in packet.evidence}


def _atomic_claim_evidence(paper_id: str) -> dict[str, dict[str, Any]]:
    path = ATOMIC_ROOT / paper_id / "claims.json"
    if not path.exists():
        return {}
    evidence: dict[str, dict[str, Any]] = {}
    for claim in _load_json(path):
        for row in claim.get("evidence", []):
            evidence_id = row["evidence_id"]
            if evidence_id not in evidence:
                evidence[evidence_id] = {
                    **row,
                    "quotes": [row["quote"]],
                }
            elif row["quote"] not in evidence[evidence_id]["quotes"]:
                evidence[evidence_id]["quotes"].append(row["quote"])
    return evidence


def _experiment_payload(
    paper_id: str, experiment_ids: set[str]
) -> list[dict[str, Any]]:
    path = EXPERIMENT_ROOT / paper_id / "inventory.json"
    if not path.exists():
        return []
    inventory = ProvisionalExperimentInventoryV12.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    return [
        {
            "provisional_experiment_id": row.provisional_experiment_id,
            "label": row.label,
            "anchors": [
                {
                    "anchor_type": anchor.anchor_type,
                    "value": anchor.value,
                    "evidence_ids": anchor.evidence_ids,
                }
                for anchor in row.anchors
            ],
            "boundary_status": row.boundary_status,
            "boundary_reason": row.boundary_reason,
            "confidence": row.confidence,
        }
        for row in inventory.experiments
        if row.provisional_experiment_id in experiment_ids
    ]


def build_v12_route_support(
    packet: CompactApiPacket,
) -> dict[str, Any]:
    paper_id = packet.paper_id
    text_candidates = _text_candidates(paper_id)
    table_candidates = _docling_candidates(paper_id)
    visual_claims = _accepted_visual_claims(paper_id)
    visual_candidates = _visual_candidates(paper_id, visual_claims)
    atomic_candidates = [
        *text_candidates,
        *table_candidates,
        *visual_candidates,
    ]
    experiment_ids = {
        row.provisional_experiment_id
        for row in atomic_candidates
        if row.provisional_experiment_id
    }

    packet_evidence_ids = {row.evidence_id for row in packet.evidence}
    full_evidence = _full_evidence(paper_id)
    claim_evidence = _atomic_claim_evidence(paper_id)
    local_evidence: dict[str, dict[str, Any]] = {}
    for candidate in text_candidates:
        for evidence_id in candidate.evidence_ids:
            if evidence_id in packet_evidence_ids or evidence_id in local_evidence:
                continue
            source = full_evidence.get(evidence_id)
            claim_source = claim_evidence.get(evidence_id)
            if source is None and claim_source is None:
                raise ValueError(
                    f"{candidate.candidate_id} references unavailable evidence "
                    f"{evidence_id}"
                )
            local_evidence[evidence_id] = {
                "evidence_id": evidence_id,
                "text": (
                    source.text
                    if source is not None
                    else "\n".join(claim_source["quotes"])
                ),
                "source_ids": [
                    (
                        claim_source["source_id"]
                        if claim_source is not None
                        else source_id
                    )
                    for source_id in candidate.source_ids
                ],
                "source_kind": "text",
                "provenance": (
                    [
                        row.model_dump(mode="json", exclude_none=True)
                        for row in source.source_locations
                    ]
                    if source is not None
                    else {
                        key: value
                        for key, value in claim_source.items()
                        if key not in {"quote", "quotes"}
                    }
                ),
            }
    for candidate in table_candidates:
        evidence_id = candidate.evidence_ids[0]
        local_evidence[evidence_id] = {
            "evidence_id": evidence_id,
            "text": (
                f"{candidate.subject_text} | {candidate.endpoint_text} | "
                f"{candidate.value_text}"
            ),
            "source_ids": candidate.source_ids,
            "source_kind": "docling_table_cell",
            "provenance": candidate.source_ids,
        }
    for row in visual_claims:
        local_evidence[row["evidence_id"]] = {
            "evidence_id": row["evidence_id"],
            "text": row["support_text"],
            "source_ids": [row["object_id"]],
            "source_kind": "gated_vlm_figure_region",
            "provenance": {
                "object_id": row["object_id"],
                "image_path": row["image_path"],
                "panel_or_cell": row["claim"]["panel_or_cell"],
            },
        }

    payload = {
        "support_version": "main-route-recall-support-1.2.0",
        "paper_id": paper_id,
        "instructions": [
            "Candidates are navigation aids, not verified final outcomes.",
            "Create a final record only when its cited evidence directly supports it.",
            "Keep distinct provisional experiments and atomic relationships separate.",
            "Deduplicate candidates against outcomes already supported by the packet.",
            "Use only evidence IDs present in the packet or local_evidence below.",
        ],
        "provisional_experiments": _experiment_payload(
            paper_id, experiment_ids
        ),
        "atomic_outcome_candidates": [
            row.model_dump(mode="json") for row in atomic_candidates
        ],
        "accepted_visual_claims": visual_claims,
        "local_evidence": list(local_evidence.values()),
    }
    payload["estimated_tokens"] = estimate_tokens(payload)
    return payload


def allowed_v12_evidence_ids(support: dict[str, Any]) -> set[str]:
    return {
        row["evidence_id"] for row in support.get("local_evidence", [])
    }


def _nested_evidence_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value.get("evidence_ids", []))
        for child in value.values():
            found |= _nested_evidence_ids(child)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found |= _nested_evidence_ids(child)
        return found
    return set()


def evaluate_v12_result_coverage(
    support: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Check the validated result against its gold-blind support envelope."""

    candidates = [
        AtomicOutcomeCandidateV12.model_validate(row)
        for row in support.get("atomic_outcome_candidates", [])
    ]
    outcomes = result.get("outcomes", [])
    matches = _matches(candidates, outcomes)
    matched_candidate_indexes = {row[0] for row in matches}
    visual_evidence_ids = {
        row["evidence_id"]
        for row in support.get("accepted_visual_claims", [])
    }
    used_evidence_ids = _nested_evidence_ids(outcomes)
    missing_visual = sorted(visual_evidence_ids - used_evidence_ids)
    missing_atomic = [
        candidate.candidate_id
        for index, candidate in enumerate(candidates)
        if index not in matched_candidate_indexes
    ]
    return {
        "coverage_version": "main-route-result-coverage-1.2.0",
        "paper_id": support["paper_id"],
        "status": (
            "complete"
            if not missing_atomic and not missing_visual
            else "review_unmatched_support"
        ),
        "atomic_candidate_matches": [
            {
                "candidate_id": candidates[candidate_index].candidate_id,
                "outcome_id": outcomes[outcome_index].get("outcome_id"),
                "score": score,
                "reasons": reasons,
            }
            for candidate_index, outcome_index, score, reasons in matches
        ],
        "missing_atomic_candidate_ids": missing_atomic,
        "missing_accepted_visual_evidence_ids": missing_visual,
        "paid_api_requests": 0,
    }


def evaluate_v12_structural_result_coverage(
    support: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Grade candidate coverage from facts, never model-authored labels."""

    report = evaluate_structural_coverage(
        candidates=[
            AtomicOutcomeCandidateV12.model_validate(row)
            for row in support.get("atomic_outcome_candidates", [])
        ],
        provisional_experiments=support.get("provisional_experiments", []),
        result=result,
    )
    return {
        **report,
        "paper_id": support["paper_id"],
        "status": (
            "complete"
            if not report["routes"]["bounded_repair_task"]
            and not report["routes"]["human_review"]
            else "review_unconfirmed_or_contradicted_facts"
        ),
    }
