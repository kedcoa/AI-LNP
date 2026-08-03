"""Run one fully approved application-pilot manifest sequentially and once."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from src.extraction.prepare_application_pilot import (
    ApprovalManifest,
    ApprovalRequest,
    RunSummary,
    _canonical_json,
    _json_bytes,
    _sha256,
)
from src.rag.compact_api_packet import estimate_tokens


def _has_symlink_component(path: Path) -> bool:
    """Inspect every existing path component without following symlinks."""

    if not path.is_absolute():
        return False
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except FileNotFoundError:
            continue
    return False


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

    if not manifest_path.is_absolute():
        raise ValueError("manifest path must be absolute")
    if _has_symlink_component(manifest_path):
        raise ValueError("manifest path cannot contain a symlink")
    expected_manifest_path = manifest_path
    request_root = manifest.request_root
    run_root = manifest.run_root
    if manifest.manifest_path != expected_manifest_path:
        raise ValueError("manifest path binding does not match the approved manifest")
    expected_request_root = manifest_path.parent / "requests"
    expected_run_root = manifest_path.parent / "run"
    if request_root != expected_request_root or run_root != expected_run_root:
        raise ValueError("manifest roots must be exact children of its directory")
    if _has_symlink_component(request_root) or _has_symlink_component(run_root):
        raise ValueError("manifest roots cannot contain symlinks")

    listed_paths = {row.request_path for row in manifest.requests}
    for entry in request_root.rglob("*"):
        try:
            if stat.S_ISLNK(os.lstat(entry).st_mode):
                raise ValueError("request directory cannot contain symlinks")
        except FileNotFoundError as exc:
            raise ValueError("request directory changed during validation") from exc
    actual_paths = {
        path
        for path in request_root.rglob("*")
        if path.is_file()
    }
    if actual_paths != listed_paths:
        raise ValueError("request directory contains a missing or extra request")

    verified: list[tuple[ApprovalRequest, dict[str, Any]]] = []
    for row in manifest.requests:
        request_path = row.request_path
        if not request_path.is_absolute():
            raise ValueError("approved request path must be absolute")
        if request_path.parent != request_root:
            raise ValueError("approved request path is outside the request root")
        if _has_symlink_component(request_path):
            raise ValueError("approved request path cannot contain a symlink")
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
            if not row.source_artifact_path.is_absolute():
                raise ValueError(
                    f"approved request {row.request_id} source path must be absolute"
                )
            if _has_symlink_component(row.source_artifact_path):
                raise ValueError(
                    f"approved request {row.request_id} source path contains a symlink"
                )
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

    for binding in manifest.source_bindings:
        if not binding.path.is_absolute():
            raise ValueError("manifest source binding path must be absolute")
        if _has_symlink_component(binding.path):
            raise ValueError("manifest source binding cannot contain a symlink")
        try:
            source_bytes = binding.path.read_bytes()
        except OSError as exc:
            raise ValueError("manifest source artifact is unavailable") from exc
        if _sha256(source_bytes) != binding.sha256:
            raise ValueError("manifest source artifact changed")

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
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        payload = {**payload, "output_text": output_text}
    return payload


def _atomic_create(path: Path, content: bytes) -> None:
    """Publish complete bytes exactly once without replacing another runner."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FileExistsError(f"artifact already exists: {path}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


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
    client_factory: Callable[[], Any] | None = None,
) -> RunSummary:
    """Execute every and only approved request once, continuing after failures."""

    if client is not None and client_factory is not None:
        raise ValueError("provide either client or client_factory, not both")
    manifest, verified = _load_and_verify_manifest(
        Path(manifest_path), approval_hash
    )
    _atomic_create(
        manifest.run_root / "run_started.json",
        _json_bytes(
            {
                "status": "run_started",
                "manifest_path": str(Path(manifest_path)),
                "approval_hash": approval_hash,
            }
        ),
    )
    attempted: list[str] = []
    succeeded: list[str] = []
    failed: list[str] = []
    response_paths: dict[str, Path] = {}
    error_paths: dict[str, Path] = {}
    provider_call_count = 0

    if not verified:
        summary = RunSummary(
            manifest_path=Path(manifest_path),
            approval_hash=approval_hash,
            attempted_request_ids=[],
            succeeded_request_ids=[],
            failed_request_ids=[],
            provider_call_count=0,
            retry_count=0,
            repair_count=0,
            response_artifact_paths={},
            error_artifact_paths={},
        )
        _atomic_create(
            manifest.run_root / "summary.json",
            _json_bytes(summary.model_dump(mode="json")),
        )
        return summary

    run_marker = manifest.run_root / "run_started.json"
    try:
        provider = (
            client
            if client is not None
            else client_factory()
            if client_factory is not None
            else OpenAI(max_retries=0)
        )
    except Exception:
        try:
            run_marker.unlink()
        except FileNotFoundError:
            pass
        raise

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
            _atomic_create(
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
            _atomic_create(
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
    _atomic_create(
        manifest.run_root / "summary.json",
        _json_bytes(summary.model_dump(mode="json")),
    )
    return summary
