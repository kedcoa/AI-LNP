"""Export versioned JSON Schemas for LLM/API consumers."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import (
    ComponentExtraction,
    EvidenceExtraction,
    ExperimentExtraction,
    ExtractionBundle,
    FormulationExtraction,
    OutcomeExtraction,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "extraction" / "schemas" / "v1"
MODELS = {
    "formulation": FormulationExtraction,
    "component": ComponentExtraction,
    "experiment": ExperimentExtraction,
    "outcome": OutcomeExtraction,
    "evidence": EvidenceExtraction,
    "extraction_bundle": ExtractionBundle,
}


def export() -> list[Path]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in MODELS.items():
        path = OUTPUT / f"{name}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


if __name__ == "__main__":
    for output_path in export():
        print(output_path.relative_to(ROOT))
