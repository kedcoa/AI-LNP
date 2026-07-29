"""Materialize v1.2 atomic claims and candidates for local evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.extraction.assign_atomic_claims import assign_claims
from src.extraction.atomize_outcome_claims import atomize
from src.extraction.build_atomic_candidates_v12 import build_atomic_candidates
from src.extraction.build_provisional_experiments import (
    OUTPUT_ROOT as INVENTORY_ROOT,
    PACKET_ROOT,
    load_full_view,
)
from src.extraction.v12_structure_contracts import (
    ProvisionalExperimentInventoryV12,
)
from src.extraction.select_atomic_candidates_v12 import select_candidates


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data/staging/extraction/v12_atomic_inventory"


def _write(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_paper(
    paper_id: str,
    *,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    packet = load_full_view(paper_id)
    inventory = ProvisionalExperimentInventoryV12.model_validate_json(
        (INVENTORY_ROOT / paper_id / "inventory.json").read_text(
            encoding="utf-8"
        )
    )
    raw_claims = atomize(packet)
    assigned_claims, diagnostics = assign_claims(
        raw_claims,
        inventory,
        packet=packet,
    )
    candidates = build_atomic_candidates(paper_id, assigned_claims)
    selected_candidates, selection_audit = select_candidates(candidates)
    destination = output_root / paper_id
    destination.mkdir(parents=True, exist_ok=True)
    _write(
        destination / "claims.json",
        [row.model_dump(mode="json") for row in assigned_claims],
    )
    _write(destination / "assignment_diagnostics.json", diagnostics)
    _write(
        destination / "candidates.json",
        [row.model_dump(mode="json") for row in candidates],
    )
    _write(
        destination / "selected_candidates.json",
        [row.model_dump(mode="json") for row in selected_candidates],
    )
    _write(destination / "selection_audit.json", selection_audit)
    manifest = {
        "inventory_version": "atomic-outcome-inventory-1.2.0",
        "paper_id": paper_id,
        "source_packet_checksum": packet.packet_checksum,
        "raw_claim_count": len(raw_claims),
        "assigned_claim_count": sum(
            row.provisional_experiment_id is not None
            for row in assigned_claims
        ),
        "unassigned_claim_count": sum(
            row.provisional_experiment_id is None
            for row in assigned_claims
        ),
        "atomic_candidate_count": len(candidates),
        "selected_candidate_count": len(selected_candidates),
        "high_confidence_candidate_count": sum(
            row.confidence == "high" for row in candidates
        ),
        "review_candidate_count": sum(
            row.confidence == "medium" for row in candidates
        ),
        "paid_api_requests": 0,
    }
    _write(destination / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    args = parser.parse_args()
    paper_ids = args.paper_id or sorted(
        path.stem for path in PACKET_ROOT.glob("GP-*.json")
    )
    manifests = [run_paper(paper_id) for paper_id in paper_ids]
    print(json.dumps({"papers": manifests}, indent=2))


if __name__ == "__main__":
    main()
