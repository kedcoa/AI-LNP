"""NP-001-only guarded core-biological-slot extraction trial."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openai.lib._pydantic import to_strict_json_schema

from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.compact_prompt_v1 import (
    COMPACT_EXTRACTION_PROMPT,
    PROMPT_VERSION,
    prompt_sha256,
)
from src.extraction.core_biological_slots import (
    CORE_SLOT_CONTRACT_VERSION,
    build_core_slot_schema,
    build_np001_core_slots,
    validate_core_slot_response,
)
from src.extraction.run_compact_one_call import PACKET_ROOT, load_packet
from src.rag.compact_api_packet import estimate_tokens


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_OUTPUT_ROOT = (
    ROOT / "data/staging/extraction/np001_core_slot_trial_preflight"
)
RUN_OUTPUT_ROOT = ROOT / "data/staging/extraction/np001_core_slot_trial_run"
TRIAL_ROUTE = "primary-core-biological-slot-trial"
TRIAL_ROUTE_VERSION = "compact-route-1.4.0-trial"
TRIAL_PREFLIGHT_VERSION = "compact-core-slot-preflight-1.0.0"
TRIAL_MAX_OUTPUT_TOKENS = 12_000
TRIAL_PAPER_ID = "NP-001"

_CORE_SLOT_INSTRUCTIONS = (
    "Return exactly one core_slot_accounting entry for every supplied "
    "qualified core biological slot. Link only records and evidence IDs "
    "present in that slot's compact evidence packet."
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


def _require_trial_paper(paper_id: str) -> None:
    if paper_id != TRIAL_PAPER_ID:
        raise ValueError("core biological slot trial accepts only NP-001")


def _slot_packets(
    packet: Any,
    qualified_slots: list[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    evidence_by_id = {
        row.evidence_id: row.model_dump(mode="json", exclude_none=True)
        for row in packet.evidence
    }
    shared_ids = _select_shared_evidence_ids(
        evidence_by_id,
        qualified_slots,
    )
    packets = []
    selected_ids = list(shared_ids)
    for slot in qualified_slots:
        evidence_ids = _preferred_outcome_evidence_ids(
            evidence_by_id,
            slot,
        )
        selected_ids.extend(evidence_ids)
        packets.append(
            {
                "slot_id": slot["slot_id"],
                "model_family": slot["model_family"],
                "outcome_family": slot["outcome_family"],
                "evidence_ids": list(
                    dict.fromkeys((*shared_ids, *evidence_ids))
                ),
            }
        )
    selected_ids = list(dict.fromkeys(selected_ids))
    return (
        [evidence_by_id[value] for value in selected_ids],
        shared_ids,
        packets,
    )


def _text_has_term(text: str, term: str) -> bool:
    import re

    escaped = re.escape(term).replace(r"\ ", r"\s+")
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
            text,
            flags=re.IGNORECASE,
        )
    )


def _select_shared_evidence_ids(
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    qualified_slots: list[Mapping[str, Any]],
) -> list[str]:
    if not qualified_slots:
        return []
    first_slot = qualified_slots[0]
    formulation_candidates = [
        str(value) for value in first_slot["formulation_evidence_ids"]
    ]
    formulation_signature = first_slot.get("formulation_signature", {})
    expected_components = tuple(
        formulation_signature.get("composition_terms", [])
    )

    def formulation_score(evidence_id: str) -> tuple[int, int]:
        text = str(evidence_by_id[evidence_id]["text"])
        group_score = int(
            "dx_lnp" in formulation_signature.get("group_markers", [])
            and (
                (_text_has_term(text, "dx")
                 or _text_has_term(text, "dexamethasone"))
                and (
                    _text_has_term(text, "lnp")
                    or _text_has_term(text, "lnps")
                    or _text_has_term(text, "lipid nanoparticle")
                    or _text_has_term(text, "lipid nanoparticles")
                )
            )
        )
        component_score = sum(
            _text_has_term(text, term) for term in expected_components
        )
        return group_score * 100 + component_score, -len(text)

    selected_formulation = max(
        formulation_candidates,
        key=formulation_score,
    )
    outcome_text = " ".join(
        str(evidence_by_id[evidence_id]["text"])
        for slot in qualified_slots
        for evidence_id in slot["outcome_evidence_ids"]
    )
    payload_signature = first_slot.get("payload_signature", {})
    outcome_cargo_terms = [
        term
        for term in payload_signature.get("cargo_terms", [])
        if _text_has_term(outcome_text, term)
    ]

    def payload_score(evidence_id: str) -> tuple[int, int, int]:
        text = str(evidence_by_id[evidence_id]["text"])
        cargo_score = sum(
            _text_has_term(text, term) for term in outcome_cargo_terms
        )
        type_score = sum(
            _text_has_term(text, term)
            for term in payload_signature.get("type_terms", [])
        )
        return cargo_score, type_score, -len(text)

    payload_candidates = [
        str(value) for value in first_slot["payload_evidence_ids"]
    ]
    selected_payload = max(payload_candidates, key=payload_score)
    return list(dict.fromkeys((selected_formulation, selected_payload)))


def _preferred_outcome_evidence_ids(
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    slot: Mapping[str, Any],
) -> list[str]:
    candidates = [
        str(value) for value in slot["outcome_evidence_ids"]
    ]
    model_terms = {
        "hepg2": ("hepg2", "hep g2"),
        "dc2.4": ("dc2.4", "dc 2.4"),
        "hpbmc": ("hpbmc", "hpbmcs", "human pbmc"),
        "mouse_in_vivo": ("mouse", "mice", "murine"),
    }.get(str(slot["model_family"]), ())
    model_specific = [
        evidence_id
        for evidence_id in candidates
        if any(
            term.casefold()
            in str(evidence_by_id[evidence_id]["text"]).casefold()
            for term in model_terms
        )
    ]
    if model_specific:
        candidates = model_specific
    preferred_terms = {
        "transfection_expression": (
            "transfect",
            "reporter",
            "egfp",
            "gfp",
            "luciferase",
        ),
        "cytokine_immune": (
            "cytokine",
            "immune",
            "tnf",
            "il-",
            "mhc",
        ),
        "biodistribution_expression": (
            "biodistribution",
            "accumulation",
            "organ distribution",
            "tissue distribution",
        ),
    }.get(str(slot["outcome_family"]), ())
    preferred = [
        evidence_id
        for evidence_id in candidates
        if any(
            term.casefold()
            in str(evidence_by_id[evidence_id]["text"]).casefold()
            for term in preferred_terms
        )
    ]
    return preferred or candidates


def build_core_slot_trial_request(
    packet: Any,
    *,
    model: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Construct the provider request and all immutable local bindings."""

    _require_trial_paper(packet.paper_id)
    packet_payload = packet.model_dump(mode="json", exclude_none=True)
    qualification = build_np001_core_slots(packet_payload)
    qualified_slots = qualification["qualified_slots"]
    dynamic_schema = build_core_slot_schema(
        to_strict_json_schema(CompactExtractionResponse),
        qualified_slots,
    )
    qualification_sha256 = _sha256(_canonical_json(qualification))
    schema_sha256 = _sha256(_canonical_json(dynamic_schema))
    fingerprint = _sha256(
        _canonical_json(
            {
                "paper_id": packet.paper_id,
                "packet_checksum": packet.packet_checksum,
                "model": model,
                "route": TRIAL_ROUTE,
                "route_version": TRIAL_ROUTE_VERSION,
                "prompt_version": PROMPT_VERSION,
                "prompt_checksum": prompt_sha256(),
                "core_slot_contract_version": (
                    CORE_SLOT_CONTRACT_VERSION
                ),
                "slot_qualification_sha256": qualification_sha256,
                "dynamic_schema_sha256": schema_sha256,
            }
        )
    )
    evidence, shared_evidence_ids, slot_packets = _slot_packets(
        packet,
        qualified_slots,
    )
    payload = {
        "paper_id": packet.paper_id,
        "evidence": evidence,
        "shared_evidence_ids": shared_evidence_ids,
        "core_slot_packets": slot_packets,
    }
    request = {
        "model": model,
        "reasoning": {"effort": "low"},
        "store": False,
        "service_tier": "default",
        "max_output_tokens": TRIAL_MAX_OUTPUT_TOKENS,
        "prompt_cache_key": fingerprint,
        "input": [
            {
                "role": "system",
                "content": (
                    f"{COMPACT_EXTRACTION_PROMPT} "
                    f"{_CORE_SLOT_INSTRUCTIONS}"
                ),
            },
            {"role": "user", "content": _canonical_json(payload)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "CoreBiologicalSlotTrialResponse",
                "schema": dynamic_schema,
                "strict": True,
            }
        },
    }
    return request, qualification, {
        "dynamic_schema": dynamic_schema,
        "dynamic_schema_sha256": schema_sha256,
        "slot_qualification_sha256": qualification_sha256,
        "request_fingerprint": fingerprint,
    }


