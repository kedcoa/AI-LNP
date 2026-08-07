"""Lightweight path resolution for the authoritative evidence database."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def resolve_common_checkout_root(checkout_root: Path | str) -> Path:
    """Resolve the main checkout from Git metadata without invoking Git."""

    checkout = Path(checkout_root).resolve()
    dot_git = checkout / ".git"
    if dot_git.is_dir():
        return checkout
    if not dot_git.is_file():
        raise RuntimeError(f"Missing Git metadata at {dot_git}")
    lines = dot_git.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1 or not lines[0].startswith("gitdir: "):
        raise RuntimeError(f"Malformed worktree .git file: {dot_git}")
    raw_git_dir = lines[0].removeprefix("gitdir: ").strip()
    if not raw_git_dir:
        raise RuntimeError(f"Malformed worktree .git file: {dot_git}")
    git_dir = Path(raw_git_dir)
    if not git_dir.is_absolute():
        git_dir = dot_git.parent / git_dir
    git_dir = git_dir.resolve()
    commondir_file = git_dir / "commondir"
    if not commondir_file.is_file():
        raise RuntimeError(f"Missing worktree commondir: {commondir_file}")
    common_text = commondir_file.read_text(encoding="utf-8").strip()
    if not common_text:
        raise RuntimeError(f"Malformed worktree commondir: {commondir_file}")
    common_git = Path(common_text)
    if not common_git.is_absolute():
        common_git = git_dir / common_git
    common_git = common_git.resolve()
    if (
        common_git.name != ".git"
        or not common_git.is_dir()
        or len(git_dir.parents) < 2
        or git_dir.parents[1] != common_git
    ):
        raise RuntimeError(
            "Worktree commondir does not resolve to a common .git directory: "
            f"{commondir_file}"
        )
    return common_git.parent.resolve()


COMMON_CHECKOUT_ROOT = resolve_common_checkout_root(REPOSITORY_ROOT)
CANONICAL_AUTHORITATIVE_DATABASE = (
    COMMON_CHECKOUT_ROOT / "data/curated/lnp_evidence.db"
).resolve()


__all__ = [
    "CANONICAL_AUTHORITATIVE_DATABASE",
    "COMMON_CHECKOUT_ROOT",
    "REPOSITORY_ROOT",
    "resolve_common_checkout_root",
]
