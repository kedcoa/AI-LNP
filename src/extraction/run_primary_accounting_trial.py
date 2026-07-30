"""NP-001-only, explicitly approved primary-candidate accounting trial.

This is deliberately a sibling of the production compact runner, not a mode
or flag on it.  It performs no repair or vision calls and makes at most one
provider request after a signed local preflight is approved by request SHA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv
from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema

from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.compact_prompt_v1 import (
    COMPACT_EXTRACTION_PROMPT,
    PROMPT_VERSION,
    prompt_sha256,
)
from src.extraction.primary_candidate_accounting import (
    ACCOUNTING_CONTRACT_VERSION,
    DISPOSITIONS,
    TRIAL_ROUTE,
    TRIAL_ROUTE_VERSION,
    build_candidate_accounting_schema,
    parse_accounting_response,
)
from src.extraction.run_compact_one_call import PACKET_ROOT, load_packet
from src.extraction.v12_main_route import (
    allowed_v12_evidence_ids,
    build_v12_route_support,
)
from src.rag.compact_api_packet import estimate_tokens


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_OUTPUT_ROOT = (
    ROOT
    / "data/staging/extraction/np001_primary_accounting_trial_preflight"
)
RUN_OUTPUT_ROOT = (
    ROOT / "data/staging/extraction/np001_primary_accounting_trial_run"
)
TRIAL_PREFLIGHT_VERSION = "compact-primary-accounting-preflight-1.0.0"
CORE_CONTRACT_VERSION = "compact-1.1.0"
TRIAL_MAX_OUTPUT_TOKENS = 12_000
TRIAL_PAPER_ID = "NP-001"

_ACCOUNTING_INSTRUCTIONS = (
    "For every supplied candidate fact, fill exactly one candidate_accounting "
    "entry. extracted means the candidate is directly supported by a returned "
    "outcome; duplicate means the same fact is represented by a linked returned "
    "outcome; not_outcome means it is context, method, or malformed rather than "
    "an outcome; insufficient_evidence means the supplied evidence does not "
    "support an outcome; requires_visual means a visual value is needed and is "
    "not available as text; ambiguous means the evidence conflicts or assignment "
    "is uncertain. Use only supplied evidence IDs and only the permitted "
    "dispositions and reason codes."
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _require_trial_paper(paper_id: str) -> None:
    if paper_id != TRIAL_PAPER_ID:
        raise ValueError("primary candidate accounting trial accepts only NP-001")


def _trial_prompt() -> str:
    return f"{COMPACT_EXTRACTION_PROMPT} {_ACCOUNTING_INSTRUCTIONS}"


def _candidate_facts(support: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = support.get("atomic_outcome_candidates")
    if not isinstance(candidates, list):
        raise ValueError("trial recall support must contain atomic outcome candidates")
    if len(candidates) != 36:
        raise ValueError("NP-001 trial requires exactly 36 ordered atomic candidates")
    if not all(isinstance(row, dict) for row in candidates):
        raise ValueError("trial atomic outcome candidates must be JSON objects")
    return candidates


def _request_fingerprint(
    *,
    packet_checksum: str,
    model: str,
    candidate_facts_sha256: str,
    dynamic_schema_sha256: str,
    recall_support_sha256: str,
) -> str:
    return _sha256(
        _canonical_json(
            {
                "paper_id": TRIAL_PAPER_ID,
                "packet_checksum": packet_checksum,
                "model": model,
                "route": TRIAL_ROUTE,
                "route_version": TRIAL_ROUTE_VERSION,
                "core_contract_version": CORE_CONTRACT_VERSION,
                "accounting_contract_version": ACCOUNTING_CONTRACT_VERSION,
                "prompt_version": PROMPT_VERSION,
                "prompt_checksum": prompt_sha256(),
                "candidate_facts_sha256": candidate_facts_sha256,
                "dynamic_schema_sha256": dynamic_schema_sha256,
                "recall_support_sha256": recall_support_sha256,
            }
        )
    )


def build_trial_request(
    packet: Any,
    *,
    model: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build the trial request and immutable bindings without provider access."""

    _require_trial_paper(packet.paper_id)
    recall_support = build_v12_route_support(packet)
    candidate_facts = _candidate_facts(recall_support)
    dynamic_schema = build_candidate_accounting_schema(
        to_strict_json_schema(CompactExtractionResponse), candidate_facts
    )
    candidate_facts_sha256 = _sha256(_canonical_json(candidate_facts))
    dynamic_schema_sha256 = _sha256(_canonical_json(dynamic_schema))
    recall_support_sha256 = _sha256(_canonical_json(recall_support))
    fingerprint = _request_fingerprint(
        packet_checksum=packet.packet_checksum,
        model=model,
        candidate_facts_sha256=candidate_facts_sha256,
        dynamic_schema_sha256=dynamic_schema_sha256,
        recall_support_sha256=recall_support_sha256,
    )
    payload = {
        "evidence_packet": packet.model_dump(mode="json", exclude_none=True),
        "outcome_recall_support": recall_support,
        "candidate_facts": candidate_facts,
    }
    request = {
        "model": model,
        "reasoning": {"effort": "low"},
        "store": False,
        "service_tier": "default",
        "max_output_tokens": TRIAL_MAX_OUTPUT_TOKENS,
        "prompt_cache_key": fingerprint,
        "input": [
            {"role": "system", "content": _trial_prompt()},
            {"role": "user", "content": _canonical_json(payload)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "PrimaryCandidateAccountingTrialResponse",
                "schema": dynamic_schema,
                "strict": True,
            }
        },
    }
    return request, recall_support, payload, {
        "route": TRIAL_ROUTE,
        "route_version": TRIAL_ROUTE_VERSION,
        "core_contract_version": CORE_CONTRACT_VERSION,
        "request_fingerprint": fingerprint,
        "candidate_facts_sha256": candidate_facts_sha256,
        "dynamic_schema_sha256": dynamic_schema_sha256,
        "recall_support_sha256": recall_support_sha256,
        "dynamic_schema": dynamic_schema,
    }


