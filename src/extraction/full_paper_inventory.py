"""Build a local evidence inventory from source-native full-paper structure."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

import fitz
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FullPaperEvidenceBlock(StrictModel):
    """One normalized local source block with deterministic provenance."""

    evidence_id: str
    page_number: int = Field(ge=1)
    heading: str
    text: str = Field(min_length=1)
    retrieval_tags: list[str]


class CategoryCoverageDiagnostic(StrictModel):
    """Local evidence coverage for one required semantic category."""

    category: str
    status: Literal["covered", "missing"]
    evidence_ids: list[str]
    evidence_ids_by_tag: dict[str, list[str]]
    message: str


class FullPaperEvidenceInventory(StrictModel):
    """Generic, local-only evidence retained from a full-paper source."""

    inventory_version: Literal["full-paper-evidence-1.0.0"] = (
        "full-paper-evidence-1.0.0"
    )
    paper_id: str
    source_pdf: str
    evidence_blocks: list[FullPaperEvidenceBlock]
    coverage_diagnostics: list[CategoryCoverageDiagnostic]
    missing_categories: list[str]

    @property
    def evidence(self) -> list[FullPaperEvidenceBlock]:
        """Compatibility-friendly name for the retained evidence blocks."""
        return self.evidence_blocks


_TAG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("formulation", re.compile(r"\bformulat\w*\b", re.IGNORECASE)),
    (
        "preparation_method",
        re.compile(
            r"\b(?:prepar\w*|mix\w*|assembl\w*|manufactur\w*|synthes\w*|"
            r"sonicat\w*|extrud\w*|dialyz\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "component_ratio",
        re.compile(
            r"\b(?:component|composition|ratio|molar|mole|weight|mass|volume)\b"
            r"|\b\d+(?:\.\d+)?\s*[:/]\s*\d+",
            re.IGNORECASE,
        ),
    ),
    (
        "ratio_basis",
        re.compile(
            r"\b(?:molar|mole|weight|mass|volume)\b|\b(?:mol|wt|vol)\s*%|"
            r"\b[wv]/[wv]\b",
            re.IGNORECASE,
        ),
    ),
    (
        "payload",
        re.compile(
            r"\b(?:payload|rna|dna|oligonucleotid\w*|nucleic acid|protein|"
            r"peptide|cargo|reporter)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "model",
        re.compile(
            r"\b(?:model|in vivo|in vitro|animal|cohort|participant|patient|"
            r"culture|organoid)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "species",
        re.compile(
            r"\b(?:species|rodent|mouse|mice|rat|rabbit|primate|human|"
            r"porcine|canine|murine)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "route",
        re.compile(
            r"\b(?:route|administ\w*|inject\w*|intravenous|intramuscular|"
            r"subcutaneous|oral|inhal\w*|topical)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cell",
        re.compile(
            r"\b(?:cell|cells|cell line|primary cells?|tissue)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "outcome",
        re.compile(
            r"\b(?:outcome|result|increase\w*|decrease\w*|reduce\w*|"
            r"improve\w*|express\w*|deliver\w*|uptake|activity|efficacy|"
            r"survival|response|toxicity)\b|\b\d+(?:\.\d+)?\s*(?:%|fold)\b",
            re.IGNORECASE,
        ),
    ),
)

_COVERAGE_REQUIREMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("formulation_preparation", ("formulation", "preparation_method")),
    ("component_ratios", ("component_ratio", "ratio_basis")),
    ("payload", ("payload",)),
    (
        "model_species_route_cell",
        ("model", "species", "route", "cell"),
    ),
    ("outcomes", ("outcome",)),
)

_HTML_SUFFIXES = frozenset({".htm", ".html", ".xhtml"})
_HTML_CONTENT_TAGS = frozenset({"p", "li", "caption", "figcaption", "tr"})
_DOCLING_HEADING_LABELS = frozenset({"section_header", "title"})
_DOCLING_IGNORED_LABELS = frozenset(
    {"page_footer", "page_header", "picture"}
)


def normalize_block_text(text: str) -> str:
    """Normalize extraction whitespace without changing reported facts."""
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def retrieval_tags(text: str) -> list[str]:
    """Return generic semantic categories supported by the text itself."""
    return [tag for tag, pattern in _TAG_PATTERNS if pattern.search(text)]


def _heading_path(values: list[str]) -> str:
    return " > ".join(values) if values else "Unsectioned"


def _replace_heading(
    heading_path: list[str],
    *,
    level: int,
    text: str,
) -> None:
    """Replace a source-native heading and retain any available ancestors."""
    parent_count = max(level - 1, 0)
    del heading_path[parent_count:]
    heading_path.append(text)


class _FullPaperHTMLParser(HTMLParser):
    """Collect source blocks while respecting native HTML heading levels."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[tuple[int, str, str]] = []
        self._headings: list[str] = []
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._capture_tag: str | None = None
        self._capture_parts: list[str] = []
        self._nested_capture_tags = 0
        self._table_cell_depth = 0
        self._table_cells_seen = 0
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        tag = tag.casefold()
        if tag in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._heading_tag = tag
            self._heading_parts = []
            return
        if self._capture_tag is None and tag in _HTML_CONTENT_TAGS:
            self._capture_tag = tag
            self._capture_parts = []
            self._nested_capture_tags = 0
            self._table_cell_depth = 0
            self._table_cells_seen = 0
            return
        if self._capture_tag is not None:
            if tag == self._capture_tag:
                self._nested_capture_tags += 1
            if self._capture_tag == "tr" and tag in {"td", "th"}:
                if self._table_cells_seen:
                    self._capture_parts.append(" | ")
                self._table_cells_seen += 1
                self._table_cell_depth += 1
            elif tag == "br":
                self._capture_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == self._heading_tag:
            text = normalize_block_text("".join(self._heading_parts))
            if text:
                _replace_heading(
                    self._headings,
                    level=int(tag[1]),
                    text=text,
                )
            self._heading_tag = None
            self._heading_parts = []
            return
        if self._capture_tag == "tr" and tag in {"td", "th"}:
            self._table_cell_depth = max(0, self._table_cell_depth - 1)
        if tag != self._capture_tag:
            return
        if self._nested_capture_tags:
            self._nested_capture_tags -= 1
            return
        text = normalize_block_text("".join(self._capture_parts))
        if text:
            self.records.append((1, _heading_path(self._headings), text))
        self._capture_tag = None
        self._capture_parts = []
        self._table_cell_depth = 0
        self._table_cells_seen = 0

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._heading_tag is not None:
            self._heading_parts.append(data)
        elif self._capture_tag == "tr":
            if self._table_cell_depth:
                self._capture_parts.append(data)
        elif self._capture_tag is not None:
            self._capture_parts.append(data)


