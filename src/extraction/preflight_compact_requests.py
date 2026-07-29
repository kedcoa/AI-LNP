"""Validate exact v1.2 OpenAI request bodies without generating model output."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .run_compact_one_call import (
    OUTPUT_ROOT as PAID_OUTPUT_ROOT,
    build_openai_request,
    load_packet,
)
from .v12_main_route import allowed_v12_evidence_ids


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = (
    ROOT / "data/staging/extraction/compact_one_call_v1_2_preflight"
)
GOLD_IDENTIFIER = re.compile(r"\bG[OX]-\d+")


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


def run(
    paper_ids: list[str],
    *,
    model: str,
    client: OpenAI,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    available_models = {row.id for row in client.models.list().data}
    if model not in available_models:
        raise ValueError(f"configured model is unavailable: {model}")

    rows: list[dict[str, Any]] = []
    for paper_id in paper_ids:
        if (PAID_OUTPUT_ROOT / paper_id / "response.json").exists():
            raise FileExistsError(
                f"paid response already exists for {paper_id}"
            )
        packet = load_packet(paper_id)
        (
            api_request,
            recall_support,
            _user_payload,
            fingerprint,
        ) = build_openai_request(packet, model=model)
        serialized = json.dumps(
            api_request, ensure_ascii=False, sort_keys=True
        )
        schema = api_request["text"]["format"]["schema"]
        schema_checks = _schema_checks(schema)
        evidence_checks = _evidence_checks(api_request, recall_support)
        gold_identifiers = sorted(set(GOLD_IDENTIFIER.findall(serialized)))
        if gold_identifiers:
            raise ValueError(
                f"{paper_id} request contains gold identifiers: "
                f"{gold_identifiers}"
            )
        if not all(
            value
            for key, value in schema_checks.items()
            if key
            in {
                "root_is_object",
                "root_is_not_any_of",
                "within_5000_property_limit",
                "within_10_level_object_limit",
                "all_object_fields_required",
                "all_objects_disallow_extra_properties",
            }
        ):
            raise ValueError(f"{paper_id} strict schema audit failed")
        if not evidence_checks["all_support_evidence_ids_resolve"]:
            raise ValueError(f"{paper_id} evidence audit failed")

        # The official endpoint accepts the same model/input/reasoning/text
        # shape as Responses but returns a token count without generation.
        token_count = client.responses.input_tokens.count(
            model=api_request["model"],
            reasoning=api_request["reasoning"],
            input=api_request["input"],
            text=api_request["text"],
        )
        paper_root = output_root / paper_id
        paper_root.mkdir(parents=True, exist_ok=True)
        (paper_root / "request.json").write_text(
            json.dumps(api_request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        row = {
            "paper_id": paper_id,
            "status": "passed",
            "model": model,
            "request_fingerprint": fingerprint,
            "request_bytes": len(serialized.encode("utf-8")),
            "server_input_tokens": token_count.input_tokens,
            "schema_checks": schema_checks,
            "evidence_checks": evidence_checks,
            "gold_identifiers": gold_identifiers,
            "accepted_visual_claims": len(
                recall_support.get("accepted_visual_claims", [])
            ),
            "generation_requests": 0,
            "input_token_count_requests": 1,
        }
        (paper_root / "preflight.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rows.append(row)

    report = {
        "preflight_version": "compact-request-preflight-1.2.0",
        "status": "passed",
        "model": model,
        "papers": rows,
        "total_server_input_tokens": sum(
            row["server_input_tokens"] for row in rows
        ),
        "generation_requests": 0,
        "input_token_count_requests": len(rows),
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
            "Validate exact compact requests through the non-generating "
            "OpenAI input-token endpoint."
        )
    )
    parser.add_argument("--paper-id", action="append", required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    model = os.getenv("COMPACT_EXTRACTION_MODEL", "gpt-5.6-terra")
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ),
        timeout=300.0,
        max_retries=0,
    )
    print(json.dumps(
        run(args.paper_id, model=model, client=client),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
