from __future__ import annotations

import argparse
import json
from pathlib import Path

from .entities import regex_candidates, scispacy_candidates
from .extraction_bridge import blocked_fields, retrieve_extraction_input
from .index import FaissSentenceTransformerBackend, HybridIndex, load_blocks


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "staging" / "rag" / "gold_v1"
PACKETS = ROOT / "data" / "staging" / "rag" / "retrieval_packets"


def run(paper_ids: list[str], output_dir: Path = PACKETS) -> dict:
    blocks = load_blocks(CORPUS)
    entities = regex_candidates(blocks) + scispacy_candidates(blocks)
    index = HybridIndex(CORPUS / "ai_lnp_hybrid.sqlite", FaissSentenceTransformerBackend())
    index.build(blocks, entities)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {"papers": {}, "model_calls": 0}
    for paper_id in paper_ids:
        value = retrieve_extraction_input(index, paper_id)
        failures = blocked_fields(value)
        payload = {
            "paper_id": paper_id,
            "packets": {
                field: packet.model_dump() for field, packet in value.packets.items()
            },
            "blocked_fields": failures,
            "ready_for_extraction": not failures,
            "important": (
                "These are source evidence packets, not extracted answers. "
                "Experiment-scoped LLM extraction may run only for unblocked fields."
            ),
        }
        path = output_dir / f"{paper_id}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n")
        summary["papers"][paper_id] = {
            "ready_for_extraction": not failures,
            "blocked_fields": sorted(failures),
            "packet_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        }
    (output_dir / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    parser.add_argument("--output-dir", type=Path, default=PACKETS)
    args = parser.parse_args()
    selected = args.paper_id or [f"GP-{number:03d}" for number in range(1, 10)]
    print(json.dumps(run(selected, args.output_dir), indent=2))
