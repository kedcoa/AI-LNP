from pathlib import Path

from src.rag.entities import regex_candidates
from src.rag.index import HybridIndex, TfidfVectorBackend
from src.rag.guardrails import gate_packet
from src.rag.models import DocumentBlock, RetrievalQuery


def block(block_id: str, text: str) -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id, paper_id="GP-X", source_path="x.xml", source_kind="pmc_xml",
        section_path="Results", block_type="paragraph", text=text, char_start=0,
        char_end=len(text), parser="test", parser_confidence=1.0,
    )


def test_hybrid_retrieval_finds_cell_specific_evidence(tmp_path: Path):
    blocks = [
        block("B1", "MC3 DSPC cholesterol and DMG-PEG2000 were mixed at 50:10:38.5:1.5."),
        block("B2", "Kupffer cells showed rapid LNP uptake but no EGFP translation."),
        block("B3", "Hepatocytes expressed EGFP after intravenous mRNA-LNP."),
    ]
    entities = regex_candidates(blocks)
    index = HybridIndex(tmp_path / "rag.sqlite", TfidfVectorBackend())
    index.build(blocks, entities)
    packet = index.retrieve(RetrievalQuery(
        query_id="Q1", paper_id="GP-X",
        question="What happened after LNP delivery to Kupffer cells?",
        field_group="recipient_cell", required_entity_types=["cell", "lnp"],
    ), k=2)
    assert packet.hits[0].block_id == "B2"


def test_cell_candidates_are_separate():
    blocks = [block("B1", "LNPs reached hepatocytes, endothelial cells, and Kupffer cells.")]
    values = [row.text.lower() for row in regex_candidates(blocks) if row.entity_type == "cell"]
    assert "hepatocytes" in values
    assert "endothelial cells" in values
    assert "kupffer cells" in values


def test_evidence_gate_rejects_single_hit():
    index = HybridIndex(Path("/tmp/test-rag-gate.sqlite"), TfidfVectorBackend())
    blocks = [block("B1", "LNPs reached hepatocytes.")]
    index.build(blocks, regex_candidates(blocks))
    packet = index.retrieve(RetrievalQuery(
        query_id="Q2", paper_id="GP-X", question="Where did LNPs go?",
        field_group="recipient_cell", required_entity_types=["lnp", "cell"],
    ), k=1)
    gate = gate_packet(packet)
    assert not gate.passed
    assert "Only 1 evidence block" in gate.reasons[0]