def _candidate_inventory(
    candidates: list[dict[str, Any]], candidate_facts_sha256: str
) -> dict[str, Any]:
    candidate_ids = [str(candidate.get("candidate_id", "")) for candidate in candidates]
    if any(not candidate_id for candidate_id in candidate_ids):
        raise ValueError("trial candidate inventory contains an empty candidate ID")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("trial candidate inventory contains duplicate candidate IDs")
    return {
        "raw_candidate_count": len(candidate_ids),
        "raw_candidate_ids": candidate_ids,
        "quarantined_candidate_count": 0,
        "quarantined_candidate_ids": [],
        "sent_candidate_count": len(candidate_ids),
        "sent_candidate_ids": candidate_ids,
        "ordered_sent_candidate_facts_sha256": candidate_facts_sha256,
    }


def _schema_audit(
    schema: Mapping[str, Any], sent_candidate_ids: list[str]
) -> dict[str, Any]:
    accounting = schema.get("properties", {}).get("candidate_accounting", {})
    candidate_properties = accounting.get("properties", {})
    return {
        "root_is_object": schema.get("type") == "object",
        "accounting_contract_version": schema.get("properties", {})
        .get("accounting_contract_version", {})
        .get("const"),
        "candidate_count": len(candidate_properties),
        "candidate_ids_are_ordered": list(candidate_properties)
        == sent_candidate_ids,
        "accounting_is_closed": accounting.get("additionalProperties") is False,
        "all_candidates_required": schema.get("required", [])[-2:]
        == ["accounting_contract_version", "candidate_accounting"],
    }


