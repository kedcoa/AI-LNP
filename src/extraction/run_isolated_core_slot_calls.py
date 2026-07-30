"""Six sequential, independently approved NP-001 core-slot calls."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openai.lib._pydantic import to_strict_json_schema

from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.core_biological_slots import (
    build_core_slot_schema,
    validate_core_slot_response,
)
from src.extraction.run_compact_one_call import PACKET_ROOT, load_packet
from src.extraction.run_core_slot_trial import (
    TRIAL_MAX_OUTPUT_TOKENS,
    _canonical_json,
    _compact_validation_slots,
    _fsync_directory,
    _sha256,
    build_core_slot_trial_request,
)
from src.rag.compact_api_packet import estimate_tokens


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_OUTPUT_ROOT = (
    ROOT / "data/staging/extraction/np001_isolated_core_calls_preflight"
)
RUN_OUTPUT_ROOT = (
    ROOT / "data/staging/extraction/np001_isolated_core_calls_run"
)
ROUTE = "primary-isolated-core-biological-slot-trial"
ROUTE_VERSION = "compact-route-1.5.0-trial"
PREFLIGHT_VERSION = "compact-isolated-core-preflight-1.0.0"
SLOT_IDS = (
    "CORE-HEPG2-TRANSFECTION",
    "CORE-DC24-TRANSFECTION",
    "CORE-DC24-IMMUNE",
    "CORE-HPBMC-TRANSFECTION",
    "CORE-HPBMC-IMMUNE",
    "CORE-MOUSE-BIODISTRIBUTION",
)
_INSTRUCTIONS = (
    "This request contains exactly one core biological slot. Return exactly "
    "one extracted accounting entry for that slot, exactly one complete "
    "experiment, at least one linked outcome, and no unresolved items. "
    "Duplicate or unresolved dispositions are forbidden."
)


def _isolated_requests(
    packet: Any,
    *,
    model: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    global_request, qualification, _bindings = (
        build_core_slot_trial_request(packet, model=model)
    )
    global_payload = json.loads(global_request["input"][1]["content"])
    evidence_by_id = {
        row["evidence_id"]: row for row in global_payload["evidence"]
    }
    slot_by_id = {
        row["slot_id"]: row for row in qualification["qualified_slots"]
    }
    packet_by_id = {
        row["slot_id"]: row
        for row in global_payload["core_slot_packets"]
    }
    if tuple(slot_by_id) != SLOT_IDS:
        raise ValueError("NP-001 must qualify all six isolated core slots")
    requests = []
    for sequence, slot_id in enumerate(SLOT_IDS, start=1):
        slot = slot_by_id[slot_id]
        slot_packet = packet_by_id[slot_id]
        exact_ids = slot_packet["evidence_ids"]
        payload = {
            "paper_id": packet.paper_id,
            "evidence": [evidence_by_id[value] for value in exact_ids],
            "shared_evidence_ids": [
                value
                for value in global_payload["shared_evidence_ids"]
                if value in exact_ids
            ],
            "core_slot_packets": [slot_packet],
        }
        schema = build_core_slot_schema(
            to_strict_json_schema(CompactExtractionResponse),
            [slot],
        )
        entry = schema["$defs"]["CoreSlotAccountingEntry"]
        entry["properties"]["disposition"]["enum"] = ["extracted"]
        schema["properties"]["experiments"].update(
            {"minItems": 1, "maxItems": 1}
        )
        schema["properties"]["outcomes"]["minItems"] = 1
        schema["properties"]["formulations"].update(
            {"minItems": 1, "maxItems": 1}
        )
        schema["properties"]["unresolved_items"]["maxItems"] = 0
        fingerprint = _sha256(
            _canonical_json(
                {
                    "paper_id": packet.paper_id,
                    "packet_checksum": packet.packet_checksum,
                    "slot_id": slot_id,
                    "sequence": sequence,
                    "model": model,
                    "route": ROUTE,
                    "route_version": ROUTE_VERSION,
                    "payload": payload,
                    "schema": schema,
                }
            )
        )
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
                        global_request["input"][0]["content"]
                        + " "
                        + _INSTRUCTIONS
                    ),
                },
                {"role": "user", "content": _canonical_json(payload)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "IsolatedCoreSlotResponse",
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        requests.append(
            {
                "sequence": sequence,
                "slot_id": slot_id,
                "request": request,
                "request_fingerprint": fingerprint,
                "dynamic_schema_sha256": _sha256(
                    _canonical_json(schema)
                ),
            }
        )
    return requests, qualification


def preflight_isolated_core_calls(
    paper_id: str,
    *,
    model: str,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = PREFLIGHT_OUTPUT_ROOT,
) -> dict[str, Any]:
    if paper_id != "NP-001":
        raise ValueError("isolated core calls accept only NP-001")
    packet = load_packet(paper_id, packet_root)
    requests, qualification = _isolated_requests(packet, model=model)
    paper_root = (output_root / paper_id).resolve()
    paper_root.mkdir(parents=True, exist_ok=True)
    entries = []
    for row in requests:
        slot_root = paper_root / f"{row['sequence']:02d}"
        slot_root.mkdir(parents=True, exist_ok=True)
        request_path = slot_root / "request.json"
        request_bytes = (
            json.dumps(row["request"], ensure_ascii=False, indent=2) + "\n"
        ).encode()
        request_path.write_bytes(request_bytes)
        entry = {
            "sequence": row["sequence"],
            "slot_id": row["slot_id"],
            "request_path": str(request_path),
            "request_sha256": _sha256(request_bytes),
            "request_bytes": len(request_bytes),
            "estimated_input_tokens": estimate_tokens(row["request"]),
            "max_output_tokens": TRIAL_MAX_OUTPUT_TOKENS,
            "request_fingerprint": row["request_fingerprint"],
            "dynamic_schema_sha256": row["dynamic_schema_sha256"],
            "provider_calls": 0,
        }
        (slot_root / "preview.txt").write_text(
            "\n".join(
                (
                    f"Sequence: {row['sequence']}",
                    f"Slot: {row['slot_id']}",
                    f"Request: {request_path}",
                    f"SHA-256: {entry['request_sha256']}",
                    (
                        "Estimated input tokens: "
                        f"{entry['estimated_input_tokens']}"
                    ),
                    f"Output cap: {TRIAL_MAX_OUTPUT_TOKENS}",
                    "Proposed calls: 1",
                    "Provider calls: 0",
                )
            )
            + "\n"
        )
        entries.append(entry)
    unsigned = {
        "preflight_version": PREFLIGHT_VERSION,
        "route": ROUTE,
        "route_version": ROUTE_VERSION,
        "paper_id": paper_id,
        "model": model,
        "packet_checksum": packet.packet_checksum,
        "slot_qualification_sha256": _sha256(
            _canonical_json(qualification)
        ),
        "slot_ids": list(SLOT_IDS),
        "proposed_calls": 6,
        "provider_calls": 0,
        "requests": entries,
    }
    manifest = {
        **unsigned,
        "manifest_checksum": _sha256(_canonical_json(unsigned)),
    }
    (paper_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return manifest


def _approved_requests(
    *,
    packet: Any,
    model: str,
    manifest_path: Path,
    approvals: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text())
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_checksum"
    }
    if manifest.get("manifest_checksum") != _sha256(
        _canonical_json(unsigned)
    ):
        raise ValueError("isolated preflight manifest checksum is invalid")
    expected_rows, qualification = _isolated_requests(
        packet,
        model=model,
    )
    approved = []
    for expected, entry in zip(expected_rows, manifest["requests"]):
        slot_id = expected["slot_id"]
        approved_sha = approvals.get(slot_id)
        if approved_sha != entry["request_sha256"]:
            raise PermissionError(
                f"exact approval SHA required for {slot_id}"
            )
        request_path = Path(entry["request_path"])
        request_bytes = request_path.read_bytes()
        if _sha256(request_bytes) != approved_sha:
            raise ValueError(f"approved request bytes changed for {slot_id}")
        request = json.loads(request_bytes)
        if request != expected["request"]:
            raise ValueError(f"approved request mismatch for {slot_id}")
        approved.append(
            {
                **entry,
                "request": request,
                "request_bytes_value": request_bytes,
            }
        )
    return approved, qualification


def run_approved_isolated_core_calls(
    paper_id: str,
    *,
    model: str,
    client: Any,
    preflight_manifest_path: Path,
    approved_request_sha256_by_slot: Mapping[str, str],
    packet_root: Path = PACKET_ROOT,
    output_root: Path = RUN_OUTPUT_ROOT,
) -> dict[str, Any]:
    if paper_id != "NP-001":
        raise ValueError("isolated core calls accept only NP-001")
    packet = load_packet(paper_id, packet_root)
    approved, qualification = _approved_requests(
        packet=packet,
        model=model,
        manifest_path=preflight_manifest_path,
        approvals=approved_request_sha256_by_slot,
    )
    completed = []
    paper_root = output_root / paper_id
    for row in approved[:6]:
        final_request_bytes = Path(row["request_path"]).read_bytes()
        if _sha256(final_request_bytes) != row["request_sha256"]:
            raise ValueError(
                f"approved request bytes changed for {row['slot_id']}"
            )
        final_request = json.loads(final_request_bytes)
        if final_request != row["request"]:
            raise ValueError(
                f"approved request changed for {row['slot_id']}"
            )
        slot_root = paper_root / f"{row['sequence']:02d}"
        marker_path = slot_root / "invocation_started.json"
        if marker_path.exists() or (slot_root / "manifest.json").exists():
            raise FileExistsError(
                f"isolated call already started for {row['slot_id']}"
            )
        slot_root.mkdir(parents=True, exist_ok=True)
        (slot_root / "request.json").write_bytes(final_request_bytes)
        started = datetime.now(timezone.utc)
        with marker_path.open("x") as marker:
            marker.write(
                json.dumps(
                    {
                        "status": "invocation_started",
                        "slot_id": row["slot_id"],
                        "sequence": row["sequence"],
                        "request_sha256": row["request_sha256"],
                        "started_at": started.isoformat(),
                    },
                    indent=2,
                )
                + "\n"
            )
            marker.flush()
            os.fsync(marker.fileno())
        _fsync_directory(slot_root)
        response = client.responses.create(**final_request)
        (slot_root / "response.json").write_text(
            json.dumps(response.model_dump(mode="json"), indent=2) + "\n"
        )
        trial_response = json.loads(response.output_text)
        (slot_root / "trial_response.json").write_text(
            json.dumps(trial_response, indent=2) + "\n"
        )
        compact_body = {
            key: value
            for key, value in trial_response.items()
            if key
            not in {"core_slot_contract_version", "core_slot_accounting"}
        }
        compact = CompactExtractionResponse.model_validate(compact_body)
        (slot_root / "result.json").write_text(
            json.dumps(compact.model_dump(mode="json"), indent=2) + "\n"
        )
        payload = json.loads(final_request["input"][1]["content"])
        isolated_qualification = {
            **qualification,
            "qualified_slots": [
                slot
                for slot in qualification["qualified_slots"]
                if slot["slot_id"] == row["slot_id"]
            ],
        }
        validation = validate_core_slot_response(
            trial_response,
            _compact_validation_slots(isolated_qualification, payload),
            {item["evidence_id"] for item in payload["evidence"]},
        )
        (slot_root / "scientific_validation.json").write_text(
            json.dumps(validation, indent=2) + "\n"
        )
        completed_at = datetime.now(timezone.utc)
        slot_manifest = {
            "status": "completed_pending_human_review",
            "slot_id": row["slot_id"],
            "sequence": row["sequence"],
            "request_sha256": row["request_sha256"],
            "paid_api_requests": 1,
            "repair_calls": 0,
            "vision_calls": 0,
            "scientifically_confirmed": validation[
                "scientifically_confirmed"
            ],
            "started_at": started.isoformat(),
            "completed_at": completed_at.isoformat(),
            "usage": (
                response.usage.model_dump(mode="json")
                if response.usage
                else None
            ),
        }
        (slot_root / "manifest.json").write_text(
            json.dumps(slot_manifest, indent=2) + "\n"
        )
        completed.append(row["slot_id"])
    return {
        "paper_id": paper_id,
        "route": ROUTE,
        "route_version": ROUTE_VERSION,
        "paid_api_requests": len(completed),
        "repair_calls": 0,
        "vision_calls": 0,
        "completed_slot_ids": completed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--packet-root", type=Path, default=PACKET_ROOT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PREFLIGHT_OUTPUT_ROOT,
    )
    args = parser.parse_args()
    print(
        json.dumps(
            preflight_isolated_core_calls(
                args.paper_id,
                model=args.model,
                packet_root=args.packet_root,
                output_root=args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
