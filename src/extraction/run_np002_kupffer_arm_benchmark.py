"""Prepare and execute the guarded NP-002 Kupffer-arm benchmark."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema
from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.compact_prompt_v1 import (
    COMPACT_EXTRACTION_PROMPT,
    PROMPT_VERSION,
    prompt_sha256,
)
from src.extraction.experimental_arms import (
    ARM_PROPOSAL_VERSION,
    ARM_REVIEW_VERSION,
    build_experimental_arm_schema,
    build_np002_kupffer_arm_proposal,
    validate_experimental_arm_response,
    validate_arm_review,
)
from src.extraction.run_compact_one_call import load_packet
from src.rag.compact_api_packet import estimate_tokens


ROOT = Path(__file__).resolve().parents[2]
REVIEW_OUTPUT_ROOT = (
    ROOT
    / "data"
    / "staging"
    / "extraction"
    / "np002_kupffer_arm_benchmark_review"
)
PREFLIGHT_OUTPUT_ROOT = (
    ROOT
    / "data"
    / "staging"
    / "extraction"
    / "np002_kupffer_arm_benchmark_preflight"
)
PREFLIGHT_VERSION = "np002-kupffer-arm-benchmark-preflight-1.0.0"
RUN_OUTPUT_ROOT = (
    ROOT
    / "data"
    / "staging"
    / "extraction"
    / "np002_kupffer_arm_benchmark_run"
)
BENCHMARK_ROUTE = "np002-kupffer-arm-benchmark"
BENCHMARK_ROUTE_VERSION = "np002-kupffer-arm-benchmark-1.0.0"
MAX_OUTPUT_TOKENS = 12_000
_ARM_INSTRUCTIONS = (
    "Every experimental-arm candidate must be independently interpreted. "
    "Copying one outcome to incompatible dose/payload arms is forbidden."
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


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _review_markdown(proposal: dict[str, Any]) -> str:
    evidence = {
        row["evidence_id"]: row["text"]
        for row in proposal["packet_evidence"]
    }
    lines = [
        "# NP-002 Kupffer-cell experimental-arm review",
        "",
        "All decisions are pending human review.",
        "",
    ]
    for arm in proposal["proposed_arms"]:
        lines.extend(
            [
                f"## {arm['candidate_id']}",
                "",
                (
                    f"{arm['formulation']} / {arm['payload']} / "
                    f"{arm['dose']} {arm['dose_unit']} / "
                    f"{arm['target_cell']}"
                ),
                "",
                "**Decision:** pending",
                "",
                "**Evidence:**",
                "",
            ]
        )
        for evidence_id in dict.fromkeys(
            arm["existence_evidence_ids"] + arm["outcome_evidence_ids"]
        ):
            lines.append(f"- `{evidence_id}` — {evidence[evidence_id]}")
        lines.append("")
    return "\n".join(lines)


def prepare_arm_review(
    paper_id: str,
    *,
    packet_root: Path,
    output_root: Path = REVIEW_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Build a local-only proposal and pending human-review packet."""

    if paper_id != "NP-002":
        raise ValueError("Kupffer arm review preparation accepts only NP-002")
    packet = load_packet(paper_id, packet_root)
    proposal = build_np002_kupffer_arm_proposal(
        packet.model_dump(mode="json", exclude_none=True)
    )
    unsigned_review = {
        "review_version": ARM_REVIEW_VERSION,
        "paper_id": paper_id,
        "proposal_sha256": proposal["proposal_sha256"],
        "decisions": [
            {
                "candidate_id": arm["candidate_id"],
                "decision": "pending",
                "reason": "",
            }
            for arm in proposal["proposed_arms"]
        ],
        "corrections": [],
        "additions": [],
    }
    review = {
        **unsigned_review,
        "review_sha256": _sha256(_canonical_json(unsigned_review)),
    }
    destination = output_root / paper_id
    destination.mkdir(parents=True, exist_ok=True)
    proposal_path = destination / "proposal.json"
    review_path = destination / "review_template.json"
    markdown_path = destination / "experimental_arms_review.md"
    _write_json(proposal_path, proposal)
    _write_json(review_path, review)
    markdown_path.write_text(_review_markdown(proposal), encoding="utf-8")
    return {
        "paper_id": paper_id,
        "proposal_path": str(proposal_path.resolve()),
        "review_path": str(review_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "proposal_sha256": proposal["proposal_sha256"],
        "review_sha256": review["review_sha256"],
        "proposed_arm_count": len(proposal["proposed_arms"]),
        "provider_calls": 0,
    }


def _load_signed_review(
    review_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
        proposal = json.loads(
            review_path.with_name("proposal.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("proposal or review JSON is unavailable or invalid") from exc
    if not isinstance(review, dict):
        raise ValueError("review must be a JSON object")
    unsigned_review = {
        key: value for key, value in review.items() if key != "review_sha256"
    }
    if review.get("review_sha256") != _sha256(
        _canonical_json(unsigned_review)
    ):
        raise ValueError("review SHA-256 does not match the review content")
    validation = validate_arm_review(proposal, review)
    return proposal, review, validation


def _build_benchmark_request(
    packet: Any,
    *,
    model: str,
    approved_arms: list[dict[str, Any]],
    proposal_sha256: str,
    review_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = build_experimental_arm_schema(
        to_strict_json_schema(CompactExtractionResponse),
        approved_arms,
    )
    evidence_by_id = {
        row.evidence_id: row.model_dump(mode="json", exclude_none=True)
        for row in packet.evidence
    }
    arm_packets = []
    for arm in approved_arms:
        evidence_ids = list(
            dict.fromkeys(
                arm["existence_evidence_ids"] + arm["outcome_evidence_ids"]
            )
        )
        arm_packets.append(
            {
                "arm": arm,
                "evidence": [evidence_by_id[item] for item in evidence_ids],
            }
        )
    payload = {
        "paper_id": packet.paper_id,
        "experimental_arm_packets": arm_packets,
    }
    schema_sha256 = _sha256(_canonical_json(schema))
    arms_sha256 = _sha256(_canonical_json(approved_arms))
    fingerprint = _sha256(
        _canonical_json(
            {
                "paper_id": packet.paper_id,
                "packet_checksum": packet.packet_checksum,
                "model": model,
                "route": BENCHMARK_ROUTE,
                "route_version": BENCHMARK_ROUTE_VERSION,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": prompt_sha256(),
                "proposal_sha256": proposal_sha256,
                "review_sha256": review_sha256,
                "approved_arms_sha256": arms_sha256,
                "dynamic_schema_sha256": schema_sha256,
            }
        )
    )
    request = {
        "model": model,
        "reasoning": {"effort": "low"},
        "store": False,
        "service_tier": "default",
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "prompt_cache_key": fingerprint,
        "input": [
            {
                "role": "system",
                "content": f"{COMPACT_EXTRACTION_PROMPT} {_ARM_INSTRUCTIONS}",
            },
            {"role": "user", "content": _canonical_json(payload)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "KupfferArmBenchmarkResponse",
                "schema": schema,
                "strict": True,
            }
        },
    }
    return request, {
        "dynamic_schema_sha256": schema_sha256,
        "approved_arms_sha256": arms_sha256,
        "request_fingerprint": fingerprint,
    }


def preflight_kupffer_benchmark(
    paper_id: str,
    *,
    model: str,
    review_path: Path,
    packet_root: Path,
    output_root: Path = PREFLIGHT_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Persist an immutable, zero-call request for explicit approval."""

    if paper_id != "NP-002":
        raise ValueError("Kupffer arm benchmark accepts only NP-002")
    packet = load_packet(paper_id, packet_root)
    proposal, review, validation = _load_signed_review(review_path)
    approved_arms = validation["approved_arms"]
    if len(approved_arms) != 6:
        raise ValueError("Kupffer benchmark requires exactly six approved arms")
    request, bindings = _build_benchmark_request(
        packet,
        model=model,
        approved_arms=approved_arms,
        proposal_sha256=proposal["proposal_sha256"],
        review_sha256=review["review_sha256"],
    )
    paper_root = (output_root / paper_id).resolve()
    paper_root.mkdir(parents=True, exist_ok=True)
    request_path = paper_root / "request.json"
    request_bytes = (
        json.dumps(request, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    request_path.write_bytes(request_bytes)
    request_sha256 = _sha256(request_bytes)
    preview_path = paper_root / "preview.txt"
    preview_path.write_text(
        "\n".join(
            (
                "NP-002 Kupffer experimental-arm benchmark preflight",
                f"Request SHA-256: {request_sha256}",
                f"Approved arms: {len(approved_arms)}",
                f"Estimated input tokens: {estimate_tokens(request)}",
                f"Output cap: {MAX_OUTPUT_TOKENS}",
                "Proposed calls: 1",
                "Provider calls: 0",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    unsigned_manifest = {
        "preflight_version": PREFLIGHT_VERSION,
        "route": BENCHMARK_ROUTE,
        "route_version": BENCHMARK_ROUTE_VERSION,
        "arm_proposal_version": ARM_PROPOSAL_VERSION,
        "arm_review_version": ARM_REVIEW_VERSION,
        "status": "passed",
        "human_approval_required": True,
        "paper_id": paper_id,
        "model": model,
        "packet_root": str(packet_root.resolve()),
        "packet_checksum": packet.packet_checksum,
        "proposal_path": str(review_path.with_name("proposal.json").resolve()),
        "proposal_sha256": proposal["proposal_sha256"],
        "review_path": str(review_path.resolve()),
        "review_sha256": review["review_sha256"],
        **bindings,
        "request_path": str(request_path),
        "request_sha256": request_sha256,
        "request_bytes": len(request_bytes),
        "approved_arm_ids": [
            arm["candidate_id"] for arm in approved_arms
        ],
        "estimated_input_tokens": estimate_tokens(request),
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "proposed_calls": 1,
        "provider_calls": 0,
        "preview_path": str(preview_path),
    }
    manifest = {
        **unsigned_manifest,
        "manifest_checksum": _sha256(_canonical_json(unsigned_manifest)),
    }
    _write_json(paper_root / "manifest.json", manifest)
    return manifest


def _read_preflight_manifest(
    manifest_path: Path,
    approval_sha256: str,
) -> dict[str, Any]:
    if not approval_sha256:
        raise PermissionError(
            "an approved request SHA-256 is required for this paid call"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("benchmark preflight manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise ValueError("benchmark preflight manifest must be an object")
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_checksum"
    }
    if manifest.get("manifest_checksum") != _sha256(
        _canonical_json(unsigned)
    ):
        raise ValueError("benchmark preflight manifest checksum is invalid")
    if manifest.get("preflight_version") != PREFLIGHT_VERSION:
        raise ValueError("benchmark preflight version is invalid")
    if manifest.get("paper_id") != "NP-002":
        raise ValueError("benchmark preflight must target NP-002")
    if manifest.get("status") != "passed":
        raise ValueError("benchmark preflight did not pass")
    if manifest.get("request_sha256") != approval_sha256:
        raise ValueError("approval SHA-256 does not match the preflight request")
    return manifest


def _approved_request(
    manifest: dict[str, Any],
    approval_sha256: str,
) -> tuple[bytes, dict[str, Any], Any, list[dict[str, Any]]]:
    request_path = Path(manifest["request_path"])
    try:
        request_bytes = request_path.read_bytes()
    except OSError as exc:
        raise ValueError("approved request bytes are unavailable") from exc
    if (
        _sha256(request_bytes) != approval_sha256
        or len(request_bytes) != manifest.get("request_bytes")
    ):
        raise ValueError("approved request bytes do not match the preflight")
    packet = load_packet("NP-002", Path(manifest["packet_root"]))
    if packet.packet_checksum != manifest.get("packet_checksum"):
        raise ValueError("packet checksum does not match the preflight")
    proposal, review, validation = _load_signed_review(
        Path(manifest["review_path"])
    )
    approved_arms = validation["approved_arms"]
    if len(approved_arms) != 6:
        raise ValueError("Kupffer benchmark requires exactly six approved arms")
    expected, bindings = _build_benchmark_request(
        packet,
        model=manifest["model"],
        approved_arms=approved_arms,
        proposal_sha256=proposal["proposal_sha256"],
        review_sha256=review["review_sha256"],
    )
    if proposal["proposal_sha256"] != manifest.get("proposal_sha256"):
        raise ValueError("proposal SHA-256 does not match the preflight")
    if review["review_sha256"] != manifest.get("review_sha256"):
        raise ValueError("review SHA-256 does not match the preflight")
    for key in (
        "dynamic_schema_sha256",
        "approved_arms_sha256",
        "request_fingerprint",
    ):
        if bindings[key] != manifest.get(key):
            raise ValueError(f"{key} does not match the preflight")
    try:
        request = json.loads(request_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("approved request bytes are not valid JSON") from exc
    if request != expected:
        raise ValueError("approved request bytes do not match the rebuilt request")
    return request_bytes, request, packet, approved_arms


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _artifact(path: Path, value: Any) -> tuple[bytes, str]:
    data = (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    path.write_bytes(data)
    return data, _sha256(data)


def run_approved_kupffer_benchmark(
    *,
    manifest_path: Path,
    approval_sha256: str,
    output_root: Path = RUN_OUTPUT_ROOT,
    client: Any | None = None,
) -> dict[str, Any]:
    """Dispatch the exact approved request once, with no retries or repairs."""

    run_dir = output_root / "NP-002"
    invocation_path = run_dir / "invocation_started.json"
    if invocation_path.exists() or (run_dir / "manifest.json").exists():
        raise FileExistsError(
            "A benchmark invocation already started; refusing duplicate"
        )
    preflight = _read_preflight_manifest(manifest_path, approval_sha256)
    _, expected_request, packet, approved_arms = _approved_request(
        preflight,
        approval_sha256,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    # Deliberately re-read after all reconstruction checks and immediately
    # before creating the durable invocation marker.
    final_request_bytes = Path(preflight["request_path"]).read_bytes()
    if _sha256(final_request_bytes) != approval_sha256:
        raise ValueError("approved request bytes changed before dispatch")
    try:
        final_request = json.loads(final_request_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("approved request bytes are not valid JSON") from exc
    if final_request != expected_request:
        raise ValueError("approved request bytes changed before dispatch")
    (run_dir / "request.json").write_bytes(final_request_bytes)
    started_at = datetime.now(timezone.utc)
    invocation = {
        "status": "invocation_started",
        "paper_id": "NP-002",
        "route": BENCHMARK_ROUTE,
        "model": preflight["model"],
        "approval_sha256": approval_sha256,
        "preflight_manifest_path": str(manifest_path.resolve()),
        "started_at": started_at.isoformat(),
    }
    try:
        with invocation_path.open("x", encoding="utf-8") as marker:
            marker.write(
                json.dumps(invocation, ensure_ascii=False, indent=2) + "\n"
            )
            marker.flush()
            os.fsync(marker.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            "A benchmark invocation already started; refusing duplicate"
        ) from exc
    _fsync_directory(run_dir)
    provider_client = client if client is not None else OpenAI(max_retries=0)
    response = provider_client.responses.create(**final_request)
    completed_at = datetime.now(timezone.utc)
    _, raw_response_sha256 = _artifact(
        run_dir / "response.json",
        response.model_dump(mode="json"),
    )
    if not response.output_text:
        raise RuntimeError("approved benchmark response has no structured output")
    try:
        trial_response = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise ValueError("approved benchmark response is not valid JSON") from exc
    _, trial_response_sha256 = _artifact(
        run_dir / "trial_response.json",
        trial_response,
    )
    compact_body = {
        key: value
        for key, value in trial_response.items()
        if key != "experimental_arm_accounting"
    }
    compact_result = CompactExtractionResponse.model_validate(compact_body)
    _, result_sha256 = _artifact(
        run_dir / "result.json",
        compact_result.model_dump(mode="json"),
    )
    payload = json.loads(final_request["input"][1]["content"])
    evidence_envelope = {
        row["evidence_id"]
        for arm_packet in payload["experimental_arm_packets"]
        for row in arm_packet["evidence"]
    }
    validation = validate_experimental_arm_response(
        trial_response,
        approved_arms,
        evidence_envelope,
    )
    _, validation_sha256 = _artifact(
        run_dir / "scientific_validation.json",
        validation,
    )
    usage = (
        response.usage.model_dump(mode="json")
        if getattr(response, "usage", None)
        else None
    )
    _, usage_sha256 = _artifact(run_dir / "usage.json", usage)
    result = {
        "status": "completed_pending_human_review",
        "paper_id": "NP-002",
        "route": BENCHMARK_ROUTE,
        "route_version": BENCHMARK_ROUTE_VERSION,
        "paid_api_requests": 1,
        "repair_calls": 0,
        "vision_calls": 0,
        "model_requested": preflight["model"],
        "model_returned": response.model,
        "response_id": response.id,
        "approval_sha256": approval_sha256,
        "request_sha256": _sha256(final_request_bytes),
        "raw_response_sha256": raw_response_sha256,
        "response_sha256": trial_response_sha256,
        "result_sha256": result_sha256,
        "validation_sha256": validation_sha256,
        "usage_sha256": usage_sha256,
        "preflight_manifest_path": str(manifest_path.resolve()),
        "packet_checksum": packet.packet_checksum,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_seconds": (completed_at - started_at).total_seconds(),
        "usage": usage,
        "scientifically_confirmed": validation["scientifically_confirmed"],
        "ambiguous": validation["ambiguous"],
        "validation_errors": len(validation["errors"]),
    }
    _write_json(run_dir / "manifest.json", result)
    return result
