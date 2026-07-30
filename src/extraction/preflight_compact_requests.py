"""Validate exact v1.2 OpenAI request bodies without generating model output."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.rag.compact_api_packet import estimate_tokens

from .run_compact_one_call import (
    PACKET_ROOT,
    PRIMARY_PREFLIGHT_VERSION,
    PRIMARY_ROUTE,
    PRIMARY_ROUTE_VERSION,
    build_openai_request,
    load_packet,
)
from .v12_main_route import allowed_v12_evidence_ids


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = (
    ROOT / "data/staging/extraction/compact_one_call_v1_2_preflight"
)
GOLD_IDENTIFIER = re.compile(r"\bG[OX]-\d+")


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


def _schema_checks(schema: dict[str, Any]) -> dict[str, Any]:
    object_count = 0
    property_count = 0
    max_object_depth = 0
    missing_required: list[str] = []
    missing_additional_false: list[str] = []

    def walk(value: Any, *, path: str = "$", object_depth: int = 0) -> None:
        nonlocal object_count, property_count, max_object_depth
        if isinstance(value, dict):
            is_object = value.get("type") == "object" or "properties" in value
            next_depth = object_depth + int(is_object)
            max_object_depth = max(max_object_depth, next_depth)
            if is_object:
                object_count += 1
                properties = value.get("properties", {})
                property_count += len(properties)
                if set(value.get("required", [])) != set(properties):
                    missing_required.append(path)
                if value.get("additionalProperties") is not False:
                    missing_additional_false.append(path)
            for key, child in value.items():
                walk(
                    child,
                    path=f"{path}.{key}",
                    object_depth=next_depth,
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(
                    child,
                    path=f"{path}[{index}]",
                    object_depth=object_depth,
                )

    walk(schema)
    return {
        "root_is_object": schema.get("type") == "object",
        "root_is_not_any_of": "anyOf" not in schema,
        "object_count": object_count,
        "property_count": property_count,
        "max_object_depth": max_object_depth,
        "within_5000_property_limit": property_count <= 5_000,
        "within_10_level_object_limit": max_object_depth <= 10,
        "all_object_fields_required": not missing_required,
        "all_objects_disallow_extra_properties": (
            not missing_additional_false
        ),
        "missing_required_paths": missing_required,
        "missing_additional_false_paths": missing_additional_false,
    }


def _evidence_checks(
    api_request: dict[str, Any],
    recall_support: dict[str, Any],
) -> dict[str, Any]:
    payload = json.loads(api_request["input"][1]["content"])
    packet_ids = {
        row["evidence_id"]
        for row in payload["evidence_packet"].get("evidence", [])
    }
    local_ids = allowed_v12_evidence_ids(recall_support)
    allowed_ids = packet_ids | local_ids
    referenced_ids = {
        evidence_id
        for candidate in recall_support.get(
            "atomic_outcome_candidates", []
        )
        for evidence_id in candidate.get("evidence_ids", [])
    } | {
        row["evidence_id"]
        for row in recall_support.get("accepted_visual_claims", [])
    }
    unknown_ids = sorted(referenced_ids - allowed_ids)
    return {
        "packet_evidence_ids": len(packet_ids),
        "local_evidence_ids": len(local_ids),
        "referenced_support_evidence_ids": len(referenced_ids),
        "unknown_support_evidence_ids": unknown_ids,
        "all_support_evidence_ids_resolve": not unknown_ids,
    }


def preflight_primary_request(
    paper_id: str,
    *,
    model: str,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Persist and sign one exact compact primary request using local checks."""

    packet = load_packet(paper_id, packet_root)
    (
        api_request,
        recall_support,
        _user_payload,
        fingerprint,
    ) = build_openai_request(packet, model=model)
    serialized = _canonical_json(api_request)
    schema_checks = _schema_checks(
        api_request["text"]["format"]["schema"]
    )
    evidence_checks = _evidence_checks(api_request, recall_support)
    gold_identifiers = sorted(
        set(GOLD_IDENTIFIER.findall(serialized))
    )
    required_schema_checks = {
        "root_is_object",
        "root_is_not_any_of",
        "within_5000_property_limit",
        "within_10_level_object_limit",
        "all_object_fields_required",
        "all_objects_disallow_extra_properties",
    }
    if gold_identifiers:
        raise ValueError(
            f"{paper_id} request contains gold identifiers: "
            f"{gold_identifiers}"
        )
    if not all(
        value
        for key, value in schema_checks.items()
        if key in required_schema_checks
    ):
        raise ValueError(f"{paper_id} strict schema audit failed")
    if not evidence_checks["all_support_evidence_ids_resolve"]:
        raise ValueError(f"{paper_id} evidence audit failed")

    paper_root = (output_root / paper_id).resolve()
    paper_root.mkdir(parents=True, exist_ok=True)
    request_path = paper_root / "request.json"
    request_bytes = (
        json.dumps(api_request, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    request_path.write_bytes(request_bytes)
    unsigned_manifest = {
        "preflight_version": PRIMARY_PREFLIGHT_VERSION,
        "route": PRIMARY_ROUTE,
        "route_version": PRIMARY_ROUTE_VERSION,
        "status": "passed",
        "human_approval_required": True,
        "request_path": str(request_path),
        "request_sha256": _sha256(request_bytes),
        "paper_id": paper_id,
        "model": model,
        "packet_checksum": packet.packet_checksum,
        "request_fingerprint": fingerprint,
        "request_bytes": len(request_bytes),
        "estimated_input_tokens": estimate_tokens(api_request),
        "max_output_tokens": api_request["max_output_tokens"],
        "schema_checks": schema_checks,
        "evidence_checks": evidence_checks,
        "gold_identifiers": gold_identifiers,
        "provider_calls": 0,
    }
    manifest = {
        **unsigned_manifest,
        "manifest_checksum": _sha256(
            _canonical_json(unsigned_manifest)
        ),
    }
    (paper_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def run(
    paper_ids: list[str],
    *,
    model: str,
    packet_root: Path = PACKET_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    rows = [
        preflight_primary_request(
            paper_id,
            model=model,
            packet_root=packet_root,
            output_root=output_root,
        )
        for paper_id in paper_ids
    ]
    report = {
        "preflight_version": PRIMARY_PREFLIGHT_VERSION,
        "status": "passed",
        "model": model,
        "papers": rows,
        "total_estimated_input_tokens": sum(
            row["estimated_input_tokens"] for row in rows
        ),
        "provider_calls": 0,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and persist exact compact primary requests locally."
        )
    )
    parser.add_argument("--paper-id", action="append", required=True)
    parser.add_argument("--packet-root", type=Path, default=PACKET_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--model", default="gpt-5.6-terra")
    args = parser.parse_args()
    print(json.dumps(
        run(
            args.paper_id,
            model=args.model,
            packet_root=args.packet_root,
            output_root=args.output_root,
        ),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
