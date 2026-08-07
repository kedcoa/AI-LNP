from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from .models import DocumentBlock


ROOT = Path(__file__).resolve().parents[2]
GOLD_PAPERS = ROOT / "data" / "annotations" / "gold_v1" / "papers.csv"
XML_ROOT = ROOT / "data" / "raw" / "fulltext" / "gold_v1" / "xml"
OA_ROOT = ROOT / "data" / "raw" / "fulltext" / "oa_packages"
CORPUS_ROOT = ROOT / "data" / "staging" / "rag" / "gold_v1"


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def element_text(element: ET.Element) -> str:
    return compact("".join(element.itertext()))


def stable_id(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode()).hexdigest()[:20]


def gold_manifest() -> list[dict[str, str]]:
    with GOLD_PAPERS.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def find_xml(candidate_id: str, pmcid: str) -> Path:
    package_xml = sorted((OA_ROOT / pmcid).glob("*.nxml"))
    if package_xml:
        return package_xml[0]
    matches = sorted(XML_ROOT.glob(f"{candidate_id}_{pmcid}.xml"))
    if not matches:
        raise FileNotFoundError(f"No PMC XML for {candidate_id} {pmcid}")
    return matches[0]


def section_title(sec: ET.Element, fallback: str) -> str:
    title = next((child for child in sec if local_name(child.tag) == "title"), None)
    return element_text(title) if title is not None else fallback


def xml_blocks(paper_id: str, path: Path) -> list[DocumentBlock]:
    root = ET.fromstring(path.read_bytes())
    rows: list[DocumentBlock] = []
    seen: set[int] = set()

    def add(element: ET.Element, block_type: str, section: str, **metadata):
        text = element_text(element)
        if not text or id(element) in seen:
            return
        seen.add(id(element))
        block_id = f"{paper_id}-B-{stable_id(str(path), section, block_type, text)}"
        rows.append(DocumentBlock(
            block_id=block_id, paper_id=paper_id,
            source_path=(
                str(path.relative_to(ROOT)) if path.is_relative_to(ROOT)
                else str(path)
            ),
            source_kind="pmc_xml", section_path=section, block_type=block_type,
            text=text, xml_element_id=element.attrib.get("id"), char_start=0,
            char_end=len(text), parser="pmc_xml", parser_confidence=1.0, **metadata,
        ))

    for title in (element for element in root.iter() if local_name(element.tag) == "article-title"):
        add(title, "title", "Article")
        break
    for abstract in (element for element in root.iter() if local_name(element.tag) == "abstract"):
        for paragraph in (x for x in abstract.iter() if local_name(x.tag) == "p"):
            add(paragraph, "abstract", "Abstract")
        break

    body = next((element for element in root.iter() if local_name(element.tag) == "body"), None)
    if body is not None:
        def visit(container: ET.Element, parents: list[str]):
            for child in container:
                name = local_name(child.tag)
                if name == "sec":
                    heading = section_title(child, "Untitled section")
                    visit(child, parents + [heading])
                elif name == "p":
                    add(child, "paragraph", " > ".join(parents) or "Body")
                elif name == "table-wrap":
                    label = next((element_text(x) for x in child if local_name(x.tag) == "label"), "")
                    add(child, "table", " > ".join(parents) or "Body", table_number=label or None)
                elif name == "fig":
                    label = next((element_text(x) for x in child if local_name(x.tag) == "label"), "")
                    captions = [x for x in child.iter() if local_name(x.tag) == "caption"]
                    for caption in captions:
                        add(caption, "figure_caption", " > ".join(parents) or "Body", figure_number=label or None)
        visit(body, [])
    return rows


def pdf_blocks(paper_id: str, path: Path) -> list[DocumentBlock]:
    try:
        import pymupdf
    except ImportError as error:
        raise RuntimeError("PyMuPDF is required in the RAG environment") from error
    rows = []
    with pymupdf.open(path) as document:
        for page_index, page in enumerate(document):
            text = compact(page.get_text("text", sort=True))
            if not text:
                continue
            rows.append(DocumentBlock(
                block_id=f"{paper_id}-B-{stable_id(str(path), str(page_index + 1), text)}",
                paper_id=paper_id,
                source_path=(
                    str(path.relative_to(ROOT)) if path.is_relative_to(ROOT)
                    else str(path)
                ),
                section_path=f"Supplement page {page_index + 1}", block_type="pdf_page",
                text=text, page_number=page_index + 1, char_start=0, char_end=len(text),
                parser="pymupdf", parser_confidence=0.75,
            ))
    return rows


def supplement_pdfs(pmcid: str) -> Iterable[Path]:
    directory = OA_ROOT / pmcid
    if not directory.exists():
        return []
    return [
        path for path in sorted(directory.glob("*.pdf"))
        if not re.search(r"(Article_|pnas\.202534673\.pdf$|main\.pdf$)", path.name)
    ]


class GrobidClient:
    """Optional full-text parser; no service is required for PMC XML ingestion."""

    def __init__(self, base_url: str = "http://127.0.0.1:8070"):
        self.endpoint = base_url.rstrip("/") + "/api/processFulltextDocument"

    def available(self, timeout: float = 1.0) -> bool:
        try:
            with urllib.request.urlopen(self.endpoint.rsplit("/api/", 1)[0] + "/api/isalive", timeout=timeout) as response:
                return response.status == 200
        except Exception:
            return False


def build_corpus() -> dict:
    CORPUS_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {"papers": [], "grobid_available": GrobidClient().available()}
    for paper in gold_manifest():
        paper_id, candidate_id, pmcid = paper["gold_paper_id"], paper["candidate_id"], paper["pmcid"]
        xml_path = find_xml(candidate_id, pmcid)
        blocks = xml_blocks(paper_id, xml_path)
        pdf_paths = list(supplement_pdfs(pmcid))
        for pdf_path in pdf_paths:
            blocks.extend(pdf_blocks(paper_id, pdf_path))
        output = CORPUS_ROOT / f"{paper_id}.blocks.jsonl"
        with output.open("w", encoding="utf-8") as handle:
            for block in blocks:
                handle.write(block.model_dump_json() + "\n")
        manifest["papers"].append({
            "paper_id": paper_id, "pmcid": pmcid, "xml_path": str(xml_path.relative_to(ROOT)),
            "supplement_pdfs": [str(path.relative_to(ROOT)) for path in pdf_paths],
            "blocks": len(blocks), "characters": sum(len(block.text) for block in blocks),
        })
    (CORPUS_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def ingest_manifest_entry_assets(entry: dict, *, allow_network: bool = False):
    """Ingest registered current-corpus supplements through the general router."""

    from .current_corpus_assets import (
        ingest_current_corpus_assets,
        resolve_declared_supplements,
    )

    assets = resolve_declared_supplements(
        entry, root=ROOT, allow_network=allow_network
    )
    return ingest_current_corpus_assets(entry, assets)


if __name__ == "__main__":
    print(json.dumps(build_corpus(), indent=2))
