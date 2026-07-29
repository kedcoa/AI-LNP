"""Download the frozen gold papers from the official PMC OA service.

No API key or LLM call is used. Each open-access package includes the article
XML and any files (PDFs, figures, tables, or supplements) deposited in PMC.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data/manifests/gold_source_manifest_v1.json"
DEFAULT_OUTPUT = ROOT / "data/raw/fulltext"
OA_API = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"
USER_AGENT = "AI-LNP gold-source downloader/1.0"


def request_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def oa_package_url(pmcid: str) -> str:
    root = ET.fromstring(request_bytes(OA_API.format(pmcid=pmcid)))
    error = root.find(".//error")
    if error is not None:
        raise RuntimeError(f"{pmcid}: PMC OA error: {error.text}")
    for link in root.findall(".//link"):
        if link.attrib.get("format") == "tgz" and link.attrib.get("href"):
            return link.attrib["href"]
    raise RuntimeError(f"{pmcid}: PMC returned no OA tar package")


def safe_extract(archive: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            member_path = (destination / member.name).resolve()
            if destination_root not in member_path.parents and member_path != destination_root:
                raise RuntimeError(f"Unsafe archive member: {member.name}")
            if member.issym() or member.islnk():
                raise RuntimeError(f"Archive links are not accepted: {member.name}")
        bundle.extractall(destination, filter="data")


def find_article_xml(package_dir: Path, pmcid: str) -> Path:
    candidates = sorted(package_dir.rglob("*.nxml"))
    if not candidates:
        raise RuntimeError(f"{pmcid}: package contains no NXML article")
    exact = [path for path in candidates if path.name == f"{pmcid}.nxml"]
    return exact[0] if exact else candidates[0]


def download_paper(
    paper: dict[str, str],
    output_root: Path,
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, str]:
    pmcid = paper["pmcid"]
    package_dir = output_root / "oa_packages" / pmcid
    xml_target = output_root / "gold_v1" / "xml" / paper["expected_xml_name"]

    if package_dir.exists() and xml_target.exists() and not force:
        return {"paper_id": paper["paper_id"], "pmcid": pmcid, "status": "already_present"}
    if dry_run:
        return {
            "paper_id": paper["paper_id"],
            "pmcid": pmcid,
            "status": "would_download",
            "oa_api": OA_API.format(pmcid=pmcid),
        }

    package_url = oa_package_url(pmcid)
    xml_target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"ai-lnp-{pmcid}-") as temp_name:
        temp_dir = Path(temp_name)
        archive = temp_dir / Path(urlparse(package_url).path).name
        archive.write_bytes(request_bytes(package_url))
        archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()
        safe_extract(archive, extract_dir)
        roots = [path for path in extract_dir.iterdir() if path.is_dir()]
        content_root = roots[0] if len(roots) == 1 else extract_dir
        if package_dir.exists() and force:
            shutil.rmtree(package_dir)
        shutil.copytree(content_root, package_dir, dirs_exist_ok=True)

    article_xml = find_article_xml(package_dir, pmcid)
    shutil.copy2(article_xml, xml_target)
    metadata = {
        "paper_id": paper["paper_id"],
        "pmcid": pmcid,
        "doi": paper["doi"],
        "source": package_url,
        "archive_sha256": archive_sha256,
        "article_xml": str(article_xml.relative_to(ROOT)),
        "ingestion_xml": str(xml_target.relative_to(ROOT)),
    }
    (package_dir / ".package.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"paper_id": paper["paper_id"], "pmcid": pmcid, "status": "downloaded"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--paper-id", action="append", help="Download selected GP ID(s)")
    parser.add_argument("--force", action="store_true", help="Replace existing packages")
    parser.add_argument("--dry-run", action="store_true", help="List without downloading")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected = set(args.paper_id or [])
    known = {paper["paper_id"] for paper in manifest["papers"]}
    unknown = selected - known
    if unknown:
        parser.error(f"Unknown paper ID(s): {', '.join(sorted(unknown))}")
    papers = [
        paper
        for paper in manifest["papers"]
        if not selected or paper["paper_id"] in selected
    ]
    results = [
        download_paper(
            paper,
            args.output_root,
            force=args.force,
            dry_run=args.dry_run,
        )
        for paper in papers
    ]
    print(json.dumps({"papers": results}, indent=2))


if __name__ == "__main__":
    main()