def _html_records(source_path: Path) -> list[tuple[int, str, str]]:
    parser = _FullPaperHTMLParser()
    parser.feed(source_path.read_text(encoding="utf-8"))
    parser.close()
    return parser.records


def _resolve_json_pointer(
    document: dict[str, Any],
    reference: str,
) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"Unsupported Docling reference: {reference}")
    value: Any = document
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    if not isinstance(value, dict):
        raise ValueError(f"Docling reference does not resolve to an item: {reference}")
    return value


def _iter_docling_items(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Traverse Docling body/group references in their native document order."""
    body = document.get("body")
    if isinstance(body, dict) and isinstance(body.get("children"), list):
        active_groups: set[str] = set()

        def walk(raw: Any) -> Iterator[dict[str, Any]]:
            if not isinstance(raw, dict):
                return
            reference = raw.get("$ref")
            item = (
                _resolve_json_pointer(document, reference)
                if isinstance(reference, str)
                else raw
            )
            children = item.get("children")
            if isinstance(children, list):
                group_id = str(item.get("self_ref", reference or id(item)))
                if group_id in active_groups:
                    raise ValueError(f"Cyclic Docling group reference: {group_id}")
                active_groups.add(group_id)
                for child in children:
                    yield from walk(child)
                active_groups.remove(group_id)
                return
            yield item

        for child in body["children"]:
            yield from walk(child)
        return

    text_items = document.get("texts")
    if not isinstance(text_items, list):
        text_items = document.get("text_items", [])
    for item in text_items:
        if isinstance(item, dict):
            yield item
    for item in document.get("tables", []):
        if isinstance(item, dict):
            yield item


def _docling_page_number(item: dict[str, Any]) -> int:
    provenance = item.get("prov")
    if isinstance(provenance, list) and provenance:
        page_number = provenance[0].get("page_no", 1)
    else:
        page_number = item.get("page_in_crop", item.get("page_no", 1))
    return max(1, int(page_number))


def _docling_table_rows(item: dict[str, Any]) -> list[str]:
    cells = item.get("data", {}).get("table_cells", [])
    if not isinstance(cells, list):
        return []
    rows: dict[int, list[tuple[int, str]]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        text = normalize_block_text(str(cell.get("text", "")))
        if not text:
            continue
        row = int(cell.get("start_row_offset_idx", 0))
        column = int(cell.get("start_col_offset_idx", 0))
        rows.setdefault(row, []).append((column, text))
    return [
        " | ".join(text for _, text in sorted(row_cells))
        for _, row_cells in sorted(rows.items())
    ]


def _docling_records(docling_path: Path) -> list[tuple[int, str, str]]:
    document = json.loads(docling_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Docling JSON root must be an object")
    records: list[tuple[int, str, str]] = []
    headings: list[str] = []
    for item in _iter_docling_items(document):
        label = str(item.get("label", "text")).casefold()
        text = normalize_block_text(str(item.get("text", "")))
        if label in _DOCLING_HEADING_LABELS:
            if text:
                level = 1 if label == "title" else max(1, int(item.get("level", 1)))
                _replace_heading(headings, level=level, text=text)
            continue
        if label in _DOCLING_IGNORED_LABELS:
            continue
        page_number = _docling_page_number(item)
        if label == "table" or (not text and "table_cells" in item.get("data", {})):
            for row_text in _docling_table_rows(item):
                records.append((page_number, _heading_path(headings), row_text))
            continue
        if not text:
            continue
        if label == "list_item":
            marker = normalize_block_text(str(item.get("marker", "")))
            if marker and not text.startswith(marker):
                text = f"{marker} {text}"
        records.append((page_number, _heading_path(headings), text))
    return records


def _raw_pdf_records(source_path: Path) -> list[tuple[int, str, str]]:
    """Retain every raw selectable block without guessing document structure."""
    records: list[tuple[int, str, str]] = []
    with fitz.open(source_path) as document:
        for page_number, page in enumerate(document, start=1):
            heading = f"Unsectioned (page {page_number})"
            for block in page.get_text("blocks", sort=True):
                text = normalize_block_text(str(block[4]))
                if text:
                    records.append((page_number, heading, text))
    return records


def _evidence_id(
    paper_id: str,
    page_number: int,
    block_ordinal: int,
    heading: str,
    text: str,
) -> str:
    payload = "\0".join(
        (paper_id, str(page_number), str(block_ordinal), heading, text)
    )
    return "FPE-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _coverage_diagnostics(
    evidence_blocks: list[FullPaperEvidenceBlock],
) -> tuple[list[CategoryCoverageDiagnostic], list[str]]:
    diagnostics: list[CategoryCoverageDiagnostic] = []
    missing_categories: list[str] = []
    for category, required_tags in _COVERAGE_REQUIREMENTS:
        evidence_ids_by_tag = {
            tag: [
                block.evidence_id
                for block in evidence_blocks
                if tag in block.retrieval_tags
            ]
            for tag in required_tags
        }
        evidence_ids = [
            block.evidence_id
            for block in evidence_blocks
            if any(tag in block.retrieval_tags for tag in required_tags)
        ]
        if all(evidence_ids_by_tag.values()):
            diagnostics.append(
                CategoryCoverageDiagnostic(
                    category=category,
                    status="covered",
                    evidence_ids=evidence_ids,
                    evidence_ids_by_tag=evidence_ids_by_tag,
                    message="Local source evidence was retained for this category.",
                )
            )
        else:
            missing_categories.append(category)
            diagnostics.append(
                CategoryCoverageDiagnostic(
                    category=category,
                    status="missing",
                    evidence_ids=evidence_ids,
                    evidence_ids_by_tag=evidence_ids_by_tag,
                    message="One or more required tags lack local source evidence.",
                )
            )
    return diagnostics, missing_categories


def build_full_paper_evidence(
    paper_id: str,
    source_path: Path,
    *,
    docling_path: Path | None = None,
) -> FullPaperEvidenceInventory:
    """Inventory a full paper locally, preferring source-native structure."""
    source_path = Path(source_path)
    if source_path.suffix.casefold() in _HTML_SUFFIXES:
        records = _html_records(source_path)
    elif docling_path is not None:
        records = _docling_records(Path(docling_path))
    else:
        records = _raw_pdf_records(source_path)

    evidence_blocks = [
        FullPaperEvidenceBlock(
            evidence_id=_evidence_id(
                paper_id,
                page_number,
                block_ordinal,
                heading,
                text,
            ),
            page_number=page_number,
            heading=heading,
            text=text,
            retrieval_tags=retrieval_tags(text),
        )
        for block_ordinal, (page_number, heading, text) in enumerate(
            records,
            start=1,
        )
    ]
    diagnostics, missing_categories = _coverage_diagnostics(evidence_blocks)
    return FullPaperEvidenceInventory(
        paper_id=paper_id,
        source_pdf=source_path.name,
        evidence_blocks=evidence_blocks,
        coverage_diagnostics=diagnostics,
        missing_categories=missing_categories,
    )
