"""Export the v7 compact extraction response as versioned JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

from .compact_contracts import CompactExtractionResponse


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = (
    ROOT
    / "docs"
    / "extraction"
    / "schemas"
    / "compact_v1"
    / "compact_extraction_response.schema.json"
)


def export() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            CompactExtractionResponse.model_json_schema(),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return OUTPUT


if __name__ == "__main__":
    print(export().relative_to(ROOT))
