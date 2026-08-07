from __future__ import annotations

import json
from pathlib import Path

from src.extraction.prepare_new_paper_extraction_batch import (
    prepare_extraction_batch,
)
from src.rag.models import DocumentBlock


def test_source_blocks_become_immutable_zero_call_extraction_request(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    text = (
        "Mice received 1 mg/kg luciferase mRNA LNP intravenously. The LNP "
        "contained ionizable lipid, DSPC, cholesterol, and PEG-lipid at a "
        "50:10:38.5:1.5 molar ratio. Hepatocyte expression increased 5-fold "
        "at 24 hours by luminescence assay."
    )
    block = DocumentBlock(
        block_id="candidate_00001-B-1",
        paper_id="candidate_00001",
        source_path="article.nxml",
        source_kind="pmc_xml",
        section_path="Methods and Results",
        block_type="paragraph",
        text=text,
        char_end=len(text),
        parser="fixture",
        parser_confidence=1.0,
    )
    block_path = corpus / "candidate_00001.blocks.jsonl"
    block_path.write_text(block.model_dump_json() + "\n", encoding="utf-8")
    retrieval_manifest = tmp_path / "retrieval_manifest.json"
    retrieval_manifest.write_text(
        json.dumps({
            "papers": [{
                "candidate_id": "candidate_00001",
                "status": "source_ingested",
                "block_path": str(block_path),
            }]
        }),
        encoding="utf-8",
    )

    report = prepare_extraction_batch(
        retrieval_manifest,
        tmp_path / "extraction",
        model="gpt-5.6-terra",
    )

    assert report["status"] == "awaiting_exact_hash_approval"
    assert report["provider_calls"] == 0
    assert report["request_count"] == 1
    request = report["requests"][0]
    assert len(request["request_sha256"]) == 64
    assert Path(request["request_path"]).is_file()
    assert request["evidence_items"] >= 1
    retrieval = json.loads(
        (tmp_path / "extraction/retrieval_packets/candidate_00001.json")
        .read_text(encoding="utf-8")
    )
    assert retrieval["ready_for_extraction"] == (not retrieval["blocked_fields"])