def preflight_core_slot_trial(
    paper_id: str,
    *,
    model: str,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = PREFLIGHT_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Persist a zero-provider-call exact request for human approval."""

    _require_trial_paper(paper_id)
    packet = load_packet(paper_id, packet_root)
    request, qualification, bindings = build_core_slot_trial_request(
        packet,
        model=model,
    )
    paper_root = (output_root / paper_id).resolve()
    paper_root.mkdir(parents=True, exist_ok=True)
    request_path = paper_root / "request.json"
    request_bytes = (
        json.dumps(request, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    request_path.write_bytes(request_bytes)
    qualification_path = paper_root / "slot_qualification.json"
    qualification_path.write_text(
        json.dumps(qualification, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    qualified_ids = [
        row["slot_id"] for row in qualification["qualified_slots"]
    ]
    excluded_ids = [
        row["slot_id"]
        for row in qualification["evaluated_slots"]
        if not row["qualified"]
    ]
    request_sha256 = _sha256(request_bytes)
    estimated_input_tokens = estimate_tokens(request)
    preview = "\n".join(
        (
            "NP-001 core biological slot trial preflight",
            f"Request path: {request_path}",
            f"Request SHA-256: {request_sha256}",
            f"Qualified slots: {', '.join(qualified_ids) or '(none)'}",
            f"Excluded slots: {', '.join(excluded_ids) or '(none)'}",
            f"Estimated input tokens: {estimated_input_tokens}",
            f"Output cap: {TRIAL_MAX_OUTPUT_TOKENS}",
            "Proposed calls: 1",
            "Provider calls: 0",
        )
    )
    preview_path = paper_root / "preview.txt"
    preview_path.write_text(preview + "\n", encoding="utf-8")
    unsigned_manifest = {
        "preflight_version": TRIAL_PREFLIGHT_VERSION,
        "route": TRIAL_ROUTE,
        "route_version": TRIAL_ROUTE_VERSION,
        "core_slot_contract_version": CORE_SLOT_CONTRACT_VERSION,
        "status": "passed",
        "human_approval_required": True,
        "paper_id": paper_id,
        "model": model,
        "packet_checksum": packet.packet_checksum,
        "slot_qualification_sha256": bindings[
            "slot_qualification_sha256"
        ],
        "dynamic_schema_sha256": bindings["dynamic_schema_sha256"],
        "request_fingerprint": bindings["request_fingerprint"],
        "request_path": str(request_path),
        "request_sha256": request_sha256,
        "request_bytes": len(request_bytes),
        "qualified_slot_ids": qualified_ids,
        "excluded_slot_ids": excluded_ids,
        "estimated_input_tokens": estimated_input_tokens,
        "max_output_tokens": TRIAL_MAX_OUTPUT_TOKENS,
        "proposed_calls": 1,
        "provider_calls": 0,
        "qualification_path": str(qualification_path),
        "preview_path": str(preview_path),
    }
    manifest = {
        **unsigned_manifest,
        "manifest_checksum": _sha256(_canonical_json(unsigned_manifest)),
    }
    (paper_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
        raise PermissionError(
            "an approved request SHA-256 is required for this paid call"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "core slot trial manifest is unavailable or invalid"
        ) from exc
    if not isinstance(manifest, dict):
        raise ValueError("core slot trial manifest must be a JSON object")
    unsigned_manifest = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_checksum"
    }
    if manifest.get("manifest_checksum") != _sha256(
        _canonical_json(unsigned_manifest)
    ):
        raise ValueError("core slot trial manifest checksum is invalid")
    required = {
        "preflight_version": TRIAL_PREFLIGHT_VERSION,
        "route": TRIAL_ROUTE,
        "route_version": TRIAL_ROUTE_VERSION,
        "core_slot_contract_version": CORE_SLOT_CONTRACT_VERSION,
        "status": "passed",
        "human_approval_required": True,
        "paper_id": paper_id,
        "model": model,
        "packet_checksum": packet.packet_checksum,
        "max_output_tokens": TRIAL_MAX_OUTPUT_TOKENS,
        "proposed_calls": 1,
        "provider_calls": 0,
    }
    if any(manifest.get(key) != value for key, value in required.items()):
        raise ValueError(
            "core slot trial manifest does not bind the current request"
        )
    if manifest.get("request_sha256") != approved_request_sha256:
        raise ValueError(
            "approved request SHA-256 does not match trial manifest"
        )
    request_path = Path(str(manifest.get("request_path", "")))
    if not request_path.is_absolute():
        raise ValueError("trial manifest request path must be absolute")
    try:
        request_bytes = request_path.read_bytes()
    except OSError as exc:
        raise ValueError(
            "approved core slot request bytes are unavailable"
        ) from exc
    if _sha256(request_bytes) != approved_request_sha256:
        raise ValueError(
            "approved core slot request bytes do not match approval SHA-256"
        )
    if manifest.get("request_bytes") != len(request_bytes):
        raise ValueError(
            "approved core slot request bytes do not match manifest"
        )
    try:
        request = json.loads(request_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "approved core slot request bytes are not valid JSON"
        ) from exc
    expected, qualification, bindings = build_core_slot_trial_request(
        packet,
        model=model,
    )
    if request != expected:
        raise ValueError(
            "approved core slot request dictionary does not match inputs"
        )
    for key in (
        "slot_qualification_sha256",
        "dynamic_schema_sha256",
        "request_fingerprint",
    ):
        if manifest.get(key) != bindings[key]:
            raise ValueError(
                f"core slot trial manifest {key} does not match inputs"
            )
    qualified_ids = [
        row["slot_id"] for row in qualification["qualified_slots"]
    ]
    excluded_ids = [
        row["slot_id"]
        for row in qualification["evaluated_slots"]
        if not row["qualified"]
    ]
    if manifest.get("qualified_slot_ids") != qualified_ids:
        raise ValueError(
            "core slot trial qualified slot inventory does not match inputs"
        )
    if manifest.get("excluded_slot_ids") != excluded_ids:
        raise ValueError(
            "core slot trial excluded slot inventory does not match inputs"
        )
    return request, qualification, manifest


def _final_approved_request_bytes(
    *,
    request_path: Path,
    approved_request_sha256: str,
    expected_request: Mapping[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    try:
        request_bytes = request_path.read_bytes()
    except OSError as exc:
        raise ValueError(
            "approved core slot request bytes are unavailable"
        ) from exc
    if _sha256(request_bytes) != approved_request_sha256:
        raise ValueError(
            "approved core slot request bytes changed before dispatch"
        )
    try:
        request = json.loads(request_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "approved core slot request bytes are not valid JSON"
        ) from exc
    if request != expected_request:
        raise ValueError(
            "approved core slot request bytes changed before dispatch"
        )
    return request_bytes, request


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _compact_validation_slots(
    qualification: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    packet_ids_by_slot = {
        str(row["slot_id"]): {
            str(evidence_id) for evidence_id in row["evidence_ids"]
        }
        for row in payload["core_slot_packets"]
    }
    validation_slots = []
    for slot in qualification["qualified_slots"]:
        slot_id = str(slot["slot_id"])
        exact_ids = packet_ids_by_slot[slot_id]
        validation_slot = dict(slot)
        validation_slot["evidence_ids"] = [
            evidence_id
            for evidence_id in slot["evidence_ids"]
            if evidence_id in exact_ids
        ]
        for category in (
            "formulation_evidence_ids",
            "payload_evidence_ids",
            "model_evidence_ids",
            "outcome_evidence_ids",
        ):
            validation_slot[category] = [
                evidence_id
                for evidence_id in slot[category]
                if evidence_id in exact_ids
            ]
        validation_slots.append(validation_slot)
    return validation_slots


def run_approved_core_slot_trial(
    paper_id: str,
    *,
    model: str,
    client: Any,
    manifest_path: Path,
    approved_request_sha256: str | None,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = RUN_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Dispatch exactly one preflight-approved request and validate it."""

    _require_trial_paper(paper_id)
    run_dir = output_root / paper_id
    invocation_path = run_dir / "invocation_started.json"
    if invocation_path.exists():
        raise FileExistsError(
            "A core slot trial invocation already started; refusing duplicate"
        )
    if (run_dir / "manifest.json").exists():
        raise FileExistsError(
            "A completed core slot trial exists; refusing duplicate"
        )
    packet = load_packet(paper_id, packet_root)
    request, qualification, preflight_manifest = _load_approved_request(
        paper_id=paper_id,
        model=model,
        packet=packet,
        manifest_path=manifest_path,
        approved_request_sha256=approved_request_sha256,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    approved_request_bytes, request = _final_approved_request_bytes(
        request_path=Path(preflight_manifest["request_path"]),
        approved_request_sha256=str(approved_request_sha256),
        expected_request=request,
    )
    (run_dir / "request.json").write_bytes(approved_request_bytes)
    started_at = datetime.now(timezone.utc)
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
            marker.write(
                json.dumps(invocation, ensure_ascii=False, indent=2) + "\n"
            )
            marker.flush()
            os.fsync(marker.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            "A core slot trial invocation already started; refusing duplicate"
        ) from exc
    _fsync_directory(run_dir)
    response = client.responses.create(**request)
    completed_at = datetime.now(timezone.utc)
    (run_dir / "response.json").write_text(
        json.dumps(
            response.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not response.output_text:
        raise RuntimeError(
            "approved core slot response has no structured output"
        )
    try:
        trial_response = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "approved core slot response is not valid JSON"
        ) from exc
    (run_dir / "trial_response.json").write_text(
        json.dumps(trial_response, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    compact_body = {
        key: value
        for key, value in trial_response.items()
        if key
        not in {"core_slot_contract_version", "core_slot_accounting"}
    }
    compact_result = CompactExtractionResponse.model_validate(compact_body)
    (run_dir / "result.json").write_text(
        json.dumps(
            compact_result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    payload = json.loads(request["input"][1]["content"])
    evidence_envelope = {
        row["evidence_id"] for row in payload["evidence"]
    }
    validation = validate_core_slot_response(
        trial_response,
        _compact_validation_slots(qualification, payload),
        evidence_envelope,
    )
    (run_dir / "scientific_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    usage = (
        response.usage.model_dump(mode="json")
        if response.usage
        else None
    )
    manifest = {
        "status": "completed_pending_human_review",
        "paper_id": paper_id,
        "route": TRIAL_ROUTE,
        "route_version": TRIAL_ROUTE_VERSION,
        "core_slot_contract_version": CORE_SLOT_CONTRACT_VERSION,
        "paid_api_requests": 1,
        "repair_calls": 0,
        "vision_calls": 0,
        "model_requested": model,
        "model_returned": response.model,
        "response_id": response.id,
        "approved_request_sha256": approved_request_sha256,
        "preflight_manifest_path": str(manifest_path.resolve()),
        "packet_checksum": packet.packet_checksum,
        "qualified_slot_ids": preflight_manifest[
            "qualified_slot_ids"
        ],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_seconds": (completed_at - started_at).total_seconds(),
        "usage": usage,
        "scientifically_confirmed": validation[
            "scientifically_confirmed"
        ],
        "validation_errors": len(validation["errors"]),
        "rejected_links": len(validation["rejected_links"]),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NP-001 guarded core biological slot trial"
    )
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--packet-root", type=Path, default=PACKET_ROOT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PREFLIGHT_OUTPUT_ROOT,
    )
    args = parser.parse_args(sys.argv[1:])
    print(
        json.dumps(
            preflight_core_slot_trial(
                args.paper_id,
                model=args.model,
                packet_root=args.packet_root,
                output_root=args.output_root,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
