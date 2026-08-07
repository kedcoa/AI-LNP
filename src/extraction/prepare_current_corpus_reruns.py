"""Generate a zero-call preflight for bounded current-corpus reruns."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.database.build_rerun_queue import build_rerun_queue


@dataclass(frozen=True)
class RerunPreflight:
    schema_version: str
    database_path: str
    database_sha256: str
    manifest_path: str
    approval_hash: str
    paper_ids: tuple[str, ...]
    requested_fields: tuple[str, ...]
    requests: tuple[dict[str, Any], ...]
    total_estimated_input_tokens: int
    total_max_output_tokens: int
    provider_calls: int = 0
    human_approval_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_current_corpus_reruns(
    database_path: Path,
    corpus_manifest_path: Path,
    approval_manifest_path: Path,
) -> RerunPreflight:
    database_path = Path(database_path).resolve()
    approval_manifest_path = Path(approval_manifest_path).resolve()
    with sqlite3.connect(database_path) as connection:
        queue = build_rerun_queue(connection)
    requested_papers = {str(item["paper_id"]) for item in queue}
    approval = json.loads(approval_manifest_path.read_text(encoding="utf-8"))
    requests = []
    for row in approval["requests"]:
        if row["paper_id"] not in requested_papers:
            continue
        request_path = Path(row["request_path"])
        if _sha(request_path) != row["request_sha256"]:
            raise ValueError(f"request bytes changed: {row['request_id']}")
        source_path = Path(row["source_artifact_path"])
        if _sha(source_path) != row["source_artifact_sha256"]:
            raise ValueError(f"source artifact changed: {row['request_id']}")
        requests.append({
            "request_id": row["request_id"], "paper_id": row["paper_id"],
            "fields": next(item["fields"] for item in queue if item["paper_id"] == row["paper_id"]),
            "request_path": str(request_path),
            "request_sha256": row["request_sha256"],
            "source_artifact_path": str(source_path),
            "source_artifact_sha256": row["source_artifact_sha256"],
            "model": row["model"],
            "estimated_input_tokens": row["estimated_input_tokens"],
            "max_output_tokens": row["max_output_tokens"],
            "cost_estimate": "not available for the configured internal model rate",
            "expected_merge_target": "source_fact ledger then validated canonical projection",
        })
    if {row["paper_id"] for row in requests} != requested_papers:
        missing = requested_papers - {row["paper_id"] for row in requests}
        raise ValueError(f"rerun queue lacks immutable request bytes: {sorted(missing)}")
    requested_fields = tuple(
        sorted(f"{item['paper_id']}:{field}" for item in queue for field in item["fields"])
    )
    return RerunPreflight(
        schema_version="current-corpus-rerun-preflight/v1",
        database_path=str(database_path), database_sha256=_sha(database_path),
        manifest_path=str(approval["manifest_path"]),
        approval_hash=approval["approval_hash"],
        paper_ids=tuple(sorted(requested_papers)),
        requested_fields=requested_fields,
        requests=tuple(requests),
        total_estimated_input_tokens=sum(row["estimated_input_tokens"] for row in requests),
        total_max_output_tokens=sum(row["max_output_tokens"] for row in requests),
    )


def write_preflight(preflight: RerunPreflight, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preflight.to_dict(), indent=2, sort_keys=True) + "\n")


__all__ = ["RerunPreflight", "prepare_current_corpus_reruns", "write_preflight"]
