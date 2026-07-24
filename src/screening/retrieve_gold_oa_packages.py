"""Retrieve complete lawful PMC Open Access packages for the gold set."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import ssl
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import certifi

from src.rag.ingestion import GOLD_PAPERS, OA_ROOT, ROOT


OA_API = "https://pmc.ncbi.nlm.nih.gov/utils/oa/oa.fcgi?id={pmcid}"
USER_AGENT = "AI-LNP evidence project (lawful PMC OA package retrieval)"
PMC_BIN = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/bin/{name}"
EUROPE_PMC_PDF = "https://europepmc.org/articles/{pmcid}?pdf=render"
EUROPE_PMC_SUPPLEMENTS = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/"
    "{pmcid}/supplementaryFiles"
)
XML_ROOT = ROOT / "data/raw/fulltext/gold_v1/xml"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request_bytes(url: str, timeout: float = 120.0, attempts: int = 4) -> bytes:
    context = ssl.create_default_context(cafile=certifi.where())
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return response.read()
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def package_url(pmcid: str) -> str:
    root = ET.fromstring(request_bytes(OA_API.format(pmcid=pmcid)))
    link = next(
        (node for node in root.iter("link") if node.attrib.get("format") == "tgz"),
        None,
    )
    if link is None or not link.attrib.get("href"):
        error = next((node.text for node in root.iter("error")), "no tgz OA link")
        raise RuntimeError(f"{pmcid}: {error}")
    return link.attrib["href"].replace("ftp://", "https://")


def local_xml(candidate_id: str, pmcid: str) -> Path:
    matches = sorted(XML_ROOT.glob(f"{candidate_id}_{pmcid}.xml"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one XML for {candidate_id} {pmcid}")
    return matches[0]


def linked_assets(xml_path: Path) -> list[str]:
    root = ET.parse(xml_path).getroot()
    names: set[str] = set()
    for node in root.iter():
        href = next(
            (value for key, value in node.attrib.items() if key.endswith("}href") or key == "href"),
            None,
        )
        if not href:
            continue
        href = href.removeprefix("file:")
        if href.lower().endswith((".pdf", ".xlsx", ".xls", ".csv", ".zip")):
            names.add(Path(href).name)
    return sorted(names)


def retrieve_linked_package(
    paper: dict[str, str], destination: Path
) -> tuple[str, list[Path]]:
    pmcid, candidate_id = paper["pmcid"], paper["candidate_id"]
    xml_path = local_xml(candidate_id, pmcid)
    destination.mkdir(parents=True, exist_ok=True)
    copied_xml = destination / f"{pmcid}.nxml"
    if not copied_xml.exists():
        shutil.copy2(xml_path, copied_xml)
    files = [copied_xml]
    for name in linked_assets(xml_path):
        path = destination / name
        if not path.exists():
            path.write_bytes(request_bytes(PMC_BIN.format(pmcid=pmcid, name=name)))
        files.append(path)
    return "europe_pmc_linked_assets", files


def safe_extract_zip(archive: Path, destination: Path) -> None:
    resolved = destination.resolve()
    with zipfile.ZipFile(archive) as handle:
        for name in handle.namelist():
            target = (destination / name).resolve()
            if target != resolved and resolved not in target.parents:
                raise ValueError(f"Unsafe ZIP member: {name}")
        handle.extractall(destination)


def retrieve_europe_pmc_package(
    paper: dict[str, str], destination: Path
) -> tuple[str, list[Path]]:
    pmcid, candidate_id = paper["pmcid"], paper["candidate_id"]
    xml_path = local_xml(candidate_id, pmcid)
    destination.mkdir(parents=True, exist_ok=True)
    copied_xml = destination / f"{pmcid}.nxml"
    if not copied_xml.exists():
        shutil.copy2(xml_path, copied_xml)
    pdf_names = [name for name in linked_assets(xml_path) if name.lower().endswith(".pdf")]
    main_name = pdf_names[0] if pdf_names else f"{pmcid}.pdf"
    main_pdf = destination / main_name
    if not main_pdf.exists():
        main_pdf.write_bytes(request_bytes(EUROPE_PMC_PDF.format(pmcid=pmcid)))
    supplement_zip = destination / f"{pmcid}_supplementary.zip"
    try:
        if not supplement_zip.exists():
            supplement_zip.write_bytes(request_bytes(
                EUROPE_PMC_SUPPLEMENTS.format(pmcid=pmcid)
            ))
        if supplement_zip.stat().st_size and zipfile.is_zipfile(supplement_zip):
            safe_extract_zip(supplement_zip, destination)
    except Exception:
        # The main article remains usable when no separate supplement archive exists.
        pass
    return "europe_pmc_pdf_and_supplements", [
        path for path in destination.rglob("*") if path.is_file()
    ]


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved = destination.resolve()
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if target != resolved and resolved not in target.parents:
                raise ValueError(f"Unsafe archive member: {member.name}")
        handle.extractall(destination, filter="data")


def flatten_single_directory(destination: Path) -> None:
    children = [path for path in destination.iterdir() if path.name != ".package.json"]
    if len(children) != 1 or not children[0].is_dir():
        return
    nested = children[0]
    for path in list(nested.iterdir()):
        path.rename(destination / path.name)
    nested.rmdir()


def run() -> dict:
    with GOLD_PAPERS.open(newline="", encoding="utf-8") as handle:
        papers = list(csv.DictReader(handle))
    archive_root = ROOT / "data/raw/fulltext/oa_archives"
    archive_root.mkdir(parents=True, exist_ok=True)
    results = []
    for paper in papers:
        paper_id, pmcid = paper["gold_paper_id"], paper["pmcid"]
        destination = OA_ROOT / pmcid
        manifest_path = destination / ".package.json"
        if manifest_path.exists():
            results.append(json.loads(manifest_path.read_text()))
            continue
        result = {
            "paper_id": paper_id,
            "pmcid": pmcid,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
        }
        try:
            try:
                url = package_url(pmcid)
                archive = archive_root / f"{pmcid}.tar.gz"
                if not archive.exists():
                    archive.write_bytes(request_bytes(url))
                safe_extract(archive, destination)
                flatten_single_directory(destination)
                retrieval_method = "ncbi_oa_tgz"
                archive_path = str(archive.relative_to(ROOT))
                archive_digest = sha256(archive)
            except Exception:
                try:
                    retrieval_method, _ = retrieve_linked_package(paper, destination)
                    url = PMC_BIN.format(pmcid=pmcid, name="{linked_asset}")
                except Exception:
                    retrieval_method, _ = retrieve_europe_pmc_package(paper, destination)
                    url = EUROPE_PMC_PDF.format(pmcid=pmcid)
                archive_path = None
                archive_digest = None
            files = sorted(
                path for path in destination.rglob("*")
                if path.is_file() and path.name != ".package.json"
            )
            result.update({
                "status": "retrieved",
                "retrieval_method": retrieval_method,
                "package_url": url,
                "archive_path": archive_path,
                "archive_sha256": archive_digest,
                "files": [{
                    "path": str(path.relative_to(ROOT)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                } for path in files],
                "pdf_count": sum(path.suffix.lower() == ".pdf" for path in files),
            })
            destination.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n"
            )
        except Exception as error:
            result["error"] = f"{type(error).__name__}: {error}"
        results.append(result)
    output = ROOT / "data/staging/extraction/day8_final_gate/retrieval_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    return {
        "papers": len(results),
        "retrieved": sum(row["status"] == "retrieved" for row in results),
        "failed": sum(row["status"] == "failed" for row in results),
        "pdfs": sum(row.get("pdf_count", 0) for row in results),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
