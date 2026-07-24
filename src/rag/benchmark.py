from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from .entities import regex_candidates
from .index import HybridIndex, SentenceTransformerBackend, TfidfVectorBackend, load_blocks
from .models import RetrievalQuery


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "staging" / "rag" / "gold_v1"
EVIDENCE = ROOT / "data" / "annotations" / "gold_v1" / "evidence.csv"
OUTPUT = ROOT / "reports" / "rag"
DEVELOPMENT_PAPERS = {"GP-001", "GP-004", "GP-006", "GP-008"}

FIELD_QUESTIONS = {
    "composition": "What lipids and molar ratios comprise the LNP formulation?",
    "composition_and_preparation": "What is the LNP composition and how was it prepared?",
    "composition_and_manufacturing": "What is the LNP composition and manufacturing method?",
    "payload_type": "What payload is encapsulated or carried by the formulation?",
    "original_experiment_status": "Does this paper report an original tested LNP experiment?",
    "target_cell_identity": "Which specific cell type does HSC mean in this paper?",
}


def question_for(row: dict[str, str]) -> str:
    field = row["field_name"]
    if field in FIELD_QUESTIONS:
        return FIELD_QUESTIONS[field]
    words = re.sub(r"_+", " ", field)
    entity = row["supported_entity_type"]
    return f"What does the paper report for the {entity} field '{words}'?"


def field_group(row: dict[str, str]) -> str:
    field = row["field_name"].lower()
    if "composition" in field or "ratio" in field or "characterization" in field:
        return "formulation"
    if "target_cell" in field:
        return "therapeutic_target"
    if "experiment" in field or "delivery" in field or "treatment" in field:
        return "experiment_boundary"
    if "outcome" in row["supported_entity_type"] or "frequency" in field or "activity" in field:
        return "outcome"
    return "payload"


def entity_types(group: str) -> list[str]:
    return {
        "formulation": ["lnp", "lipid_or_material"],
        "payload": ["payload"],
        "experiment_boundary": ["lnp", "species"],
        "therapeutic_target": ["cell"],
        "outcome": ["outcome"],
    }.get(group, [])


def source_match(hit, row: dict[str, str]) -> bool:
    gold_path = row["xml_file"]
    gold_pmcid = re.search(r"PMC\d+", gold_path)
    hit_pmcid = re.search(r"PMC\d+", hit.source_path)
    same_source = bool(gold_path) and (
        hit.source_path == gold_path or Path(hit.source_path).name == Path(gold_path).name
        or (
            gold_pmcid
            and hit_pmcid
            and gold_pmcid.group() == hit_pmcid.group()
            and Path(gold_path).suffix.lower() in {".xml", ".nxml"}
            and Path(hit.source_path).suffix.lower() in {".xml", ".nxml"}
        )
    )
    xml_id = row["xml_element_id"].strip()
    page = row["page_number"].strip()
    exact_xml = xml_id and getattr(hit, "xml_element_id", None) == xml_id
    exact_location = (
        exact_xml
        or (page and hit.page_number == int(page))
    )
    # PMC may provide byte-different XML copies at two local paths while retaining
    # the same stable element IDs. A matching element ID within the same paper is
    # exact provenance even when the file path differs.
    return bool(exact_xml or (same_source and (exact_location or (not xml_id and not page))))


def run(backend: str = "tfidf", k: int = 8) -> dict:
    blocks = load_blocks(CORPUS)
    vector = (
        SentenceTransformerBackend()
        if backend == "sentence-transformers"
        else TfidfVectorBackend()
    )
    index = HybridIndex(CORPUS / f"benchmark-{backend}.sqlite", vector)
    index.build(blocks, regex_candidates(blocks))
    rows = list(csv.DictReader(EVIDENCE.open(encoding="utf-8", newline="")))
    results = []
    for row in rows:
        group = field_group(row)
        query = RetrievalQuery(
            query_id=row["evidence_id"],
            paper_id=row["gold_paper_id"],
            question=question_for(row),
            field_group=group,
            required_entity_types=entity_types(group),
        )
        packet = index.retrieve(query, k=k)
        ranks = [
            rank for rank, hit in enumerate(packet.hits, 1)
            if source_match(hit, row)
        ]
        results.append({
            "evidence_id": row["evidence_id"],
            "paper_id": row["gold_paper_id"],
            "field_name": row["field_name"],
            "question": query.question,
            "gold_source": row["xml_file"],
            "gold_xml_element_id": row["xml_element_id"],
            "gold_page": row["page_number"],
            "hit": bool(ranks),
            "first_gold_rank": min(ranks) if ranks else None,
            "retrieved_block_ids": [hit.block_id for hit in packet.hits],
        })
    per_paper = {}
    for paper_id in sorted({row["paper_id"] for row in results}):
        selected = [row for row in results if row["paper_id"] == paper_id]
        per_paper[paper_id] = {
            "queries": len(selected),
            "hits": sum(row["hit"] for row in selected),
            "recall_at_k": sum(row["hit"] for row in selected) / len(selected),
        }
    development = [row for row in results if row["paper_id"] in DEVELOPMENT_PAPERS]
    holdout = [row for row in results if row["paper_id"] not in DEVELOPMENT_PAPERS]
    report = {
        "backend": backend,
        "k": k,
        "queries": len(results),
        "hits": sum(row["hit"] for row in results),
        "recall_at_k": sum(row["hit"] for row in results) / len(results),
        "split_metrics": {
            "development": {
                "papers": sorted(DEVELOPMENT_PAPERS),
                "queries": len(development),
                "hits": sum(row["hit"] for row in development),
                "recall_at_k": sum(row["hit"] for row in development) / len(development),
                "used_for_tuning": True,
            },
            "holdout": {
                "papers": sorted({row["paper_id"] for row in holdout}),
                "queries": len(holdout),
                "hits": sum(row["hit"] for row in holdout),
                "recall_at_k": sum(row["hit"] for row in holdout) / len(holdout),
                "used_for_tuning": False,
            },
        },
        "per_paper": per_paper,
        "results": results,
        "limitations": [
            "Retrieval recall is not scientific correctness.",
            "A gold location hit does not prove that the answer uses the correct experiment.",
            "PDF page extraction can miss image-based tables and requires human visual review.",
            "Missing retrieval evidence must produce abstention, not an inferred value.",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"gold_v1_retrieval_{backend}.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["tfidf", "sentence-transformers"], default="tfidf")
    parser.add_argument("-k", type=int, default=6)
    args = parser.parse_args()
    print(json.dumps(run(args.backend, args.k), indent=2))
