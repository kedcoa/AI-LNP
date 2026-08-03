"""Run one fully approved application-pilot manifest sequentially and once."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from src.extraction.prepare_application_pilot import (
    ApprovalManifest,
    ApprovalRequest,
    RunSummary,
    _atomic_write,
    _canonical_json,
    _json_bytes,
    _sha256,
)
from src.rag.compact_api_packet import estimate_tokens


def _load_and_verify_manifest(
    manifest_path: Path, approval_hash: str
) -> tuple[ApprovalManifest, list[tuple[ApprovalRequest, dict[str, Any]]]]:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("approval manifest is unavailable or invalid") from exc
    if not isinstance(raw, dict):
        raise ValueError("approval manifest must be a JSON object")
    try:
        manifest = ApprovalManifest.model_validate(raw)
    except ValidationError as exc:
        raise ValueError("approval manifest failed strict validation") from exc
    unsigned = {key: value for key, value in raw.items() if key != "approval_hash"}
    computed_hash = _sha256(_canonical_json(unsigned).encode("utf-8"))
    if approval_hash != manifest.approval_hash or computed_hash != approval_hash:
        raise PermissionError("approval hash does not match canonical manifest content")

    resolved_manifest_path = manifest_path.resolve()
    request_root = manifest.request_root.resolve()
    run_root = manifest.run_root.resolve()
    if manifest.manifest_path.resolve() != resolved_manifest_path:
        raise ValueError("manifest path binding does not match the approved manifest")
    if not request_root.is_absolute() or not run_root.is_absolute():
        raise ValueError("manifest request and run roots must be absolute")

    listed_paths = {row.request_path.resolve() for row in manifest.requests}
    actual_paths = {
        path.resolve()
        for path in request_root.rglob("*")
        if path.is_file()
    }
    if actual_paths != listed_paths:
        raise ValueError("request directory contains a missing or extra request")

    verified: list[tuple[ApprovalRequest, dict[str, Any]]] = []
    for row in manifest.requests:
        request_path = row.request_path.resolve()
        if request_path.parent != request_root:
            raise ValueError("approved request path is outside the request root")
        try:
            request_bytes = request_path.read_bytes()
            request = json.loads(request_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"approved request {row.request_id} is unavailable or invalid"
            ) from exc
        if not isinstance(request, dict):
            raise ValueError(f"approved request {row.request_id} is not an object")
        if _sha256(request_bytes) != row.request_sha256:
            raise ValueError(f"approved request {row.request_id} bytes changed")
        if request.get("model") != row.model:
            raise ValueError(f"approved request {row.request_id} model changed")
        if request.get("max_output_tokens") != row.max_output_tokens:
            raise ValueError(
                f"approved request {row.request_id} output cap changed"
            )
        if estimate_tokens(request) != row.estimated_input_tokens:
            raise ValueError(
                f"approved request {row.request_id} exact token estimate changed"
            )
        if (row.source_artifact_path is None) != (
            row.source_artifact_sha256 is None
        ):
            raise ValueError(
                f"approved request {row.request_id} has an incomplete source binding"
            )
        if row.source_artifact_path is not None:
            try:
                source_bytes = row.source_artifact_path.read_bytes()
            except OSError as exc:
                raise ValueError(
                    f"approved request {row.request_id} source artifact is unavailable"
                ) from exc
            if _sha256(source_bytes) != row.source_artifact_sha256:
                raise ValueError(
                    f"approved request {row.request_id} source artifact changed"
                )
        verified.append((row, request))

    summary_path = run_root / "summary.json"
    if summary_path.exists():
        raise FileExistsError("approved manifest was already run")
    for row, _ in verified:
        request_run_root = run_root / row.request_id
        if any(
            (request_run_root / name).exists()
            for name in ("invocation.json", "response.json", "error.json")
        ):
            raise FileExistsError(
                f"request {row.request_id} already has a durable run artifact"
            )
    return manifest, verified


def _response_payload(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        payload = response.model_dump(mode="json")
    elif isinstance(response, Mapping):
        payload = dict(response)
    else:
        raise TypeError("provider response is not serializable as an object")
    if not isinstance(payload, dict):
        raise TypeError("provider response serialization must be an object")
    return payload


def _write_invocation_marker(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError("request already has an invocation marker") from exc


def run_approved_manifest(
    manifest_path: Path,
    approval_hash: str,
    *,
    client: Any | None = None,
) -> RunSummary:
    """Execute every and only approved request once, continuing after failures."""

    manifest, verified = _load_and_verify_manifest(
        Path(manifest_path), approval_hash
    )
    provider = client if client is not None else OpenAI(max_retries=0)
    attempted: list[str] = []
    succeeded: list[str] = []
    failed: list[str] = []
    response_paths: dict[str, Path] = {}
    error_paths: dict[str, Path] = {}
    provider_call_count = 0

    for row, request in verified:
        attempted.append(row.request_id)
        request_root = manifest.run_root / row.request_id
        invocation_path = request_root / "invocation.json"
        response_path = request_root / "response.json"
        error_path = request_root / "error.json"
        try:
            current_bytes = row.request_path.read_bytes()
            if _sha256(current_bytes) != row.request_sha256:
                raise ValueError("approved request bytes changed before dispatch")
            _write_invocation_marker(
                invocation_path,
                {
                    "status": "invocation_started",
                    "request_id": row.request_id,
                    "request_sha256": row.request_sha256,
                    "approval_hash": approval_hash,
                },
            )
            provider_call_count += 1
            response = provider.responses.create(**request)
            payload = _response_payload(response)
            _atomic_write(
                response_path,
                _json_bytes(
                    {
                        "status": "completed",
                        "request_id": row.request_id,
                        "request_sha256": row.request_sha256,
                        "approval_request": row.model_dump(mode="json"),
                        "response": payload,
                    }
                ),
            )
            response_paths[row.request_id] = response_path
            succeeded.append(row.request_id)
        except Exception as exc:
            _atomic_write(
                error_path,
                _json_bytes(
                    {
                        "status": "failed",
                        "request_id": row.request_id,
                        "request_sha256": row.request_sha256,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "retry_count": 0,
                        "repair_count": 0,
                    }
                ),
            )
            error_paths[row.request_id] = error_path
            failed.append(row.request_id)

    summary = RunSummary(
        manifest_path=Path(manifest_path).resolve(),
        approval_hash=approval_hash,
        attempted_request_ids=attempted,
        succeeded_request_ids=succeeded,
        failed_request_ids=failed,
        provider_call_count=provider_call_count,
        retry_count=0,
        repair_count=0,
        response_artifact_paths=response_paths,
        error_artifact_paths=error_paths,
    )
    _atomic_write(
        manifest.run_root / "summary.json",
        _json_bytes(summary.model_dump(mode="json")),
    )
    return summary
