"""Build a local, generic evidence inventory from selectable PDF text."""

from __future__ import annotations

import hashlib
import re
import unicodedata
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
_NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S")
_FIGURE_OR_TABLE_LABEL = re.compile(
    r"^(?:fig(?:ure)?|table)\s+\S", re.IGNORECASE
)
_TITLE_CONNECTORS = frozenset(
    {"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to", "via", "with"}
)

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


def _is_heading(text: str) -> bool:
    if any(pattern.fullmatch(text) for pattern in _HEADING_PATTERNS):
        return True
    if (
        not text
        or _FIGURE_OR_TABLE_LABEL.match(text)
        or text.endswith((".", "?", "!"))
    ):
        return False
    if _NUMBERED_HEADING.match(text):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    return bool(words) and len(words) <= 12 and all(
        word.casefold() in _TITLE_CONNECTORS or word[0].isupper()
        for word in words
    )


def _split_heading(block_text: str, current_heading: str) -> tuple[str, str]:
    """Use a standalone or leading conventional section heading as context."""
    lines = [normalize_block_text(line) for line in block_text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return current_heading, ""
    if _is_heading(lines[0]):
        heading = lines[0]
        return heading, normalize_block_text(" ".join(lines[1:]))
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
            for block_ordinal, block in enumerate(
                page.get_text("blocks", sort=True), start=1
            ):
                raw_text = block[4]
                heading, text = _split_heading(raw_text, current_heading)
                if _is_heading(normalize_block_text(raw_text)):
                    current_heading = heading
                    continue
                if not text:
                    continue
                current_heading = heading
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
