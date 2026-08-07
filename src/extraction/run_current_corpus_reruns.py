"""Approval wrapper for exact current-corpus rerun request hashes."""

from __future__ import annotations

import json
from pathlib import Path

from src.extraction.run_application_pilot import run_approved_manifest


def run_current_corpus_reruns(
    manifest_path: Path,
    approval_hash: str,
    *,
    approved_request_hashes: set[str],
):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    expected = {row["request_sha256"] for row in manifest["requests"]}
    if approved_request_hashes != expected:
        raise PermissionError(
            "approved request hash set does not exactly match the rerun manifest"
        )
    return run_approved_manifest(Path(manifest_path), approval_hash)


__all__ = ["run_current_corpus_reruns"]
