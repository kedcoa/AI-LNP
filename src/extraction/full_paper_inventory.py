"""Build a local, generic evidence inventory from selectable PDF text."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FullPaperEvidenceBlock(StrictModel):
    """One normalized local PDF text block with deterministic provenance."""

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
    """Generic, local-only evidence retained from a full paper PDF."""

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


_HEADING_PATTERNS = (
    re.compile(
        r"^(?:\d+(?:\.\d+)*\.?\s+)?(?:abstract|introduction|background|"
        r"materials?\s+and\s+methods?|methods?|methodology|experimental(?:\s+methods?)?|"
        r"results?|findings?|discussion|conclusions?|acknowledg(?:e)?ments?|references|"
        r"supplement(?:ary)?(?:\s+materials?)?)$",
        re.IGNORECASE,
    ),
)
_NUMBERED_HEADING = re.compile(
    r"^\d+(?:\.\d+)*\.?\s+(?P<title>\S.*)$"
)
_FIGURE_OR_TABLE_LABEL = re.compile(
    r"^(?:fig(?:ure)?|table)\s+\S", re.IGNORECASE
)
_TITLE_CONNECTORS = frozenset(
    {"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to", "via", "with"}
)
_FINITE_CLAUSE_AUXILIARY = re.compile(
    r"\b(?:am|is|are|was|were|be|been|being|has|have|had|do|does|did|"
    r"will|would|shall|should|can|could|may|might|must)\b",
    re.IGNORECASE,
)
_FINITE_CLAUSE_SUBJECT_PRONOUN = re.compile(
    r"^(?:he|i|it|she|they|we|you)\b",
    re.IGNORECASE,
)
_FONT_FLAG_BOLD = 1 << 4


@dataclass(frozen=True)
class _TextStyle:
    font_size: float
    bold: bool


@dataclass(frozen=True)
class _LineLayout:
    bbox: tuple[float, float, float, float]
    style: _TextStyle


@dataclass(frozen=True)
class _BlockLayout:
    lines: tuple[_LineLayout, ...]

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
        re.compile(r"\b(?:cell|cells|cell line|primary cells?|tissue)\b", re.IGNORECASE),
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


def normalize_block_text(text: str) -> str:
    """Normalize PDF extraction whitespace without changing the reported facts."""
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def _is_heading(
    text: str,
    *,
    following_text: str = "",
    strong_layout_signal: bool = False,
) -> bool:
    if any(pattern.fullmatch(text) for pattern in _HEADING_PATTERNS):
        return True
    if (
        not text
        or _FIGURE_OR_TABLE_LABEL.match(text)
        or text.endswith((".", "?", "!"))
    ):
        return False
    numbered_heading = _NUMBERED_HEADING.fullmatch(text)
    if numbered_heading:
        return _is_numbered_heading(
            numbered_heading["title"],
            following_text,
            strong_layout_signal,
        )
    return _is_title_like_heading(text)


def _is_title_like_heading(text: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    return bool(words) and len(words) <= 12 and all(
        word.casefold() in _TITLE_CONNECTORS or word[0].isupper()
        for word in words
    )


def _is_numbered_heading(
    title: str,
    following_text: str,
    strong_layout_signal: bool,
) -> bool:
    """Use title form and source structure to identify a numbered label."""
    if _is_title_like_heading(title):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", title)
    if not words or len(words) > 12 or not words[0][0].isupper():
        return False
    following_text = normalize_block_text(following_text)
    following_is_numbered = bool(_NUMBERED_HEADING.fullmatch(following_text))
    if strong_layout_signal and following_is_numbered:
        return True
    if (
        _FINITE_CLAUSE_AUXILIARY.search(title)
        or _FINITE_CLAUSE_SUBJECT_PRONOUN.match(title)
    ):
        return False
    if strong_layout_signal:
        return True
    has_section_content = bool(following_text) and not following_is_numbered
    return has_section_content


def _dominant_text_style(spans: list[dict[str, object]]) -> _TextStyle | None:
    weights: Counter[tuple[float, bool]] = Counter()
    for span in spans:
        text = str(span.get("text", ""))
        if not text.strip():
            continue
        size = round(float(span.get("size", 0.0)), 2)
        flags = int(span.get("flags", 0))
        weights[(size, bool(flags & _FONT_FLAG_BOLD))] += len(text.strip())
    if not weights:
        return None
    (font_size, bold), _ = max(
        weights.items(),
        key=lambda item: (item[1], -item[0][0], not item[0][1]),
    )
    return _TextStyle(font_size=font_size, bold=bold)


def _page_layout(
    page: fitz.Page,
) -> tuple[dict[int, _BlockLayout], _TextStyle | None]:
    layouts: dict[int, _BlockLayout] = {}
    page_spans: list[dict[str, object]] = []
    for block in page.get_text("dict", sort=True)["blocks"]:
        if block.get("type") != 0:
            continue
        line_layouts: list[_LineLayout] = []
        for line in block.get("lines", []):
            spans = list(line.get("spans", []))
            page_spans.extend(spans)
            style = _dominant_text_style(spans)
            if style is None:
                continue
            line_layouts.append(
                _LineLayout(
                    bbox=tuple(float(value) for value in line["bbox"]),
                    style=style,
                )
            )
        if line_layouts:
            layouts[int(block["number"])] = _BlockLayout(lines=tuple(line_layouts))
    return layouts, _dominant_text_style(page_spans)


def _strong_heading_layout_signal(
    block_layout: _BlockLayout | None,
    previous_layout: _BlockLayout | None,
    following_layout: _BlockLayout | None,
    body_style: _TextStyle | None,
) -> bool:
    """Return true only for typography or geometry that distinguishes a label."""
    if block_layout is None or not block_layout.lines:
        return False
    heading_line = block_layout.lines[0]
    content_line = (
        block_layout.lines[1]
        if len(block_layout.lines) > 1
        else following_layout.lines[0]
        if following_layout and following_layout.lines
        else None
    )
    comparison_styles = [
        style
        for style in (
            content_line.style if content_line else None,
            body_style,
        )
        if style is not None
    ]
    size_deltas = [
        heading_line.style.font_size - style.font_size
        for style in comparison_styles
    ]
    clearly_larger = any(delta >= 0.75 for delta in size_deltas)
    distinctly_bold = heading_line.style.bold and any(
        not style.bold for style in comparison_styles
    )
    if clearly_larger or distinctly_bold:
        return True

    if (
        previous_layout is None
        or not previous_layout.lines
        or content_line is None
    ):
        return False
    previous_line = previous_layout.lines[-1]
    gap_before = heading_line.bbox[1] - previous_line.bbox[3]
    gap_after = content_line.bbox[1] - heading_line.bbox[3]
    line_height = max(heading_line.bbox[3] - heading_line.bbox[1], 1.0)
    section_spacing = gap_before >= max(gap_after * 1.5, line_height * 0.75)
    modestly_larger = any(delta >= 0.25 for delta in size_deltas)
    return section_spacing and modestly_larger


def _split_heading(
    block_text: str,
    current_heading: str,
    following_block_text: str = "",
    *,
    strong_layout_signal: bool = False,
) -> tuple[str, str]:
    """Use a standalone or leading conventional section heading as context."""
    lines = [normalize_block_text(line) for line in block_text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return current_heading, ""
    same_block_text = normalize_block_text(" ".join(lines[1:]))
    if _is_heading(
        lines[0],
        following_text=same_block_text or following_block_text,
        strong_layout_signal=strong_layout_signal,
    ):
        heading = lines[0]
        return heading, same_block_text
    return current_heading, normalize_block_text(" ".join(lines))


def retrieval_tags(text: str) -> list[str]:
    """Return generic semantic categories supported by the text itself."""
    return [tag for tag, pattern in _TAG_PATTERNS if pattern.search(text)]


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
                    message="Local PDF evidence was retained for this category.",
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
                    message="One or more required tags lack local PDF evidence.",
                )
            )
    return diagnostics, missing_categories


def build_full_paper_evidence(
    paper_id: str,
    pdf_path: Path,
) -> FullPaperEvidenceInventory:
    """Inventory selectable PDF text locally, retaining page and section context."""
    evidence_blocks: list[FullPaperEvidenceBlock] = []
    current_heading = "Unsectioned"
    with fitz.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            page_blocks = page.get_text("blocks", sort=True)
            page_layouts, body_style = _page_layout(page)
            for block_ordinal, block in enumerate(
                page_blocks, start=1
            ):
                raw_text = block[4]
                block_number = int(block[5])
                following_block_text = (
                    page_blocks[block_ordinal][4]
                    if block_ordinal < len(page_blocks)
                    else ""
                )
                previous_layout = (
                    page_layouts.get(int(page_blocks[block_ordinal - 2][5]))
                    if block_ordinal > 1
                    else None
                )
                following_layout = (
                    page_layouts.get(int(page_blocks[block_ordinal][5]))
                    if block_ordinal < len(page_blocks)
                    else None
                )
                heading, text = _split_heading(
                    raw_text,
                    current_heading,
                    following_block_text,
                    strong_layout_signal=_strong_heading_layout_signal(
                        page_layouts.get(block_number),
                        previous_layout,
                        following_layout,
                        body_style,
                    ),
                )
                current_heading = heading
                if not text:
                    continue
                evidence_blocks.append(
                    FullPaperEvidenceBlock(
                        evidence_id=_evidence_id(
                            paper_id, page_number, block_ordinal, heading, text
                        ),
                        page_number=page_number,
                        heading=heading,
                        text=text,
                        retrieval_tags=retrieval_tags(text),
                    )
                )
    diagnostics, missing_categories = _coverage_diagnostics(evidence_blocks)
    return FullPaperEvidenceInventory(
        paper_id=paper_id,
        source_pdf=pdf_path.name,
        evidence_blocks=evidence_blocks,
        coverage_diagnostics=diagnostics,
        missing_categories=missing_categories,
    )
