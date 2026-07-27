import json
from pathlib import Path

from src.rag.compact_packet import (
    build_packet,
    normalize_text,
    sentences_are_contextually_related,
    write_packet,
)
from src.rag.models import DocumentBlock


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def hit(block_id: str, text: str, **values):
    return {
        "query_id": values.pop("query_id", "Q1"),
        "block_id": block_id,
        "paper_id": "GP-X",
        "text": text,
        "section_path": values.pop("section_path", "Results > Experiment A"),
        "source_path": values.pop("source_path", "paper.xml"),
        "page_number": values.pop("page_number", 4),
        "xml_element_id": values.pop("xml_element_id", "p1"),
        "fused_score": values.pop("fused_score", 1.0),
        "entity_types": values.pop("entity_types", ["lnp"]),
        **values,
    }


def field_packet(field: str, group: str, hits: list[dict]):
    return {
        "query": {
            "query_id": f"Q-{field}",
            "paper_id": "GP-X",
            "question": field,
            "field_group": group,
            "required_entity_types": [],
        },
        "hits": hits,
        "retrieval_methods": ["test"],
        "warnings": [],
    }


def test_packet_merges_field_tags_and_deduplicates_chunks_and_text(tmp_path: Path):
    same = "LNP-X contained a novel ionizable lipid at 50 mol%."
    duplicate_spacing = "  LNP-X contained a novel ionizable lipid at 50 mol%.  "
    retrieval = {
        "paper_id": "GP-X",
        "blocked_fields": {},
        "packets": {
            "formulation": field_packet(
                "formulation",
                "formulation",
                [hit("B1", same)],
            ),
            "payload": field_packet(
                "payload",
                "payload",
                [hit("B1", same), hit("B2", duplicate_spacing)],
            ),
        },
    }
    retrieval_path = tmp_path / "retrieval" / "GP-X.json"
    write_json(retrieval_path, retrieval)

    packet = build_packet(
        retrieval_path,
        corpus_root=tmp_path / "corpus",
        boundary_root=tmp_path / "boundaries",
    )

    assert len(packet.evidence) == 1
    assert packet.evidence[0].field_tags == ["formulation", "payload"]
    assert packet.evidence[0].chunk_ids == ["B1", "B2"]
    assert packet.deduplication.input_hits == 3
    assert packet.deduplication.removed_chunk_duplicates == 1
    assert packet.deduplication.removed_normalized_passages == 1


def test_packet_preserves_source_coordinates_and_experiment_candidate(tmp_path: Path):
    anchor = "LNP-X transfected hepatocytes in fibrotic liver."
    background = "Fibrosis is a major cause of morbidity."
    text = f"{background} {anchor}"
    retrieval = {
        "paper_id": "GP-X",
        "blocked_fields": {},
        "packets": {
            "recipient": field_packet(
                "recipient",
                "recipient_cell",
                [hit("B1", text)],
            )
        },
    }
    retrieval_path = tmp_path / "retrieval" / "GP-X.json"
    write_json(retrieval_path, retrieval)

    block = DocumentBlock(
        block_id="B1",
        paper_id="GP-X",
        source_path="supplement.pdf",
        source_kind="pdf",
        section_path="Results > Fibrosis",
        block_type="table",
        text=text,
        page_number=7,
        table_number="Table S2",
        figure_number="Figure S3",
        char_start=0,
        char_end=len(text),
        parser="pymupdf",
        parser_confidence=0.75,
    )
    corpus_path = tmp_path / "corpus" / "GP-X.blocks.jsonl"
    corpus_path.parent.mkdir(parents=True)
    corpus_path.write_text(block.model_dump_json() + "\n", encoding="utf-8")
    write_json(
        tmp_path / "boundaries" / "GP-X.json",
        {
            "experiments": [
                    {
                        "experiment_id": "GP-X-E01",
                        "experiment_anchor_quote": anchor,
                }
            ]
        },
    )

    packet = build_packet(
        retrieval_path,
        corpus_root=tmp_path / "corpus",
        boundary_root=tmp_path / "boundaries",
    )
    by_text = {row.text: row for row in packet.evidence}
    evidence = by_text[anchor]
    location = evidence.source_locations[0]
    assert evidence.experiment_candidate_ids == ["GP-X-E01"]
    assert by_text[background].experiment_candidate_ids == []
    assert location.section == "Results"
    assert location.subsection == "Fibrosis"
    assert location.page_number == 7
    assert location.table_number == "Table S2"
    assert location.figure_number == "Figure S3"


