from __future__ import annotations

import asyncio
import csv
import json
import os
import time
from pathlib import Path

from paperqa import Docs, Settings

from .benchmark import EVIDENCE, OUTPUT, question_for
from .index import load_blocks


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "staging" / "rag" / "gold_v1"
PAPERQA_ROOT = CORPUS / "paperqa"


def export_documents() -> dict[str, Path]:
    """Create one provenance-marked plain-text document per paper."""
    PAPERQA_ROOT.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list] = {}
    for block in load_blocks(CORPUS):
        grouped.setdefault(block.paper_id, []).append(block)
    paths = {}
    for paper_id, blocks in sorted(grouped.items()):
        path = PAPERQA_ROOT / f"{paper_id}.txt"
        sections = []
        for block in blocks:
            sections.append(
                f"[BLOCK_ID={block.block_id}] [SECTION={block.section_path}] "
                f"[SOURCE={block.source_path}] [PAGE={block.page_number or 'n/a'}] "
                f"[XML_ID={block.xml_element_id or 'n/a'}]\n{block.text}"
            )
        path.write_text("\n\n".join(sections) + "\n")
        paths[paper_id] = path
    return paths


def fixed_queries() -> dict[str, str]:
    """Exactly one predeclared question per gold paper to cap model cost."""
    rows = list(csv.DictReader(EVIDENCE.open(encoding="utf-8", newline="")))
    selected = {}
    for row in rows:
        selected.setdefault(row["gold_paper_id"], question_for(row))
    return selected


def settings() -> Settings:
    model = os.getenv("RAG_LLM_MODEL", "openai/deepseek-v4-flash")
    base = os.environ["SENSENOVA_BASE_URL"]
    key = os.environ["SENSENOVA_API_KEY"]
    # LiteLLM reads OpenAI-compatible credentials for models prefixed by openai/.
    os.environ["OPENAI_API_KEY"] = key
    os.environ["OPENAI_API_BASE"] = base
    return Settings(
        llm=model,
        summary_llm=model,
        embedding="st-multi-qa-MiniLM-L6-cos-v1",
        parsing={"use_doc_details": False},
        answer={
            "evidence_k": 3,
            "answer_max_sources": 3,
            "max_concurrent_requests": 1,
        },
    )


async def run() -> dict:
    paths = export_documents()
    queries = fixed_queries()
    config = settings()
    output_path = OUTPUT / "paperqa2_gold_v1.json"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    existing = json.loads(output_path.read_text()) if output_path.exists() else {}
    results = existing.get("results", [])
    completed = {row["paper_id"] for row in results}
    for paper_id in sorted(paths):
        if paper_id in completed:
            continue
        docs = Docs()
        await docs.aadd(
            paths[paper_id],
            citation=f"{paper_id} full text",
            docname=paper_id,
            settings=config,
        )
        session = await docs.aquery(queries[paper_id], settings=config)
        contexts = [
            {
                "text": context.context,
                "score": context.score,
                "citation": context.text.name,
            }
            for context in session.contexts
        ]
        cited_ids = sorted({
            token.split("]", 1)[0]
            for context in contexts
            for token in context["text"].split("[BLOCK_ID=")[1:]
            if "]" in token
        })
        results.append({
            "paper_id": paper_id,
            "question": queries[paper_id],
            "answer": session.answer,
            "contexts": contexts,
            "cited_block_ids": cited_ids,
            "has_provenance_citation": bool(cited_ids),
        })
        checkpoint = {
            "system": "PaperQA2",
            "status": "in_progress",
            "papers": len(results),
            "model": os.getenv("RAG_LLM_MODEL", "openai/deepseek-v4-flash"),
            "embedding": "st-multi-qa-MiniLM-L6-cos-v1",
            "results": results,
        }
        output_path.write_text(json.dumps(checkpoint, indent=2) + "\n")
        time.sleep(float(os.getenv("PAPERQA_INTER_PAPER_DELAY", "15")))
    report = {
        "system": "PaperQA2",
        "papers": len(results),
        "model": os.getenv("RAG_LLM_MODEL", "openai/deepseek-v4-flash"),
        "embedding": "st-multi-qa-MiniLM-L6-cos-v1",
        "results": results,
        "warning": "Answers are candidates only; human scientific verification remains required.",
    }
    report["status"] = "complete"
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
