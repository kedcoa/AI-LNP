from __future__ import annotations

import argparse
import csv
import hashlib
import json
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import certifi


DEFAULT_MANIFEST = Path(
    "data/annotations/gold_paper_candidates.csv"
)
DEFAULT_OUTPUT_ROOT = Path(
    "data/raw/fulltext/gold_v1"
)

EUROPE_PMC_URL = (
    "https://www.ebi.ac.uk/europepmc/"
    "webservices/rest/{pmcid}/fullTextXML"
)

NCBI_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/"
    "entrez/eutils/efetch.fcgi"
    "?db=pmc&id={pmcid}"
    "&rettype=full&retmode=xml"
)

USER_AGENT = (
    "AI-LNP evidence project "
    "(research full-text retrieval)"
)


def load_selected(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    return [
        row
        for row in rows
        if row.get(
            "selected_for_gold",
            "",
        ).lower()
        == "true"
    ]


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_json(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def elements_by_local_name(
    root: ET.Element,
    name: str,
) -> list[ET.Element]:
    return [
        element
        for element in root.iter()
        if element.tag.rsplit(
            "}",
            1,
        )[-1]
        == name
    ]


def validate_full_text_xml(
    content: bytes,
) -> ET.Element:
    root = ET.fromstring(content)

    articles = elements_by_local_name(
        root,
        "article",
    )
    bodies = elements_by_local_name(
        root,
        "body",
    )

    if not articles:
        raise ValueError(
            "XML does not contain an article."
        )

    if not bodies:
        raise ValueError(
            "XML does not contain an article body."
        )

    return root


def retrieval_sources(
    pmcid: str,
) -> list[tuple[str, str]]:
    return [
        (
            "europe_pmc",
            EUROPE_PMC_URL.format(
                pmcid=pmcid
            ),
        ),
        (
            "ncbi_pmc_efetch",
            NCBI_EFETCH_URL.format(
                pmcid=pmcid
            ),
        ),
    ]


def retrieve_full_text_xml(
    pmcid: str,
    timeout: float,
) -> tuple[
    bytes,
    str,
    str,
    int,
    str,
    list[str],
]:
    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    failures: list[str] = []

    for source_name, requested_url in (
        retrieval_sources(pmcid)
    ):
        request = urllib.request.Request(
            requested_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "application/xml,text/xml"
                ),
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=ssl_context,
            ) as response:
                content = response.read()
                http_status = response.status
                final_url = response.geturl()

            validate_full_text_xml(content)

            return (
                content,
                requested_url,
                final_url,
                http_status,
                source_name,
                failures,
            )

        except urllib.error.HTTPError as error:
            failures.append(
                f"{source_name}: "
                f"HTTP {error.code}"
            )

            if error.code != 404:
                continue

        except urllib.error.URLError as error:
            failures.append(
                f"{source_name}: "
                f"URLError: {error}"
            )

        except TimeoutError as error:
            failures.append(
                f"{source_name}: "
                f"TimeoutError: {error}"
            )

        except ET.ParseError as error:
            failures.append(
                f"{source_name}: "
                f"invalid XML: {error}"
            )

        except ValueError as error:
            failures.append(
                f"{source_name}: {error}"
            )

    raise RuntimeError(
        "All structured full-text sources "
        "failed: "
        + "; ".join(failures)
    )


def existing_xml_is_valid(
    path: Path,
) -> tuple[bool, str | None]:
    try:
        content = path.read_bytes()
        validate_full_text_xml(content)
    except (
        OSError,
        ET.ParseError,
        ValueError,
    ) as error:
        return False, str(error)

    return True, None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Retrieve structured full text for "
            "selected Day 4 gold papers."
        )
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    xml_dir = args.output_root / "xml"
    metadata_dir = (
        args.output_root / "metadata"
    )

    xml_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    metadata_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    selected = load_selected(
        args.manifest
    )

    if not selected:
        raise SystemExit(
            "No selected gold papers found."
        )

    success_count = 0
    skipped_count = 0
    failure_count = 0

    for index, row in enumerate(
        selected,
        start=1,
    ):
        candidate_id = row[
            "candidate_id"
        ]
        pmcid = row.get(
            "pmcid",
            "",
        ).strip()

        print(
            f"[{index}/{len(selected)}] "
            f"{candidate_id} "
            f"{pmcid or 'NO_PMCID'}"
        )

        metadata_path = (
            metadata_dir
            / f"{candidate_id}.json"
        )

        retrieved_at = datetime.now(
            timezone.utc
        ).isoformat()

        if not pmcid:
            failure_count += 1

            write_json(
                metadata_path,
                {
                    "candidate_id": (
                        candidate_id
                    ),
                    "gold_candidate_id": (
                        row.get(
                            "gold_candidate_id"
                        )
                    ),
                    "pmcid": None,
                    "status": "failed",
                    "error_type": (
                        "missing_pmcid"
                    ),
                    "error": (
                        "Selected paper has no PMCID."
                    ),
                    "retrieved_at": (
                        retrieved_at
                    ),
                },
            )

            print("  Failed: missing PMCID.")
            continue

        xml_path = (
            xml_dir
            / f"{candidate_id}_{pmcid}.xml"
        )

        if (
            xml_path.exists()
            and not args.overwrite
        ):
            is_valid, validation_error = (
                existing_xml_is_valid(
                    xml_path
                )
            )

            if is_valid:
                print(
                    "  Skipped existing "
                    "valid full-text XML."
                )
                skipped_count += 1
                continue

            print(
                "  Existing XML is invalid: "
                f"{validation_error}"
            )
            print(
                "  Attempting fresh retrieval."
            )

        attempted_urls = [
            url
            for _, url in retrieval_sources(
                pmcid
            )
        ]

        try:
            (
                content,
                requested_url,
                final_url,
                http_status,
                retrieval_source,
                previous_failures,
            ) = retrieve_full_text_xml(
                pmcid,
                args.timeout,
            )

            xml_path.write_bytes(content)

            root = validate_full_text_xml(
                content
            )

            article_count = len(
                elements_by_local_name(
                    root,
                    "article",
                )
            )
            body_count = len(
                elements_by_local_name(
                    root,
                    "body",
                )
            )
            table_count = len(
                elements_by_local_name(
                    root,
                    "table-wrap",
                )
            )
            figure_count = len(
                elements_by_local_name(
                    root,
                    "fig",
                )
            )

            write_json(
                metadata_path,
                {
                    "candidate_id": (
                        candidate_id
                    ),
                    "gold_candidate_id": (
                        row.get(
                            "gold_candidate_id"
                        )
                    ),
                    "pmid": (
                        row.get("pmid")
                        or None
                    ),
                    "pmcid": pmcid,
                    "doi": (
                        row.get("doi")
                        or None
                    ),
                    "retrieval_source": (
                        retrieval_source
                    ),
                    "attempted_urls": (
                        attempted_urls
                    ),
                    "previous_failures": (
                        previous_failures
                    ),
                    "requested_url": (
                        requested_url
                    ),
                    "final_url": final_url,
                    "http_status": (
                        http_status
                    ),
                    "retrieved_at": (
                        retrieved_at
                    ),
                    "content_type": (
                        "application/xml"
                    ),
                    "byte_count": len(
                        content
                    ),
                    "sha256": sha256_bytes(
                        content
                    ),
                    "article_count": (
                        article_count
                    ),
                    "body_count": (
                        body_count
                    ),
                    "table_count": (
                        table_count
                    ),
                    "figure_count": (
                        figure_count
                    ),
                    "xml_path": str(
                        xml_path
                    ),
                    "status": "success",
                },
            )

            print(
                "  Retrieved "
                f"{len(content)} bytes "
                f"from {retrieval_source}."
            )
            print(
                "  Content: "
                f"{table_count} tables, "
                f"{figure_count} figures."
            )

            success_count += 1

        except (
            RuntimeError,
            OSError,
            ET.ParseError,
            ValueError,
        ) as error:
            failure_count += 1

            write_json(
                metadata_path,
                {
                    "candidate_id": (
                        candidate_id
                    ),
                    "gold_candidate_id": (
                        row.get(
                            "gold_candidate_id"
                        )
                    ),
                    "pmid": (
                        row.get("pmid")
                        or None
                    ),
                    "pmcid": pmcid,
                    "doi": (
                        row.get("doi")
                        or None
                    ),
                    "attempted_urls": (
                        attempted_urls
                    ),
                    "retrieved_at": (
                        retrieved_at
                    ),
                    "status": "failed",
                    "error_type": type(
                        error
                    ).__name__,
                    "error": str(error),
                },
            )

            print(
                "  Failed: "
                f"{type(error).__name__}: "
                f"{error}"
            )

        if index < len(selected):
            time.sleep(args.delay)

    print()
    print(
        "Successful retrievals: "
        f"{success_count}"
    )
    print(
        "Existing files skipped: "
        f"{skipped_count}"
    )
    print(
        "Failed retrievals: "
        f"{failure_count}"
    )
    print(
        "Selected papers processed: "
        f"{len(selected)}"
    )

    if failure_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
