from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(
    "data/staging/searches/deduplicated_papers.jsonl"
)
DEFAULT_OUTPUT = Path(
    "data/staging/searches/screening_metadata.jsonl"
)


def element_text(
    element: ET.Element | None,
) -> str | None:
    if element is None:
        return None

    value = " ".join(
        "".join(element.itertext()).split()
    )

    return value or None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line_number, line in enumerate(
            file,
            start=1,
        ):
            if not line.strip():
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON on line {line_number} "
                    f"of {path}: {error}"
                ) from error

    return records


def write_jsonl(
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        for record in records:
            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )


def publication_year(
    article: ET.Element,
) -> str | None:
    candidate_paths = (
        "./MedlineCitation/Article/ArticleDate/Year",
        "./MedlineCitation/Article/Journal/"
        "JournalIssue/PubDate/Year",
        "./MedlineCitation/DateCompleted/Year",
        "./MedlineCitation/DateRevised/Year",
    )

    for path in candidate_paths:
        value = article.findtext(path)

        if value:
            return value.strip()

    medline_date = article.findtext(
        "./MedlineCitation/Article/Journal/"
        "JournalIssue/PubDate/MedlineDate"
    )

    if medline_date:
        for token in medline_date.split():
            if (
                len(token) == 4
                and token.isdigit()
            ):
                return token

    return None


def extract_pubmed_metadata(
    raw_path: Path,
    target_pmid: str,
    xml_cache: dict[Path, ET.Element],
) -> dict[str, Any] | None:
    if raw_path not in xml_cache:
        xml_cache[raw_path] = (
            ET.parse(raw_path).getroot()
        )

    root = xml_cache[raw_path]

    for article in root.findall(
        ".//PubmedArticle"
    ):
        pmid = article.findtext(
            "./MedlineCitation/PMID"
        )

        if pmid != target_pmid:
            continue

        title = element_text(
            article.find(
                "./MedlineCitation/Article/"
                "ArticleTitle"
            )
        )

        abstract_parts = []

        for abstract_element in article.findall(
            "./MedlineCitation/Article/"
            "Abstract/AbstractText"
        ):
            text = element_text(abstract_element)

            if not text:
                continue

            label = abstract_element.attrib.get(
                "Label"
            )

            if label:
                abstract_parts.append(
                    f"{label}: {text}"
                )
            else:
                abstract_parts.append(text)

        publication_types = []

        for type_element in article.findall(
            "./MedlineCitation/Article/"
            "PublicationTypeList/PublicationType"
        ):
            value = element_text(type_element)

            if value:
                publication_types.append(value)

        journal = element_text(
            article.find(
                "./MedlineCitation/Article/"
                "Journal/Title"
            )
        )

        return {
            "title": title,
            "abstract": (
                " ".join(abstract_parts) or None
            ),
            "publication_year": publication_year(
                article
            ),
            "publication_types": sorted(
                set(publication_types)
            ),
            "journal": journal,
            "metadata_source": "pubmed_raw",
        }

    return None


def matching_europe_pmc_item(
    raw_path: Path,
    record: dict[str, Any],
    json_cache: dict[Path, dict[str, Any]],
) -> dict[str, Any] | None:
    if raw_path not in json_cache:
        json_cache[raw_path] = json.loads(
            raw_path.read_text(
                encoding="utf-8"
            )
        )

    results = (
        json_cache[raw_path]
        .get("resultList", {})
        .get("result", [])
    )

    for item in results:
        pmid_match = (
            record.get("pmid")
            and item.get("pmid")
            == record.get("pmid")
        )
        pmcid_match = (
            record.get("pmcid")
            and item.get("pmcid")
            == record.get("pmcid")
        )
        doi_match = (
            record.get("doi")
            and item.get("doi")
            and item.get("doi").lower()
            == record.get("doi").lower()
        )

        if pmid_match or pmcid_match or doi_match:
            return item

    return None


def extract_europe_pmc_metadata(
    raw_path: Path,
    record: dict[str, Any],
    json_cache: dict[Path, dict[str, Any]],
) -> dict[str, Any] | None:
    item = matching_europe_pmc_item(
        raw_path,
        record,
        json_cache,
    )

    if item is None:
        return None

    publication_types = item.get(
        "pubTypeList",
        {}
    ).get(
        "pubType",
        [],
    )

    if isinstance(publication_types, str):
        publication_types = [
            publication_types
        ]

    return {
        "title": item.get("title"),
        "abstract": item.get("abstractText"),
        "publication_year": (
            item.get("pubYear")
        ),
        "publication_types": sorted(
            set(publication_types)
        ),
        "journal": item.get("journalTitle"),
        "metadata_source": "europe_pmc_raw",
    }


def enrich_record(
    record: dict[str, Any],
    xml_cache: dict[Path, ET.Element],
    json_cache: dict[Path, dict[str, Any]],
) -> dict[str, Any]:
    metadata = None

    for occurrence in record.get(
        "source_occurrences",
        [],
    ):
        if occurrence.get("source") != "pubmed":
            continue

        raw_path = Path(
            occurrence["raw_file"]
        )

        if not raw_path.exists():
            continue

        if not record.get("pmid"):
            continue

        metadata = extract_pubmed_metadata(
            raw_path,
            str(record["pmid"]),
            xml_cache,
        )

        if metadata:
            break

    if metadata is None:
        for occurrence in record.get(
            "source_occurrences",
            [],
        ):
            if (
                occurrence.get("source")
                != "europe_pmc"
            ):
                continue

            raw_path = Path(
                occurrence["raw_file"]
            )

            if not raw_path.exists():
                continue

            metadata = (
                extract_europe_pmc_metadata(
                    raw_path,
                    record,
                    json_cache,
                )
            )

            if metadata:
                break

    metadata = metadata or {}

    source_urls = sorted(
        {
            occurrence["source_url"]
            for occurrence in record.get(
                "source_occurrences",
                [],
            )
            if occurrence.get("source_url")
        }
    )

    full_text_status = (
        "potentially_available"
        if record.get("pmcid")
        else "unknown"
    )

    return {
        "candidate_id": record.get(
            "candidate_id"
        ),
        "pmid": record.get("pmid"),
        "pmcid": record.get("pmcid"),
        "doi": record.get("doi"),
        "title": (
            metadata.get("title")
            or record.get("title")
        ),
        "abstract": metadata.get("abstract"),
        "publication_year": metadata.get(
            "publication_year"
        ),
        "publication_types": metadata.get(
            "publication_types",
            [],
        ),
        "journal": metadata.get("journal"),
        "matched_cell_types": record.get(
            "matched_cell_types",
            [],
        ),
        "source_urls": source_urls,
        "full_text_status": full_text_status,
        "metadata_source": metadata.get(
            "metadata_source"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a screening-friendly metadata "
            "view from preserved Day 3 records."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_jsonl(args.input)

    xml_cache: dict[Path, ET.Element] = {}
    json_cache: dict[Path, dict[str, Any]] = {}

    enriched = [
        enrich_record(
            record,
            xml_cache,
            json_cache,
        )
        for record in records
    ]

    write_jsonl(
        args.output,
        enriched,
    )

    abstract_count = sum(
        bool(record.get("abstract"))
        for record in enriched
    )
    publication_type_count = sum(
        bool(record.get("publication_types"))
        for record in enriched
    )

    print(
        f"Wrote {len(enriched)} records "
        f"to {args.output}"
    )
    print(
        f"Records with abstracts: "
        f"{abstract_count}"
    )
    print(
        f"Records with publication types: "
        f"{publication_type_count}"
    )


if __name__ == "__main__":
    main()