def _evidence_audit(packet: Any, support: Mapping[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    allowed = {row.evidence_id for row in packet.evidence} | allowed_v12_evidence_ids(dict(support))
    referenced = {
        evidence_id
        for candidate in candidates
        for evidence_id in candidate.get("evidence_ids", [])
    }
    return {
        "candidate_evidence_ids": len(referenced),
        "unknown_candidate_evidence_ids": sorted(referenced - allowed),
        "all_candidate_evidence_ids_resolve": referenced <= allowed,
    }


def preflight_trial_request(
    paper_id: str,
    *,
    model: str,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = PREFLIGHT_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Write a reviewable exact request and signed bindings, with zero provider calls."""

    _require_trial_paper(paper_id)
    packet = load_packet(paper_id, packet_root)
    request, support, payload, bindings = build_trial_request(packet, model=model)
    candidate_inventory = _candidate_inventory(
        payload["candidate_facts"], bindings["candidate_facts_sha256"]
    )
    schema_audit = _schema_audit(
        bindings["dynamic_schema"], candidate_inventory["sent_candidate_ids"]
    )
    evidence_audit = _evidence_audit(packet, support, payload["candidate_facts"])
    if not all(
        (
            schema_audit["root_is_object"],
            schema_audit["candidate_count"] == 36,
            schema_audit["candidate_ids_are_ordered"],
            schema_audit["accounting_is_closed"],
            schema_audit["all_candidates_required"],
            evidence_audit["all_candidate_evidence_ids_resolve"],
        )
    ):
        raise ValueError("NP-001 trial preflight audit failed")

    paper_root = (output_root / paper_id).resolve()
    paper_root.mkdir(parents=True, exist_ok=True)
    request_path = paper_root / "request.json"
    request_bytes = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    request_path.write_bytes(request_bytes)
    audits = {
        "schema": schema_audit,
        "evidence": evidence_audit,
        "candidate_inventory": candidate_inventory,
    }
    (paper_root / "audits.json").write_text(
        json.dumps(audits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    request_sha256 = _sha256(request_bytes)
    preview = "\n".join(
        [
            "NP-001 primary candidate accounting trial preflight",
            f"Request path: {request_path}",
            f"Request SHA-256: {request_sha256}",
            f"Estimated input tokens: {estimate_tokens(request)}",
            f"Output cap: {TRIAL_MAX_OUTPUT_TOKENS}",
            "Candidates: 36",
            "Proposed paid calls: 1",
        ]
    )
    (paper_root / "preview.txt").write_text(preview + "\n", encoding="utf-8")
    unsigned_manifest = {
        "preflight_version": TRIAL_PREFLIGHT_VERSION,
        "route": TRIAL_ROUTE,
        "route_version": TRIAL_ROUTE_VERSION,
        "core_contract_version": CORE_CONTRACT_VERSION,
        "accounting_contract_version": ACCOUNTING_CONTRACT_VERSION,
        "status": "passed",
        "human_approval_required": True,
        "request_path": str(request_path),
        "request_sha256": request_sha256,
        "paper_id": paper_id,
        "model": model,
        "packet_checksum": packet.packet_checksum,
        "candidate_facts_sha256": bindings["candidate_facts_sha256"],
        "dynamic_schema_sha256": bindings["dynamic_schema_sha256"],
        "recall_support_sha256": bindings["recall_support_sha256"],
        "request_fingerprint": bindings["request_fingerprint"],
        "request_bytes": len(request_bytes),
        "estimated_input_tokens": estimate_tokens(request),
        "max_output_tokens": TRIAL_MAX_OUTPUT_TOKENS,
        "candidate_count": 36,
        "candidate_inventory": candidate_inventory,
        "provider_calls": 0,
        "audits_path": str(paper_root / "audits.json"),
        "preview_path": str(paper_root / "preview.txt"),
    }
    manifest = {
        **unsigned_manifest,
        "manifest_checksum": _sha256(_canonical_json(unsigned_manifest)),
    }
    (paper_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _load_approved_request(
    *,
    paper_id: str,
    model: str,
    packet: Any,
    manifest_path: Path,
    approved_request_sha256: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not approved_request_sha256:
        raise PermissionError("an approved request SHA-256 is required for this paid call")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("trial manifest is unavailable or invalid") from exc
    if not isinstance(manifest, dict):
        raise ValueError("trial manifest must be a JSON object")
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_checksum"}
    if manifest.get("manifest_checksum") != _sha256(_canonical_json(unsigned_manifest)):
        raise ValueError("trial manifest checksum is invalid")
    required = {
        "preflight_version": TRIAL_PREFLIGHT_VERSION,
        "route": TRIAL_ROUTE,
        "route_version": TRIAL_ROUTE_VERSION,
        "core_contract_version": CORE_CONTRACT_VERSION,
        "accounting_contract_version": ACCOUNTING_CONTRACT_VERSION,
        "status": "passed",
        "human_approval_required": True,
        "paper_id": paper_id,
        "model": model,
        "packet_checksum": packet.packet_checksum,
        "max_output_tokens": TRIAL_MAX_OUTPUT_TOKENS,
        "candidate_count": 36,
        "provider_calls": 0,
    }
    if any(manifest.get(key) != value for key, value in required.items()):
        raise ValueError("trial manifest does not bind the current approved NP-001 request")
    if manifest.get("request_sha256") != approved_request_sha256:
        raise ValueError("approved request SHA-256 does not match trial manifest")
    request_path = Path(str(manifest.get("request_path", "")))
    if not request_path.is_absolute():
        raise ValueError("trial manifest request path must be absolute")
    try:
        request_bytes = request_path.read_bytes()
    except OSError as exc:
        raise ValueError("approved trial request bytes are unavailable") from exc
    if _sha256(request_bytes) != approved_request_sha256:
        raise ValueError("approved trial request bytes do not match the approval SHA-256")
    if manifest.get("request_bytes") != len(request_bytes):
        raise ValueError("approved trial request bytes do not match manifest")
    try:
        request = json.loads(request_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("approved trial request bytes are not valid JSON") from exc
    expected, support, payload, bindings = build_trial_request(packet, model=model)
    if request != expected:
        raise ValueError("approved trial request dictionary does not match current trial inputs")
    for key in (
        "candidate_facts_sha256",
        "dynamic_schema_sha256",
        "recall_support_sha256",
        "request_fingerprint",
    ):
        if manifest.get(key) != bindings[key]:
            raise ValueError(f"trial manifest {key} does not match current trial inputs")
    expected_inventory = _candidate_inventory(
        payload["candidate_facts"], bindings["candidate_facts_sha256"]
    )
    if manifest.get("candidate_inventory") != expected_inventory:
        raise ValueError(
            "trial manifest candidate inventory does not match current trial inputs"
        )
    if payload["candidate_facts"] != support["atomic_outcome_candidates"]:
        raise ValueError("trial request candidate facts are not the ordered recall inventory")
    return request, support, manifest


def run_approved_trial(
    paper_id: str,
    *,
    model: str,
    client: OpenAI,
    manifest_path: Path,
    approved_request_sha256: str | None,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = RUN_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Invoke the provider once, only for an exact preflight-approved request."""

    _require_trial_paper(paper_id)
    run_dir = output_root / paper_id
    invocation_path = run_dir / "invocation_started.json"
    if invocation_path.exists():
        raise FileExistsError(
            "An NP-001 trial invocation already started; refusing duplicate paid call"
        )
    if (run_dir / "manifest.json").exists() or (run_dir / "response.json").exists():
        raise FileExistsError(
            "A completed NP-001 trial already exists; refusing duplicate paid call"
        )
    packet = load_packet(paper_id, packet_root)
    request, support, preflight_manifest = _load_approved_request(
        paper_id=paper_id,
        model=model,
        packet=packet,
        manifest_path=manifest_path,
        approved_request_sha256=approved_request_sha256,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    approved_request_bytes = Path(preflight_manifest["request_path"]).read_bytes()
    (run_dir / "request.json").write_bytes(approved_request_bytes)
    invocation = {
        "status": "invocation_started",
        "paper_id": paper_id,
        "route": TRIAL_ROUTE,
        "route_version": TRIAL_ROUTE_VERSION,
        "model": model,
        "approved_request_sha256": approved_request_sha256,
        "preflight_manifest_path": str(manifest_path.resolve()),
        "started_at": started_at.isoformat(),
    }
    try:
        with invocation_path.open("x", encoding="utf-8") as marker:
            marker.write(json.dumps(invocation, ensure_ascii=False, indent=2) + "\n")
            marker.flush()
            os.fsync(marker.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            "An NP-001 trial invocation already started; refusing duplicate paid call"
        ) from exc
    response = client.responses.create(**request)
    completed_at = datetime.now(timezone.utc)
    (run_dir / "response.json").write_text(
        json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not response.output_text:
        raise RuntimeError("approved trial provider response did not contain structured output")
    (run_dir / "candidate.json").write_text(response.output_text + "\n", encoding="utf-8")
    try:
        trial_response = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise ValueError("approved trial provider response is not valid JSON") from exc
    evidence_envelope = [
        *[row.model_dump(mode="json") for row in packet.evidence],
        *support.get("local_evidence", []),
    ]
    parsed, accounting_report = parse_accounting_response(
        trial_response, support["atomic_outcome_candidates"], evidence_envelope
    )
    (run_dir / "trial_response.json").write_text(
        json.dumps(trial_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "result.json").write_text(
        json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "accounting_report.json").write_text(
        json.dumps(accounting_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "status": "completed_pending_human_review",
        "paper_id": paper_id,
        "route": TRIAL_ROUTE,
        "route_version": TRIAL_ROUTE_VERSION,
        "core_contract_version": CORE_CONTRACT_VERSION,
        "accounting_contract_version": ACCOUNTING_CONTRACT_VERSION,
        "paid_api_requests": 1,
        "repair_calls": 0,
        "vision_calls": 0,
        "candidate_count": 36,
        "model_requested": model,
        "model_returned": response.model,
        "response_id": response.id,
        "approved_request_sha256": approved_request_sha256,
        "preflight_manifest_path": str(manifest_path.resolve()),
        "packet_checksum": packet.packet_checksum,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_seconds": (completed_at - started_at).total_seconds(),
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
        "accounting_errors": len(accounting_report["errors"]),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="NP-001 guarded candidate accounting trial")
    subparsers = parser.add_subparsers(dest="command")
    preflight_parser = subparsers.add_parser("preflight")
    approved_parser = subparsers.add_parser("run-approved")
    for subparser in (preflight_parser, approved_parser):
        subparser.add_argument("--paper-id", required=True)
        subparser.add_argument("--packet-root", type=Path, default=PACKET_ROOT)
    preflight_parser.add_argument(
        "--output-root", type=Path, default=PREFLIGHT_OUTPUT_ROOT
    )
    approved_parser.add_argument(
        "--output-root", type=Path, default=RUN_OUTPUT_ROOT
    )
    preflight_parser.add_argument("--model", default="gpt-5.6-terra")
    approved_parser.add_argument("--model", default="gpt-5.6-terra")
    approved_parser.add_argument("--manifest", type=Path, required=True)
    approved_parser.add_argument("--approved-request-sha256", required=True)
    argv = sys.argv[1:]
    if argv and argv[0] not in {"preflight", "run-approved", "-h", "--help"}:
        argv = ["preflight", *argv]
    args = parser.parse_args(argv)
    command = args.command or "preflight"
    if command == "preflight":
        print(json.dumps(preflight_trial_request(args.paper_id, model=args.model, packet_root=args.packet_root, output_root=args.output_root), ensure_ascii=False, indent=2))
        return
    load_dotenv(ROOT / ".env")
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=300.0,
        max_retries=0,
    )
    print(json.dumps(run_approved_trial(args.paper_id, model=args.model, client=client, manifest_path=args.manifest, approved_request_sha256=args.approved_request_sha256, packet_root=args.packet_root, output_root=args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
