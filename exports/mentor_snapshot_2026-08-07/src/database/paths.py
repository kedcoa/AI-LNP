"""Portable snapshot path constants."""
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMON_CHECKOUT_ROOT = REPOSITORY_ROOT
CANONICAL_AUTHORITATIVE_DATABASE = REPOSITORY_ROOT / "lnp_evidence.db"
