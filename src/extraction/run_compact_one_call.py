"""Run exactly one compact OpenAI extraction request for human review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema
from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.compact_validation import validate_candidate
from src.extraction.v12_main_route import (
    allowed_v12_evidence_ids,
    build_v12_route_support,
    evaluate_v12_result_coverage,
    evaluate_v12_structural_result_coverage,
)
from src.extraction.assess_outcome_complexity import assess
from src.extraction.build_outcome_candidates import build_candidates
from src.extraction.check_outcome_coverage import check
from src.extraction.compact_prompt_v1 import (
    COMPACT_EXTRACTION_PROMPT,
    PROMPT_VERSION,
    prompt_sha256,
)
from src.rag.compact_api_packet import CompactApiPacket


ROOT = Path(__file__).resolve().parents[2]
PACKET_ROOT = ROOT / "data" / "staging" / "rag" / "compact_api_packets_v1"
OUTPUT_ROOT = (
    ROOT / "data" / "staging" / "extraction" / "compact_one_call_v1_2"
)
SCHEMA_PATH = (
    ROOT
    / "docs"
    / "extraction"
    / "schemas"
    / "compact_v1"
    / "compact_extraction_response.schema.json"
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def load_packet(paper_id: str, packet_root: Path = PACKET_ROOT) -> CompactApiPacket:
    packet_path = packet_root / f"{paper_id}.json"
    packet = CompactApiPacket.model_validate_json(packet_path.read_text(encoding="utf-8"))
    unsigned = packet.model_dump(mode="json", exclude={"packet_checksum"}, exclude_none=True)
    actual_checksum = _sha256(_canonical_json(unsigned))
    if actual_checksum != packet.packet_checksum:
        raise ValueError(
            f"Packet checksum mismatch for {paper_id}: "
            f"expected {packet.packet_checksum}, calculated {actual_checksum}"
        )
    return packet


def request_fingerprint(
    packet: CompactApiPacket,
    model: str,
    recall_support: dict[str, Any] | None = None,
) -> str:
    return _sha256(
        _canonical_json(
            {
                "paper_id": packet.paper_id,
                "packet_checksum": packet.packet_checksum,
                "prompt_version": PROMPT_VERSION,
                "prompt_checksum": prompt_sha256(),
                "schema_checksum": _sha256(SCHEMA_PATH.read_bytes()),
                "model": model,
                "recall_support_checksum": (
                    _sha256(_canonical_json(recall_support))
                    if recall_support
                    else None
                ),
            }
        )
    )


def build_openai_request(
    packet: CompactApiPacket,
    *,
    model: str,
    max_output_tokens: int = 12_000,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    """Build the exact request dictionary shared by preflight and generation."""

    packet_payload = packet.model_dump(mode="json", exclude_none=True)
    recall_support = build_v12_route_support(packet)
    user_payload = {
        "evidence_packet": packet_payload,
        "outcome_recall_support": recall_support,
    }
    fingerprint = request_fingerprint(packet, model, recall_support)
    api_request = {
        "model": model,
        "reasoning": {"effort": "low"},
        "store": False,
        "service_tier": "default",
        "max_output_tokens": max_output_tokens,
        "prompt_cache_key": fingerprint,
        "input": [
            {"role": "system", "content": COMPACT_EXTRACTION_PROMPT},
            {"role": "user", "content": _canonical_json(user_payload)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "CompactExtractionResponse",
                "schema": to_strict_json_schema(CompactExtractionResponse),
                "strict": True,
            }
        },
    }
    return api_request, recall_support, user_payload, fingerprint


def _refusals(response: Any) -> list[str]:
    return [
        item.refusal
        for output in response.output
        if output.type == "message"
        for item in output.content
        if item.type == "refusal"
    ]


def run_one(
    paper_id: str,
    *,
    model: str,
    client: OpenAI,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = OUTPUT_ROOT,
    max_output_tokens: int = 12_000,
) -> dict[str, Any]:
    """Make one paid request and persist its request, response, result, and usage."""
    packet = load_packet(paper_id, packet_root)
    run_dir = output_root / paper_id
    result_path = run_dir / "result.json"
    raw_response_path = run_dir / "response.json"
    if result_path.exists() or raw_response_path.exists():
        raise FileExistsError(
            f"A completed response already exists for {paper_id}; refusing a duplicate paid call."
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    complexity = assess(packet)
    (run_dir / "complexity.json").write_text(
        complexity.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    outcome_candidates = None
    if complexity.route == "complex":
        outcome_candidates = build_candidates(packet)
        (run_dir / "outcome_candidates.json").write_text(
            json.dumps(
                [row.model_dump(mode="json") for row in outcome_candidates],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    (
        api_request,
        recall_support,
        user_payload,
        fingerprint,
    ) = build_openai_request(
        packet,
        model=model,
        max_output_tokens=max_output_tokens,
    )
    request_snapshot = {
        "paper_id": paper_id,
        "model": model,
        "reasoning_effort": "low",
        "store": False,
        "service_tier": "default",
        "max_output_tokens": max_output_tokens,
        "prompt_version": PROMPT_VERSION,
        "prompt_checksum": prompt_sha256(),
        "schema_checksum": _sha256(SCHEMA_PATH.read_bytes()),
        "packet_checksum": packet.packet_checksum,
        "recall_support_version": recall_support["support_version"],
        "recall_support_estimated_tokens": recall_support["estimated_tokens"],
        "request_fingerprint": fingerprint,
        "system_prompt": COMPACT_EXTRACTION_PROMPT,
        "request_payload": user_payload,
        "api_request": api_request,
    }
    (run_dir / "request.json").write_text(
        json.dumps(request_snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    started_at = datetime.now(timezone.utc)
    response = client.responses.create(**api_request)
    completed_at = datetime.now(timezone.utc)

    raw_response_path.write_text(
        json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not response.output_text:
        detail = "; ".join(_refusals(response)) or "no parsed output"
        raise RuntimeError(f"OpenAI structured extraction failed: {detail}")
    candidate_path = run_dir / "candidate.json"
    candidate_path.write_text(response.output_text + "\n", encoding="utf-8")
    parsed, validation_report = validate_candidate(
        response.output_text,
        paper_id=paper_id,
        allowed_evidence_ids=(
            {row.evidence_id for row in packet.evidence}
            | allowed_v12_evidence_ids(recall_support)
        ),
    )
    (run_dir / "validation_report.json").write_text(
        validation_report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    if parsed is None:
        raise ValueError(
            f"Compact candidate failed {len(validation_report.findings)} "
            "deterministic validation check(s); see validation_report.json"
        )

    result_path.write_text(
        json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    v12_coverage = evaluate_v12_result_coverage(
        recall_support,
        parsed.model_dump(mode="json"),
    )
    (run_dir / "v12_outcome_coverage.json").write_text(
        json.dumps(v12_coverage, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    v12_structural_coverage = evaluate_v12_structural_result_coverage(
        recall_support,
        parsed.model_dump(mode="json"),
    )
    (run_dir / "v12_structural_coverage.json").write_text(
        json.dumps(v12_structural_coverage, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    coverage = None
    if complexity.route == "complex":
        coverage = check(
            packet,
            parsed.model_dump(mode="json"),
            assessment=complexity,
            candidates=outcome_candidates,
        )
        (run_dir / "outcome_coverage.json").write_text(
            coverage.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    needs_coverage_review = bool(
        (coverage and coverage.status == "review_unmatched_groups")
        or v12_coverage["status"] == "review_unmatched_support"
        or v12_structural_coverage["status"]
        == "review_unconfirmed_or_contradicted_facts"
    )
    manifest = {
        "status": (
            "completed_pending_outcome_coverage_review"
            if needs_coverage_review
            else "completed_pending_human_verification"
        ),
        "paper_id": paper_id,
        "paid_api_requests": 1,
        "model_requested": model,
        "model_returned": response.model,
        "response_id": response.id,
        "request_fingerprint": fingerprint,
        "packet_checksum": packet.packet_checksum,
        "prompt_version": PROMPT_VERSION,
        "prompt_checksum": prompt_sha256(),
        "schema_checksum": _sha256(SCHEMA_PATH.read_bytes()),
        "recall_support_version": recall_support["support_version"],
        "recall_support_estimated_tokens": recall_support["estimated_tokens"],
        "recall_support_record_counts": {
            "provisional_experiments": len(
                recall_support["provisional_experiments"]
            ),
            "atomic_outcome_candidates": len(
                recall_support["atomic_outcome_candidates"]
            ),
            "accepted_visual_claims": len(
                recall_support["accepted_visual_claims"]
            ),
            "local_evidence": len(recall_support["local_evidence"]),
        },
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_seconds": (completed_at - started_at).total_seconds(),
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
        "eligibility": parsed.eligibility.model_dump(mode="json"),
        "record_counts": {
            "formulations": len(parsed.formulations),
            "components": len(parsed.components),
            "experiments": len(parsed.experiments),
            "outcomes": len(parsed.outcomes),
            "unresolved_items": len(parsed.unresolved_items),
        },
        "checks": {
            "structured_output_valid": True,
            "paper_id_matches": True,
            "all_evidence_ids_exist_in_packet": True,
            "validation_report_status": validation_report.status,
            "narrative_requested": False,
            "complexity_route": complexity.route,
            "outcome_coverage_status": (
                coverage.status if coverage else "ordinary_validation_only"
            ),
            "v12_outcome_coverage_status": v12_coverage["status"],
            "v12_structural_coverage_status": (
                v12_structural_coverage["status"]
            ),
            "v12_structural_coverage_counts": (
                v12_structural_coverage["counts"]
            ),
            "v12_structural_coverage_routes": (
                v12_structural_coverage["routes"]
            ),
            "v12_recall_support_in_request": True,
        },
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send exactly one compact paper packet to OpenAI."
    )
    parser.add_argument("--paper-id", required=True)
    parser.add_argument(
        "--packet-root",
        type=Path,
        default=PACKET_ROOT,
        help="Directory containing <paper_id>.json compact API packets.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
        help="Separate directory for request, response, result, and validation files.",
    )
    parser.add_argument(
        "--confirm-paid-call",
        action="store_true",
        help="Required guard acknowledging that exactly one paid API request may be made.",
    )
    args = parser.parse_args()
    if not args.confirm_paid_call:
        parser.error("--confirm-paid-call is required")

    load_dotenv(ROOT / ".env")
    model = os.getenv("COMPACT_EXTRACTION_MODEL", "gpt-5.6-terra")
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=300.0,
        max_retries=0,
    )
    manifest = run_one(
        args.paper_id,
        model=model,
        client=client,
        packet_root=args.packet_root,
        output_root=args.output_root,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