def test_neighbor_context_is_only_added_when_needed(tmp_path: Path):
    text = (
        "LNP-X was administered intravenously to mice. "
        "This produced expression. "
        "A separately reported assay measured serum chemistry."
    )
    retrieval = {
        "paper_id": "GP-X",
        "blocked_fields": {},
        "packets": {
            "outcomes": field_packet(
                "outcomes",
                "outcome",
                [hit("B1", text)],
            )
        },
    }
    retrieval_path = tmp_path / "retrieval" / "GP-X.json"
    write_json(retrieval_path, retrieval)
    packet = build_packet(
        retrieval_path,
        corpus_root=tmp_path / "corpus",
        boundary_root=tmp_path / "boundaries",
    )
    by_text = {row.text: row for row in packet.evidence}
    assert by_text["This produced expression."].context_before == (
        "LNP-X was administered intravenously to mice."
    )
    assert by_text[
        "A separately reported assay measured serum chemistry."
    ].context_before is None


def test_context_relation_detects_explicit_anaphora():
    assert sentences_are_contextually_related(
        "LNP-A delivered siRNA to hepatocytes.",
        "This formulation reduced TTR expression by 80%.",
    )


def test_context_relation_detects_shared_experiment_identifier():
    assert sentences_are_contextually_related(
        "LNP16 contained an ionizable lipid and helper lipid.",
        "LNP16 delivered mRNA to hepatocytes.",
    )


def test_context_relation_detects_continuation_and_strong_term_overlap():
    assert sentences_are_contextually_related(
        "The formulation contained the following components:",
        "MC3, DSPC, cholesterol, and PEG-lipid were mixed at a molar ratio.",
    )
    assert sentences_are_contextually_related(
        "Luciferase expression was measured in liver tissue.",
        "Luciferase expression increased after treatment.",
    )


def test_context_relation_rejects_unrelated_neighbor():
    assert not sentences_are_contextually_related(
        "LNP-A delivered siRNA to hepatocytes.",
        "Liver disease affects millions of people worldwide.",
    )
    assert not sentences_are_contextually_related(
        "Dietary lipids are absorbed in the intestine.",
        "LNP-B contained MC3 and cholesterol.",
    )


def test_evidence_ids_and_checksum_are_stable(tmp_path: Path):
    retrieval = {
        "paper_id": "GP-X",
        "blocked_fields": {},
        "packets": {
            "outcomes": field_packet(
                "outcomes",
                "outcome",
                [hit("B1", "Expression increased by 2-fold.")],
            )
        },
    }
    retrieval_path = tmp_path / "retrieval" / "GP-X.json"
    write_json(retrieval_path, retrieval)
    first = build_packet(
        retrieval_path,
        corpus_root=tmp_path / "corpus",
        boundary_root=tmp_path / "boundaries",
    )
    second = build_packet(
        retrieval_path,
        corpus_root=tmp_path / "corpus",
        boundary_root=tmp_path / "boundaries",
    )
    assert first.packet_checksum == second.packet_checksum
    assert first.evidence[0].evidence_id == second.evidence[0].evidence_id
    assert first.evidence[0].normalized_text_sha256 == (
        __import__("hashlib").sha256(
            normalize_text("Expression increased by 2-fold.").encode()
        ).hexdigest()
    )

    output = write_packet(first, tmp_path / "output")
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert "context_before" not in saved["evidence"][0]
