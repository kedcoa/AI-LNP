"""Retrieve and locally ingest PMC OA packages for a new-paper queue."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable
import zipfile

from src.rag.current_corpus_assets import (
    AssetResolution,
    discover_declared_assets,
    ingest_current_corpus_assets,
)
from src.rag.ingestion import xml_blocks
from src.screening.retrieve_gold_oa_packages import (
    EUROPE_PMC_SUPPLEMENTS,
    flatten_single_directory,
    package_url,
    request_bytes,
    safe_extract,
    safe_extract_zip,
)
from src.screening.retrieve_gold_fulltext import retrieve_full_text_xml


PackageLookup = Callable[[str], str]
Downloader = Callable[[str], bytes]
FullTextRetriever = Callable[[str, float], tuple[bytes, str, str, int, str, list[str]]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _article_xml(package_dir: Path) -> Path:
    candidates = sorted(
        (*package_dir.rglob("*.nxml"), *package_dir.rglob("*.xml")),
        key=lambda path: (-path.stat().st_size, str(path)),
    )
    if not candidates:
        raise FileNotFoundError("OA package has no article XML")
    return candidates[0]


def retrieve_oa_queue(
    queue: Iterable[dict[str, object]],
    output_root: Path,
    *,
    package_lookup: PackageLookup = package_url,
    download: Downloader = request_bytes,
    full_text_retriever: FullTextRetriever = retrieve_full_text_xml,
    supplement_downloader: Downloader = request_bytes,
) -> dict[str, object]:
    """Retrieve complete OA packages and turn their sources into local blocks."""

    output_root = Path(output_root)
    archive_root = output_root / "archives"
    package_root = output_root / "packages"
    corpus_root = output_root / "corpus"
    archive_root.mkdir(parents=True, exist_ok=True)
    package_root.mkdir(parents=True, exist_ok=True)
    corpus_root.mkdir(parents=True, exist_ok=True)
    papers: list[dict[str, object]] = []
    for candidate in queue:
        candidate_id = str(candidate["candidate_id"])
        pmcid = str(candidate["pmcid"])
        result: dict[str, object] = {
            "candidate_id": candidate_id,
            "pmcid": pmcid,
            "title": candidate.get("title"),
            "matched_cell_types": candidate.get("matched_cell_types", []),
            "status": "failed",
        }
        try:
            destination = package_root / candidate_id
            oa_package_error = None
            archive_path: Path | None = None
            retrieval_failures: list[str] = []
            try:
                url = package_lookup(pmcid)
                archive_path = archive_root / f"{pmcid}.tar.gz"
                if not archive_path.exists():
                    archive_path.write_bytes(download(url))
                if not destination.exists():
                    safe_extract(archive_path, destination)
                    flatten_single_directory(destination)
                article_path = _article_xml(destination)
                retrieval_method = "ncbi_oa_tgz"
            except Exception as error:
                oa_package_error = f"{type(error).__name__}: {error}"
                archive_path = None
                (
                    content,
                    requested_url,
                    final_url,
                    _http_status,
                    retrieval_method,
                    retrieval_failures,
                ) = full_text_retriever(pmcid, 60.0)
                destination.mkdir(parents=True, exist_ok=True)
                article_path = destination / f"{pmcid}.nxml"
                article_path.write_bytes(content)
                url = final_url or requested_url
            assets = discover_declared_assets((article_path,))
            supplement_paths = list(
                Path(asset.local_path)
                for asset in assets
                if asset.kind == "supplement" and asset.local_path
            )
            supplement_archive_sha256 = None
            supplement_download_error = None
            missing_supplements = [
                asset
                for asset in assets
                if asset.kind == "supplement" and not asset.local_path
            ]
            if missing_supplements:
                supplement_archive = destination / f"{pmcid}_supplementary.zip"
                try:
                    if not supplement_archive.exists():
                        supplement_archive.write_bytes(
                            supplement_downloader(
                                EUROPE_PMC_SUPPLEMENTS.format(pmcid=pmcid)
                            )
                        )
                    if not zipfile.is_zipfile(supplement_archive):
                        raise ValueError("supplement response is not a ZIP archive")
                    safe_extract_zip(supplement_archive, destination)
                    supplement_archive_sha256 = _sha256(supplement_archive)
                    for asset in missing_supplements:
                        matches = sorted(destination.rglob(asset.filename))
                        if matches:
                            supplement_paths.append(matches[0])
                except Exception as error:
                    supplement_download_error = (
                        f"{type(error).__name__}: {error}"
                    )
            supplement_paths = list(dict.fromkeys(supplement_paths))
            blocks = xml_blocks(candidate_id, article_path)
            supplement_blocks = []
            supplement_errors: list[str] = []
            for supplement_path in supplement_paths:
                try:
                    supplement_blocks.extend(
                        ingest_current_corpus_assets(
                            {"paper_id": candidate_id},
                            AssetResolution(local_files=(supplement_path,)),
                        )
                    )
                except Exception as error:
                    supplement_errors.append(
                        f"{supplement_path.name}: {type(error).__name__}"
                    )
            all_blocks = [*blocks, *supplement_blocks]
            block_path = corpus_root / f"{candidate_id}.blocks.jsonl"
            block_path.write_text(
                "".join(block.model_dump_json() + "\n" for block in all_blocks),
                encoding="utf-8",
            )
            result.update(
                {
                    "status": "source_ingested",
                    "retrieval_method": retrieval_method,
                    "package_url": url,
                    "archive_path": (
                        str(archive_path.resolve()) if archive_path else None
                    ),
                    "archive_sha256": (
                        _sha256(archive_path) if archive_path else None
                    ),
                    "oa_package_error": oa_package_error,
                    "retrieval_failures": retrieval_failures,
                    "article_path": str(article_path.resolve()),
                    "article_sha256": _sha256(article_path),
                    "declared_assets": [asset.filename for asset in assets],
                    "supplement_files": [path.name for path in supplement_paths],
                    "supplement_archive_sha256": supplement_archive_sha256,
                    "supplement_download_error": supplement_download_error,
                    "supplement_ingestion_errors": supplement_errors,
                    "article_blocks": len(blocks),
                    "supplement_blocks": len(supplement_blocks),
                    "block_path": str(block_path.resolve()),
                    "block_sha256": _sha256(block_path),
                }
            )
        except Exception as error:
            result["error"] = f"{type(error).__name__}: {error}"
        papers.append(result)
    report = {
        "schema_version": "new-paper-source-retrieval/v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "papers": papers,
        "queued": len(papers),
        "source_accessible_papers": sum(
            paper["status"] == "source_ingested" for paper in papers
        ),
        "declared_supplement_count": sum(
            len(paper.get("declared_assets", [])) for paper in papers
        ),
        "local_supplement_count": sum(
            len(paper.get("supplement_files", [])) for paper in papers
        ),
        "article_blocks": sum(int(paper.get("article_blocks", 0)) for paper in papers),
        "supplement_blocks": sum(
            int(paper.get("supplement_blocks", 0)) for paper in papers
        ),
        "extraction_stage": "source_blocks_ready",
        "provider_calls": 0,
    }
    (output_root / "retrieval_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _read_queue(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            retrieve_oa_queue(_read_queue(args.queue), args.output_root),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()


__all__ = ["retrieve_oa_queue"]
