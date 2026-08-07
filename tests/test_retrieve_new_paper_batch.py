from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from src.screening.retrieve_new_paper_batch import retrieve_oa_queue
from src.screening.retrieve_gold_oa_packages import OA_API


def oa_package() -> bytes:
    article = b"""<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><title-group><article-title>New paper</article-title></title-group></article-meta></front><body><sec><title>Results</title><p id="r1">LNP treatment increased hepatocyte expression.</p></sec></body><supplementary-material xlink:href="supplement.pdf">Supplementary information</supplementary-material></article>"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in (("article.nxml", article), ("supplement.pdf", b"fixture")):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def test_oa_api_uses_the_working_ncbi_pmc_path() -> None:
    assert OA_API == "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"


def test_oa_queue_retrieval_ingests_article_and_declared_supplement(
    tmp_path: Path,
) -> None:
    queue = [{
        "candidate_id": "candidate_00001",
        "pmcid": "PMC123",
        "title": "New paper",
        "matched_cell_types": ["hepatocyte"],
    }]

    report = retrieve_oa_queue(
        queue,
        tmp_path,
        package_lookup=lambda _pmcid: "https://example.test/package.tgz",
        download=lambda _url: oa_package(),
    )

    paper = report["papers"][0]
    assert paper["status"] == "source_ingested"
    assert paper["declared_assets"] == ["supplement.pdf"]
    assert paper["supplement_files"] == ["supplement.pdf"]
    assert paper["article_blocks"] >= 2
    assert (tmp_path / "corpus/candidate_00001.blocks.jsonl").is_file()


def test_full_text_xml_fallback_is_used_when_no_oa_archive(
    tmp_path: Path,
) -> None:
    article = b"""<pmc-articleset><article><front><article-meta><title-group><article-title>Fallback paper</article-title></title-group></article-meta></front><body><sec><title>Results</title><p>mRNA LNP expression in hepatocytes.</p></sec></body></article></pmc-articleset>"""

    report = retrieve_oa_queue(
        [{"candidate_id": "candidate_00002", "pmcid": "PMC999"}],
        tmp_path,
        package_lookup=lambda _pmcid: (_ for _ in ()).throw(
            RuntimeError("not Open Access")
        ),
        download=lambda _url: b"",
        full_text_retriever=lambda _pmcid, _timeout: (
            article,
            "https://example.test/fullTextXML",
            "https://example.test/fullTextXML",
            200,
            "ncbi_pmc_efetch",
            [],
        ),
    )

    paper = report["papers"][0]
    assert paper["status"] == "source_ingested"
    assert paper["retrieval_method"] == "ncbi_pmc_efetch"
    assert paper["oa_package_error"] == "RuntimeError: not Open Access"


def test_xml_fallback_clears_an_archive_path_when_download_failed(
    tmp_path: Path,
) -> None:
    article = b"""<article><front><article-meta><title-group><article-title>Fallback</article-title></title-group></article-meta></front><body><p>Result.</p></body></article>"""

    report = retrieve_oa_queue(
        [{"candidate_id": "candidate_00003", "pmcid": "PMC998"}],
        tmp_path,
        package_lookup=lambda _pmcid: "https://example.test/missing.tgz",
        download=lambda _url: (_ for _ in ()).throw(FileNotFoundError("archive")),
        full_text_retriever=lambda _pmcid, _timeout: (
            article, "requested", "final", 200, "ncbi_pmc_efetch", []
        ),
    )

    paper = report["papers"][0]
    assert paper["status"] == "source_ingested"
    assert paper["archive_path"] is None
    assert paper["archive_sha256"] is None


def test_declared_supplement_is_downloaded_from_europe_pmc_archive(
    tmp_path: Path,
) -> None:
    article = b"""<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><title-group><article-title>Fallback</article-title></title-group></article-meta></front><body><p>Result.</p></body><supplementary-material xlink:href="mmc1.csv">Supplementary data</supplementary-material></article>"""
    supplement_archive = io.BytesIO()
    with zipfile.ZipFile(supplement_archive, "w") as archive:
        archive.writestr("mmc1.csv", "lipid,ratio\nION,50\n")

    report = retrieve_oa_queue(
        [{"candidate_id": "candidate_00004", "pmcid": "PMC997"}],
        tmp_path,
        package_lookup=lambda _pmcid: (_ for _ in ()).throw(
            RuntimeError("not Open Access")
        ),
        download=lambda _url: b"",
        full_text_retriever=lambda _pmcid, _timeout: (
            article, "requested", "final", 200, "ncbi_pmc_efetch", []
        ),
        supplement_downloader=lambda _url: supplement_archive.getvalue(),
    )

    paper = report["papers"][0]
    assert paper["supplement_files"] == ["mmc1.csv"]
    assert paper["supplement_blocks"] == 1
    assert paper["supplement_archive_sha256"]
