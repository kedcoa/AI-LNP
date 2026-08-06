"""Typed, local-only contracts for a current-corpus manifest.

This module only inventories existing local files.  It does not read
credentials, invoke providers, or perform scientific extraction.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject misspelled manifest keys rather than silently dropping them."""

    model_config = ConfigDict(extra="forbid")


class CorpusEntry(StrictModel):
    """One paper's explicit corpus and rerun routing state."""

    paper_id: str = Field(min_length=1)
    title: str | None = None
    doi: str | None = None
    pmid: str | None = None
    import_status: Literal[
        "ready",
        "ready_with_missing_fields",
        "needs_review",
        "blocked",
        "screening_only",
    ]
    rerun_status: Literal["none", "selective", "blocked_pending_access"] = "none"
    rerun_reason: str | None = None
    import_artifact: str | None = None

    @model_validator(mode="after")
    def validate_routing(self) -> "CorpusEntry":
        if self.import_status == "screening_only" and self.import_artifact is not None:
            raise ValueError("screening_only entries cannot select an import artifact")
        if self.rerun_status != "none" and not (self.rerun_reason or "").strip():
            raise ValueError("non-none rerun status requires a rerun reason")
        return self

    @property
    def selected_import_artifact(self) -> str | None:
        """Compatibility-friendly name for the selected import path."""

        return self.import_artifact


class ArtifactCandidate(StrictModel):
    """Deterministic metadata for one local, non-raw candidate artifact."""

    paper_id: str
    path: str
    sha256: str
    artifact_kind: str
    pipeline_clue: str | None = None
    validation_clue: str | None = None
    modified_at: str

    @property
    def artifact_path(self) -> str:
        return self.path

    @property
    def pipeline_version_clue(self) -> str | None:
        return self.pipeline_clue

    @property
    def modification_time(self) -> str:
        return self.modified_at


_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".superpowers",
        ".venv",
        ".venv-rag",
        "__pycache__",
        "licensed",
        "provider",
        "providers",
        "raw",
    }
)
_EXCLUDED_FILE_NAMES = frozenset({".env", ".env.local", ".env.production"})
_SENSITIVE_PATH_COMPONENT = re.compile(
    r"(?:^|[._-])(?:access[._-]?token|api[._-]?key|credential(?:s)?|"
    r"password(?:s)?|private[._-]?key|secret(?:s)?|raw|provider|licensed)(?:[._-]|$)",
    re.IGNORECASE,
)
_ARTIFACT_KINDS = {
    ".csv": "csv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".md": "markdown",
    ".pdf": "pdf",
    ".tsv": "tsv",
    ".txt": "text",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}
_PIPELINE_CLUE = re.compile(
    r"(?<![a-z0-9])(?:v\d+(?:[._-]\d+)*|day\d+|g\d+)(?![a-z0-9])",
    re.IGNORECASE,
)
_VALIDATION_CLUE = re.compile(r"(?:validation|validated|invalid|review)", re.IGNORECASE)


def load_lane(path: str | Path) -> list[CorpusEntry]:
    """Load a JSON lane, preserving unresolved bibliography as ``null`` values."""

    lane_path = Path(path)
    raw = json.loads(lane_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, Mapping):
        rows = raw.get("entries")
    else:
        raise ValueError("corpus lane must be a JSON list or an object with entries")

    if not isinstance(rows, list):
        raise ValueError("corpus lane entries must be a list")

    entries = [CorpusEntry.model_validate(row) for row in rows]
    _validate_unique_paper_ids(entries)
    return entries


def validate_corpus(
    entries: Sequence[CorpusEntry], root: str | Path
) -> list[CorpusEntry]:
    """Validate corpus-wide uniqueness and selected local import artifacts."""

    corpus_root = Path(root).resolve()
    if not corpus_root.is_dir():
        raise ValueError(f"corpus root is not a directory: {corpus_root}")

    materialized = list(entries)
    _validate_unique_paper_ids(materialized)
    for entry in materialized:
        if entry.import_artifact is None:
            continue
        artifact_path = _resolve_within_root(corpus_root, entry.import_artifact)
        if _is_excluded(artifact_path.relative_to(corpus_root)):
            raise ValueError(
                "selected import artifact is excluded by local safety policy: "
                f"{entry.import_artifact}"
            )
        if not artifact_path.is_file():
            raise ValueError(
                "selected import artifact does not exist for "
                f"{entry.paper_id}: {entry.import_artifact}"
            )
    return materialized


def scan_artifact_candidates(
    root: str | Path, paper_ids: Iterable[str]
) -> list[ArtifactCandidate]:
    """Return sorted candidate metadata for local, non-raw paper artifacts.

    Paths are expressed relative to ``root`` so inventory output is portable.
    """

    artifact_root = Path(root).resolve()
    if not artifact_root.is_dir():
        raise ValueError(f"artifact root is not a directory: {artifact_root}")

    known_paper_ids = sorted({paper_id for paper_id in paper_ids if paper_id}, key=lambda value: (-len(value), value))
    if not known_paper_ids:
        return []

    candidates: list[ArtifactCandidate] = []
    for path in sorted(artifact_root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        relative_path = path.relative_to(artifact_root)
        if _is_excluded(relative_path):
            continue
        paper_id = _paper_id_for(relative_path.as_posix(), known_paper_ids)
        if paper_id is None:
            continue
        stat = path.stat()
        filename = relative_path.name
        candidates.append(
            ArtifactCandidate(
                paper_id=paper_id,
                path=relative_path.as_posix(),
                sha256=_sha256(path),
                artifact_kind=_artifact_kind(path),
                pipeline_clue=_find_clue(_PIPELINE_CLUE, relative_path.as_posix()),
                validation_clue=_find_clue(_VALIDATION_CLUE, filename),
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            )
        )
    return candidates


def _validate_unique_paper_ids(entries: Sequence[CorpusEntry]) -> None:
    seen: set[str] = set()
    for entry in entries:
        if entry.paper_id in seen:
            raise ValueError(f"duplicate paper_id in corpus manifest: {entry.paper_id}")
        seen.add(entry.paper_id)


def _resolve_within_root(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"selected import artifact is outside corpus root: {value}") from exc
    return candidate


def _is_excluded(relative_path: Path) -> bool:
    lowered_parts = [part.casefold() for part in relative_path.parts]
    if any(
        part in _EXCLUDED_DIRECTORY_NAMES
        or _SENSITIVE_PATH_COMPONENT.search(part)
        for part in lowered_parts[:-1]
    ):
        return True
    filename = lowered_parts[-1]
    return (
        filename in _EXCLUDED_FILE_NAMES
        or filename.startswith(".env.")
        or _SENSITIVE_PATH_COMPONENT.search(filename) is not None
    )


def _paper_id_for(path: str, paper_ids: Sequence[str]) -> str | None:
    for paper_id in paper_ids:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(paper_id)}(?![A-Za-z0-9])")
        if pattern.search(path):
            return paper_id
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_kind(path: Path) -> str:
    return _ARTIFACT_KINDS.get(path.suffix.casefold(), path.suffix.casefold().lstrip(".") or "unknown")


def _find_clue(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    return match.group(0).casefold() if match else None
