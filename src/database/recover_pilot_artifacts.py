"""Safe, deterministic recovery of PILOT source-derived artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal


_FORBIDDEN_TOKENS = (
    "benchmark",
    "answerkey",
    "goldstandard",
    "providerresponse",
    "rawprovider",
    "rawresponse",
    "response",
    "invocation",
)


def _normalized_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _validate_relative_path(path: Path) -> None:
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("artifact paths must be repository-relative")
    normalized = [_normalized_token(part) for part in path.parts]
    if any(
        forbidden in component
        for component in normalized
        for forbidden in _FORBIDDEN_TOKENS
    ):
        raise ValueError("forbidden benchmark or provider artifact path")


@dataclass(frozen=True)
class PilotArtifactExpectation:
    paper_id: str
    source_relative_path: Path
    source_sha256: str
    inventory_relative_path: Path

    def __post_init__(self) -> None:
        _validate_relative_path(self.source_relative_path)
        _validate_relative_path(self.inventory_relative_path)
        if not self.paper_id.startswith("PILOT-"):
            raise ValueError("paper ID must be a PILOT identifier")
        expected_source_prefix = Path("data/staging/new_papers") / self.paper_id
        expected_inventory = (
            Path("data/staging/extraction/application_pilot")
            / self.paper_id
            / "inventory.json"
        )
        if (
            self.source_relative_path.parent != expected_source_prefix
            or self.source_relative_path.suffix.casefold() != ".html"
        ):
            raise ValueError("expected PILOT source HTML path")
        if self.inventory_relative_path != expected_inventory:
            raise ValueError("expected PILOT inventory path")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.source_sha256):
            raise ValueError("source SHA-256 must contain 64 hex characters")


@dataclass(frozen=True)
class PilotRecoveryResult:
    paper_id: str
    status: Literal["recovered", "blocked"]
    source_logical_path: str
    inventory_logical_path: str
    source_sha256: str | None = None
    inventory_sha256: str | None = None
    source_path: str | None = None
    inventory_path: str | None = None
    inventory_bytes: bytes | None = None
    inventory_version: str | None = None
    evidence_block_count: int = 0
    recovery_worktree_root: str | None = None
    recovery_commit: str | None = None
    source_verification: str | None = None
    inventory_verification: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for local_only in ("source_path", "inventory_path", "inventory_bytes"):
            payload.pop(local_only)
        return payload


def registered_worktrees(repository_root: Path) -> dict[Path, str]:
    """Return resolved registered worktree roots and their checked-out commits."""

    command = [
        "git",
        "-C",
        str(repository_root.resolve()),
        "worktree",
        "list",
        "--porcelain",
    ]
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("repository root is not a readable git repository") from exc
    result: dict[Path, str] = {}
    current_root: Path | None = None
    for line in completed.stdout.splitlines():
        if line.startswith("worktree "):
            current_root = Path(line.removeprefix("worktree ")).resolve()
        elif line.startswith("HEAD ") and current_root is not None:
            commit = line.removeprefix("HEAD ").strip()
            if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
                raise ValueError("registered worktree has invalid commit identity")
            result[current_root] = commit
    if not result:
        raise ValueError("repository has no registered git worktrees")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_regular_file_descriptor_relative(
    root: Path,
    relative: Path,
    *,
    before_component_open: Callable[[int], None] | None = None,
) -> bytes:
    """Read through held directory FDs, failing closed without openat support."""

    if (
        not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or os.open not in os.supports_dir_fd
    ):
        raise ValueError("secure descriptor-relative file access is unsupported")
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("artifact path must be contained and relative")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        file_flags |= os.O_CLOEXEC
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(root, directory_flags))
        for index, component in enumerate(relative.parts[:-1]):
            if before_component_open is not None:
                before_component_open(index)
            descriptors.append(
                os.open(
                    component,
                    directory_flags,
                    dir_fd=descriptors[-1],
                )
            )
        final_index = len(relative.parts) - 1
        if before_component_open is not None:
            before_component_open(final_index)
        descriptor = os.open(
            relative.parts[-1], file_flags, dir_fd=descriptors[-1]
        )
        descriptors.append(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("artifact path is not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise ValueError("symlink or non-directory artifact path rejected") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def recover_pilot_sources(
    expectation: PilotArtifactExpectation,
    repository_root: Path,
    worktree_roots: tuple[Path, ...],
) -> PilotRecoveryResult:
    """Find source-matched inventory candidates in registered worktrees.

    Roots are sorted to make selection independent of caller ordering. Raw provider
    response and benchmark paths are rejected by the expectation contract.
    """

    logical_source = expectation.source_relative_path.as_posix()
    logical_inventory = expectation.inventory_relative_path.as_posix()
    failures: list[str] = []
    registrations = registered_worktrees(repository_root)
    candidates = {path.resolve() for path in worktree_roots}
    unregistered = candidates - registrations.keys()
    if unregistered:
        raise ValueError("recovery root is not a registered git worktree")
    for root in sorted(candidates, key=str):
        source = root / expectation.source_relative_path
        inventory = root / expectation.inventory_relative_path
        if not source.exists() or not inventory.exists():
            continue
        try:
            source_bytes = _read_regular_file_descriptor_relative(
                root, expectation.source_relative_path
            )
            inventory_bytes = _read_regular_file_descriptor_relative(
                root, expectation.inventory_relative_path
            )
        except ValueError as exc:
            failures.append(str(exc))
            continue
        source_hash = _sha256_bytes(source_bytes)
        if source_hash != expectation.source_sha256.lower():
            failures.append("source hash mismatch")
            continue
        try:
            payload = json.loads(inventory_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            failures.append("inventory is not valid JSON")
            continue
        if payload.get("paper_id") != expectation.paper_id:
            failures.append("inventory paper mismatch")
            continue
        if payload.get("source_pdf") != source.name:
            failures.append("inventory source mismatch")
            continue
        blocks = payload.get("evidence_blocks")
        if not isinstance(blocks, list):
            failures.append("inventory evidence blocks invalid")
            continue
        return PilotRecoveryResult(
            paper_id=expectation.paper_id,
            status="recovered",
            source_logical_path=logical_source,
            inventory_logical_path=logical_inventory,
            source_sha256=source_hash,
            inventory_sha256=_sha256_bytes(inventory_bytes),
            source_path=str(source.resolve()),
            inventory_path=str(inventory.resolve()),
            inventory_bytes=inventory_bytes,
            inventory_version=payload.get("inventory_version"),
            evidence_block_count=len(blocks),
            recovery_worktree_root=str(root),
            recovery_commit=registrations[root],
            source_verification="manifest_sha256_match",
            inventory_verification="observed_sha256_unverified",
        )
    reason = failures[0] if failures else "source or inventory unavailable"
    return PilotRecoveryResult(
        paper_id=expectation.paper_id,
        status="blocked",
        source_logical_path=logical_source,
        inventory_logical_path=logical_inventory,
        reason=reason,
    )


def prepare_pilot_bundles(
    manifest_path: Path,
    repository_root: Path,
    worktree_roots: tuple[Path, ...],
    output_dir: Path,
) -> dict[str, object]:
    """Recover all PILOT entries and write deterministic blocked-review bundles."""

    from src.database.adapters.pilot_results import build_blocked_pilot_bundle

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = sha256_file(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    paper_summaries: list[dict[str, object]] = []
    recoveries: list[dict[str, object]] = []
    for original_entry in manifest.get("entries", []):
        entry = dict(original_entry)
        paper_id = str(entry["paper_id"])
        source_candidates = [
            row
            for row in entry.get("source_access_records", [])
            if row.get("source_kind") == "full_text_html" and row.get("sha256")
        ]
        inventory_candidates = [
            row
            for row in entry.get("candidate_artifacts", [])
            if row.get("artifact_kind") == "source_inventory"
        ]
        if len(source_candidates) != 1 or len(inventory_candidates) != 1:
            raise ValueError(f"{paper_id} must declare one source and inventory")
        expectation = PilotArtifactExpectation(
            paper_id=paper_id,
            source_relative_path=Path(source_candidates[0]["path"]),
            source_sha256=str(source_candidates[0]["sha256"]),
            inventory_relative_path=Path(inventory_candidates[0]["path"]),
        )
        recovery = recover_pilot_sources(
            expectation, repository_root, worktree_roots
        )
        entry["manifest_sha256"] = manifest_hash
        bundle = build_blocked_pilot_bundle(recovery, entry)
        bundle_path = output_dir / f"{paper_id}.json"
        bundle_path.write_text(
            json.dumps(bundle.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        recoveries.append(recovery.to_dict())
        paper_summaries.append(
            {
                "paper_id": paper_id,
                "status": "blocked_review",
                "recovery_status": recovery.status,
                "evidence_block_count": recovery.evidence_block_count,
                "evidence_records": len(bundle.evidence),
                "experimental_rows": 0,
                "bundle_path": bundle_path.as_posix(),
                "bundle_sha256": sha256_file(bundle_path),
            }
        )
    summary: dict[str, object] = {
        "schema_version": "pilot-recovery-manifest/v1",
        "source_manifest": manifest_path.as_posix(),
        "source_manifest_sha256": manifest_hash,
        "paid_calls": 0,
        "papers": paper_summaries,
        "recoveries": recoveries,
    }
    (output_dir / "recovery_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


__all__ = [
    "PilotArtifactExpectation",
    "PilotRecoveryResult",
    "prepare_pilot_bundles",
    "registered_worktrees",
    "recover_pilot_sources",
    "sha256_file",
]
