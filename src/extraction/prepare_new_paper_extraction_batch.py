"""Prepare immutable compact extraction requests for retrieved new papers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.extraction.preflight_compact_requests import preflight_primary_request
from src.rag.compact_api_packet import build_api_packet
from src.rag.compact_packet import build_packet, write_packet
from src.rag.entities import regex_candidates
from src.rag.extraction_bridge import blocked_fields, retrieve_extraction_input
from src.rag.index import HybridIndex, TfidfVectorBackend
from src.rag.models import DocumentBlock


def _load_blocks(path: Path) -> list[DocumentBlock]:
    return [
        DocumentBlock.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def prepare_extraction_batch(
    retrieval_manifest_path: Path,
    output_root: Path,
    *,
    model: str,
) -> dict[str, Any]:
    """Build signed exact requests locally without dispatching provider calls."""

    retrieval_manifest_path = Path(retrieval_manifest_path).resolve()
    manifest = json.loads(retrieval_manifest_path.read_text(encoding="utf-8"))
    source_rows = [
        row for row in manifest.get("papers", [])
        if row.get("status") == "source_ingested" and row.get("block_path")
    ]
    if not source_rows:
        raise ValueError("retrieval manifest has no source-ingested papers")
    output_root = Path(output_root).resolve()
    retrieval_root = output_root / "retrieval_packets"
    compact_root = output_root / "compact_packets"
    api_root = output_root / "compact_api_packets"
    request_root = output_root / "requests"
    for path in (retrieval_root, compact_root, api_root, request_root):
        path.mkdir(parents=True, exist_ok=True)

    blocks_by_paper: dict[str, list[DocumentBlock]] = {}
    all_blocks: list[DocumentBlock] = []
    for row in source_rows:
        paper_id = str(row["candidate_id"])
        blocks = _load_blocks(Path(str(row["block_path"])))
        if not blocks:
            continue
        blocks_by_paper[paper_id] = blocks
        all_blocks.extend(blocks)
    if not all_blocks:
        raise ValueError("source-ingested papers contain no document blocks")

    index = HybridIndex(output_root / "retrieval_index.sqlite", TfidfVectorBackend())
    index.build(all_blocks, regex_candidates(all_blocks))
    requests: list[dict[str, Any]] = []
    for paper_id in sorted(blocks_by_paper):
        extraction_input = retrieve_extraction_input(index, paper_id, k=10)
        blocked = blocked_fields(extraction_input)
        retrieval_payload = {
            "paper_id": paper_id,
            "packets": {
                field: packet.model_dump(mode="json")
                for field, packet in extraction_input.packets.items()
            },
            "blocked_fields": blocked,
            "ready_for_extraction": not blocked,
            "source": "new-paper-source-blocks",
        }
        retrieval_path = retrieval_root / f"{paper_id}.json"
        retrieval_path.write_text(
            json.dumps(retrieval_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        compact_packet = build_packet(
            retrieval_path,
            corpus_root=Path(str(next(
                row["block_path"] for row in source_rows
                if row["candidate_id"] == paper_id
            ))).parent,
            boundary_root=output_root / "no_paper_specific_boundaries",
        )
        write_packet(compact_packet, compact_root)
        api_packet, selection_manifest = build_api_packet(compact_packet)
        api_path = api_root / f"{paper_id}.json"
        api_path.write_text(
            json.dumps(
                api_packet.model_dump(mode="json", exclude_none=True),
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        (api_root / f"{paper_id}.manifest.json").write_text(
            json.dumps(selection_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        preflight = preflight_primary_request(
            paper_id,
            model=model,
            packet_root=api_root,
            output_root=request_root,
        )
        requests.append(
            {
                "paper_id": paper_id,
                "request_path": preflight["request_path"],
                "request_sha256": preflight["request_sha256"],
                "request_bytes": preflight["request_bytes"],
                "estimated_input_tokens": preflight["estimated_input_tokens"],
                "max_output_tokens": preflight["max_output_tokens"],
                "evidence_items": len(api_packet.evidence),
                "blocked_fields": sorted(retrieval_payload["blocked_fields"]),
            }
        )

    report = {
        "schema_version": "new-paper-extraction-preflight/v1",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_exact_hash_approval",
        "model": model,
        "source_ingested_papers": len(blocks_by_paper),
        "request_count": len(requests),
        "requests": requests,
        "estimated_input_tokens": sum(
            int(row["estimated_input_tokens"]) for row in requests
        ),
        "max_output_tokens": sum(int(row["max_output_tokens"]) for row in requests),
        "provider_calls": 0,
    }
    (output_root / "preflight_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-terra")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(prepare_extraction_batch(
        args.retrieval_manifest,
        args.output_root,
        model=args.model,
    ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["prepare_extraction_batch"]
