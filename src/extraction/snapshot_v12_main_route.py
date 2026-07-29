"""Materialize v1.2 main-route support envelopes for human review."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .run_compact_one_call import load_packet
from .v12_main_route import build_v12_route_support


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data/staging/extraction/v12_main_route_support"
PACKET_MANIFEST_ROOT = ROOT / "data/staging/rag/compact_api_packets_v1"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def run(
    paper_ids: list[str],
    *,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for paper_id in paper_ids:
        support = build_v12_route_support(load_packet(paper_id))
        paper_root = output_root / paper_id
        paper_root.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(support, ensure_ascii=False, indent=2) + "\n"
        (paper_root / "support.json").write_text(serialized, encoding="utf-8")
        packet_manifest_path = PACKET_MANIFEST_ROOT / f"{paper_id}.manifest.json"
        packet_manifest = (
            json.loads(packet_manifest_path.read_text(encoding="utf-8"))
            if packet_manifest_path.exists()
            else {}
        )
        base_tokens = (
            packet_manifest.get("estimated_input_tokens", {}).get("total")
        )
        rows.append({
            "paper_id": paper_id,
            "support_sha256": hashlib.sha256(
                _canonical(support).encode("utf-8")
            ).hexdigest(),
            "estimated_tokens": support["estimated_tokens"],
            "base_estimated_input_tokens": base_tokens,
            "combined_estimated_input_tokens": (
                base_tokens + support["estimated_tokens"]
                if isinstance(base_tokens, int)
                else None
            ),
            "provisional_experiments": len(
                support["provisional_experiments"]
            ),
            "atomic_outcome_candidates": len(
                support["atomic_outcome_candidates"]
            ),
            "accepted_visual_claims": len(
                support["accepted_visual_claims"]
            ),
            "local_evidence": len(support["local_evidence"]),
        })
    manifest = {
        "snapshot_version": "main-route-support-snapshot-1.2.0",
        "papers": rows,
        "total_estimated_support_tokens": sum(
            row["estimated_tokens"] for row in rows
        ),
        "total_combined_estimated_input_tokens": sum(
            row["combined_estimated_input_tokens"]
            for row in rows
            if isinstance(row["combined_estimated_input_tokens"], int)
        ),
        "paid_api_requests": 0,
        "human_review_required_before_paid_rerun": True,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.paper_id), ensure_ascii=False, indent=2))
