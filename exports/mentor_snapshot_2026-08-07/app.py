"""Portable entry point for a frozen read-only mentor snapshot."""

from __future__ import annotations

import os
from pathlib import Path


SNAPSHOT_ROOT = Path(__file__).resolve().parent
os.environ["LNP_MENTOR_SNAPSHOT_DB"] = str(
    SNAPSHOT_ROOT / "lnp_evidence.db"
)

from src.ui.evidence_browser_app import main  # noqa: E402


if __name__ == "__main__":
    main()
