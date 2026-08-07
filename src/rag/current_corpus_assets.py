"""Local-first discovery and ingestion of declared current-corpus assets."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from .ingestion import compact, stable_id
from .models import DocumentBlock


SCIENTIFIC_SUFFIXES = {
    ".pdf", ".xml", ".nxml", ".html", ".htm", ".csv", ".tsv",
    ".xlsx", ".xls", ".zip",
}
SUPPLEMENT_WORDS = re.compile(
    r"\b(supplement(?:ary)?|supporting information|additional file|appendix)\b",
    re.IGNORECASE,
)
SUPPLEMENT_FILENAMES = re.compile(
    r"(?:^|[._-])(supp|sapp|mmc\d*|esm|moesm\d*|suppl)(?:[._-]|$)",
    re.IGNORECASE,
)
PATENT_WORDS = re.compile(r"\bpatent\b|\bUS\s*\d[\d,]{5,}", re.IGNORECASE)
PROTOCOL_WORDS = re.compile(r"\b(protocol|method(?:s)? appendix)\b", re.IGNORECASE)
DATASET_WORDS = re.compile(r"\b(source data|dataset|data set|raw data)\b", re.IGNORECASE)
PATENT_NUMBER = re.compile(r"\bUS\s*([\d,]{6,})", re.IGNORECASE)


@dataclass(frozen=True)
class AssetInventory:
    local_files: tuple[Path, ...]
    declared_supplements: tuple[dict[str, Any], ...]
    missing_paths: tuple[str, ...]
    hash_mismatches: tuple[str, ...]


@dataclass(frozen=True)
class AssetResolution:
    local_files: tuple[Path, ...]
    downloaded_files: tuple[Path, ...] = ()
    access_blockers: tuple[str, ...] = ()
    hash_mismatches: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeclaredAsset:
    url: str
    label: str
    kind: str
    filename: str
    declared_by: str
    local_path: str | None
    sha256: str | None
    access_status: str
    provenance_scope: str


def classify_link(
    label: str | None,
    href: str | None,
    *,
    element_name: str | None = None,
    citation_context: str | None = None,
) -> str | None:
    """Classify only links explicitly recognizable as scientific supplements."""

    label_text = compact(label or "")
    href_text = (href or "").strip()
    if not href_text:
        return None
    context = compact(" ".join(
        value for value in (label_text, element_name or "", citation_context or "")
        if value
    ))
    parsed = urllib.parse.urlparse(href_text)
    filename = Path(parsed.path).name
    suffix = Path(filename).suffix.casefold()
    if PATENT_WORDS.search(context) or "patents.google." in parsed.netloc:
        return "patent"
    if PROTOCOL_WORDS.search(context) and (
        not suffix or suffix in SCIENTIFIC_SUFFIXES
    ):
        return "protocol"
    if DATASET_WORDS.search(context) and (
        not suffix or suffix in SCIENTIFIC_SUFFIXES
    ):
        return "dataset"
    declared = bool(SUPPLEMENT_WORDS.search(label_text))
    filename_signal = bool(SUPPLEMENT_FILENAMES.search(filename))
    if declared:
        if parsed.fragment and "/lookup/doi/" in parsed.path:
            return None
        return "supplement"
    if filename_signal and suffix in SCIENTIFIC_SUFFIXES:
        return "supplement"
    return None


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._href: str | None = None
        self._text: list[str] = []
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            self.links.append((compact(" ".join(self._text)), self._href, "a"))
            self._href = None
            self._text = []


def _declared_link_rows(path: Path) -> list[tuple[str, str, str]]:
    if path.suffix.casefold() in {".xml", ".nxml"}:
        try:
            root = ET.fromstring(path.read_bytes())
        except ET.ParseError:
            return []
        rows: list[tuple[str, str, str]] = []
        for element in root.iter():
            href = next(
                (
                    value for key, value in element.attrib.items()
                    if key.rsplit("}", 1)[-1] in {"href", "locator"}
                ),
                None,
            )
            if href:
                rows.append((
                    compact("".join(element.itertext())),
                    href,
                    element.tag.rsplit("}", 1)[-1],
                ))
        return rows
    if path.suffix.casefold() in {".html", ".htm"}:
        parser = _AnchorParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        return parser.links
    return []


def _asset_filename(kind: str, label: str, href: str) -> str:
    if kind == "patent":
        match = PATENT_NUMBER.search(f"{label} {href}")
        if match:
            return f"US{match.group(1).replace(',', '')}"
        path_match = re.search(r"/patent/(US\d+)", href, re.IGNORECASE)
        if path_match:
            return path_match.group(1).upper()
    return Path(urllib.parse.urlparse(href).path).name or href


def discover_declared_assets(
    source_paths: Iterable[Path],
) -> tuple[DeclaredAsset, ...]:
    """Discover only explicitly declared scientific assets in local sources."""

    discovered: dict[tuple[str, str], DeclaredAsset] = {}
    for source_path in (Path(path).resolve() for path in source_paths):
        for label, href, element_name in _declared_link_rows(source_path):
            kind = classify_link(
                label, href, element_name=element_name, citation_context=label
            )
            if kind is None:
                continue
            parsed = urllib.parse.urlparse(href)
            basename = Path(parsed.path).name
            adjacent = source_path.parent / basename if basename else None
            local = adjacent if adjacent is not None and adjacent.is_file() else None
            digest = (
                hashlib.sha256(local.read_bytes()).hexdigest() if local else None
            )
            asset = DeclaredAsset(
                url=href,
                label=label,
                kind=kind,
                filename=_asset_filename(kind, label, href),
                declared_by=str(source_path),
                local_path=str(local) if local else None,
                sha256=digest,
                access_status="available" if local else "declared",
                provenance_scope=(
                    "indirect_reference" if kind == "patent"
                    else "direct_source_asset"
                ),
            )
            discovered[(kind, href)] = asset
    return tuple(discovered[key] for key in sorted(discovered))


def _checkout_roots(root: Path) -> tuple[Path, ...]:
    roots = [root.resolve()]
    dot_git = root / ".git"
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            gitdir = Path(text.split(":", 1)[1].strip()).resolve()
            if len(gitdir.parents) >= 3 and gitdir.parents[1].name == ".git":
                main = gitdir.parents[1].parent
                if main not in roots:
                    roots.append(main)
    return tuple(roots)


def _resolve_local(logical_path: str, roots: Iterable[Path]) -> Path | None:
    for root in roots:
        candidate = root / logical_path
        if candidate.is_file():
            return candidate.resolve()
    return None


def _declared_links_from_xml(path: Path) -> list[tuple[str, str]]:
    try:
        root = ET.fromstring(path.read_bytes())
    except ET.ParseError:
        return []
    links: list[tuple[str, str]] = []
    for element in root.iter():
        href = next(
            (
                value for key, value in element.attrib.items()
                if key.rsplit("}", 1)[-1] in {"href", "locator"}
            ),
            None,
        )
        if href:
            label = compact("".join(element.itertext()))
            if classify_link(label, href) == "supplement":
                links.append((label, href))
    return links


def _resolve_declared_local_link(
    source_path: Path, href: str, roots: Iterable[Path]
) -> Path | None:
    parsed = urllib.parse.urlparse(href)
    if parsed.scheme or parsed.netloc:
        return None
    basename = Path(parsed.path).name
    if not basename:
        return None
    adjacent = source_path.parent / basename
    if adjacent.is_file():
        return adjacent.resolve()
    for root in roots:
        matches = list(root.glob(f"data/**/{basename}"))
        if len(matches) == 1 and matches[0].is_file():
            return matches[0].resolve()
    return None


def inventory_local_assets(entry: dict[str, Any], root: Path) -> AssetInventory:
    roots = _checkout_roots(Path(root))
    local: list[Path] = []
    declared: list[dict[str, Any]] = []
    missing: list[str] = []
    mismatches: list[str] = []
    for artifact in entry.get("contributing_artifacts", []):
        if artifact.get("role") != "supplement":
            continue
        declared.append(artifact)
        logical_path = str(artifact["path"])
        path = _resolve_local(logical_path, roots)
        if path is None:
            missing.append(logical_path)
            continue
        expected = artifact.get("sha256")
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected and observed != expected:
            mismatches.append(logical_path)
            continue
        local.append(path)
    for artifact in entry.get("contributing_artifacts", []):
        if artifact.get("role") != "source_document":
            continue
        logical_path = str(artifact.get("path") or "")
        if Path(logical_path).suffix.casefold() not in {".xml", ".nxml"}:
            continue
        source_path = _resolve_local(logical_path, roots)
        if source_path is None:
            continue
        for label, href in _declared_links_from_xml(source_path):
            declared_item = {"label": label, "href": href, "declared_by": logical_path}
            declared.append(declared_item)
            resolved = _resolve_declared_local_link(source_path, href, roots)
            if resolved is not None:
                local.append(resolved)
            else:
                missing.append(href)
    return AssetInventory(
        tuple(dict.fromkeys(local)), tuple(declared), tuple(dict.fromkeys(missing)),
        tuple(dict.fromkeys(mismatches))
    )


def resolve_declared_supplements(
    entry: dict[str, Any],
    *,
    root: Path,
    allow_network: bool,
) -> AssetResolution:
    """Resolve registered local assets first; never crawl or fetch arbitrary links."""

    inventory = inventory_local_assets(entry, root)
    blockers = list(inventory.missing_paths)
    downloaded: list[Path] = []
    if allow_network:
        declared_links = [
            item for item in entry.get("declared_links", [])
            if classify_link(item.get("label"), item.get("href")) == "supplement"
        ]
        for item in declared_links:
            href = str(item["href"])
            target_name = Path(urllib.parse.urlparse(href).path).name
            if not target_name or Path(target_name).suffix.casefold() not in SCIENTIFIC_SUFFIXES:
                blockers.append(f"declared supplement has no safe filename: {href}")
                continue
            target = (
                Path(root) / "data/raw/fulltext/declared_supplements"
                / str(entry["paper_id"]) / target_name
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with urllib.request.urlopen(href, timeout=30) as response:
                    content = response.read()
                target.write_bytes(content)
                downloaded.append(target.resolve())
            except Exception as error:
                blockers.append(f"access blocked for {href}: {type(error).__name__}")
        if downloaded:
            blockers = [
                item for item in blockers
                if not any(path.name in item for path in downloaded)
            ]
    elif blockers:
        blockers = [f"local supplement unavailable: {item}" for item in blockers]
    return AssetResolution(
        local_files=inventory.local_files,
        downloaded_files=tuple(downloaded),
        access_blockers=tuple(blockers),
        hash_mismatches=inventory.hash_mismatches,
    )


def _block(
    paper_id: str,
    path: Path,
    source_kind: str,
    block_type: str,
    text: str,
    *,
    page_number: int | None = None,
    section: str,
    parser: str,
    confidence: float,
) -> DocumentBlock:
    return DocumentBlock(
        block_id=f"{paper_id}-B-{stable_id(str(path), str(page_number), text)}",
        paper_id=paper_id,
        source_path=str(path),
        source_kind=source_kind,
        section_path=section,
        block_type=block_type,
        text=text,
        page_number=page_number,
        char_start=0,
        char_end=len(text),
        parser=parser,
        parser_confidence=confidence,
    )


def _pdf_blocks(paper_id: str, path: Path) -> list[DocumentBlock]:
    import pymupdf

    rows: list[DocumentBlock] = []
    with pymupdf.open(path) as document:
        for index, page in enumerate(document, start=1):
            text = compact(page.get_text("text", sort=True))
            if text:
                rows.append(_block(
                    paper_id, path, "pdf", "pdf_page", text,
                    page_number=index, section=f"Supplement page {index}",
                    parser="pymupdf", confidence=0.75,
                ))
    return rows


def _delimited_blocks(paper_id: str, path: Path, delimiter: str) -> list[DocumentBlock]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=delimiter))
    text = "\n".join("\t".join(row) for row in rows).strip()
    return [] if not text else [_block(
        paper_id, path, "spreadsheet", "table", text,
        section="Supplement table", parser="csv", confidence=1.0,
    )]


def _xlsx_blocks(paper_id: str, path: Path) -> list[DocumentBlock]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    blocks: list[DocumentBlock] = []
    for sheet in workbook.worksheets:
        text = "\n".join(
            "\t".join("" if value is None else str(value) for value in row)
            for row in sheet.iter_rows(values_only=True)
        ).strip()
        if text:
            blocks.append(_block(
                paper_id, path, "spreadsheet", "table", text,
                section=f"Supplement sheet: {sheet.title}",
                parser="openpyxl", confidence=1.0,
            ))
    workbook.close()
    return blocks


def _zip_blocks(paper_id: str, path: Path) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            member_path = Path(member.filename)
            if member.is_dir() or member_path.is_absolute() or ".." in member_path.parts:
                continue
            suffix = member_path.suffix.casefold()
            if suffix not in {".txt", ".csv", ".tsv"}:
                continue
            data = archive.read(member)
            text = data.decode("utf-8-sig", errors="replace").strip()
            if text:
                blocks.append(_block(
                    paper_id, path, "archive_member",
                    "table" if suffix in {".csv", ".tsv"} else "paragraph",
                    text, section=f"Supplement archive: {member.filename}",
                    parser="zipfile", confidence=0.9,
                ))
    return blocks


def ingest_current_corpus_assets(
    entry: dict[str, Any], assets: AssetResolution
) -> list[DocumentBlock]:
    """Route each resolved supplement through a deterministic local parser."""

    paper_id = str(entry["paper_id"])
    blocks: list[DocumentBlock] = []
    for path in (*assets.local_files, *assets.downloaded_files):
        suffix = path.suffix.casefold()
        if suffix == ".pdf":
            blocks.extend(_pdf_blocks(paper_id, path))
        elif suffix == ".csv":
            blocks.extend(_delimited_blocks(paper_id, path, ","))
        elif suffix == ".tsv":
            blocks.extend(_delimited_blocks(paper_id, path, "\t"))
        elif suffix == ".xlsx":
            blocks.extend(_xlsx_blocks(paper_id, path))
        elif suffix == ".zip":
            blocks.extend(_zip_blocks(paper_id, path))
    return blocks


__all__ = [
    "AssetInventory", "AssetResolution", "DeclaredAsset", "classify_link",
    "discover_declared_assets",
    "inventory_local_assets", "resolve_declared_supplements",
    "ingest_current_corpus_assets",
]
