from __future__ import annotations

import argparse
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def text_of(
    element: ET.Element | None,
) -> str | None:
    if element is None:
        return None

    value = "".join(
        element.itertext()
    ).strip()

    return value or None


def normalize_doi(
    value: str | None,
) -> str | None:
    if not value:
        return None

    normalized = value.strip().lower()

    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "doi:",
    ):
        if normalized.startswith(prefix):
            normalized = normalized[
                len(prefix):
            ]

    return normalized.strip() or None


def normalize_pmcid(
    value: str | None,
) -> str | None:
    if not value:
        return None

    normalized = value.strip().upper()

    if normalized.isdigit():
        normalized = f"PMC{normalized}"

    return normalized


def normalize_title(
    value: str | None,
) -> str | None:
    if not value:
        return None

    normalized = unicodedata.normalize(
        "NFKD",
        value,
    )

    normalized = normalized.lower()

    normalized = re.sub(
        r"[^\w\s]",
        " ",
        normalized,
    )

    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    ).strip()

    return normalized or None


def parse_pubmed_page(
    xml_path: Path,
    cell: str,
) -> list[dict]:
    root = ET.parse(xml_path).getroot()
    records = []

    for article in root.findall(
        ".//PubmedArticle"
    ):
        citation = article.find(
            "./MedlineCitation"
        )

        pmid = text_of(
            citation.find("./PMID")
            if citation is not None
            else None
        )

        title = text_of(
            citation.find(
                "./Article/ArticleTitle"
            )
            if citation is not None
            else None
        )

        doi = None
        pmcid = None

        for identifier in article.findall(
            "./PubmedData/ArticleIdList/ArticleId"
        ):
            id_type = identifier.attrib.get(
                "IdType"
            )
            value = text_of(identifier)

            if id_type == "doi":
                doi = value
            elif id_type == "pmc":
                pmcid = value

        records.append(
            {
                "source": "pubmed",
                "matched_cell_type": cell,
                "pmid": pmid,
                "pmcid": normalize_pmcid(
                    pmcid
                ),
                "doi": normalize_doi(doi),
                "title": title,
                "normalized_title": (
                    normalize_title(title)
                ),
                "source_url": (
                    "https://pubmed.ncbi.nlm.nih.gov/"
                    f"{pmid}/"
                    if pmid
                    else None
                ),
                "raw_file": str(xml_path),
            }
        )

    return records


def parse_europe_pmc_page(
    json_path: Path,
    cell: str,
) -> list[dict]:
    data = json.loads(
        json_path.read_text(
            encoding="utf-8"
        )
    )

    records = []

    for item in (
        data.get("resultList", {})
        .get("result", [])
    ):
        pmid = item.get("pmid")
        pmcid = normalize_pmcid(
            item.get("pmcid")
        )
        doi = normalize_doi(
            item.get("doi")
        )
        title = item.get("title")

        source_id = item.get("id")
        source_database = item.get("source")

        if pmid:
            source_url = (
                "https://europepmc.org/article/"
                f"MED/{pmid}"
            )
        elif source_database and source_id:
            source_url = (
                "https://europepmc.org/article/"
                f"{source_database}/{source_id}"
            )
        else:
            source_url = None

        records.append(
            {
                "source": "europe_pmc",
                "matched_cell_type": cell,
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "title": title,
                "normalized_title": (
                    normalize_title(title)
                ),
                "source_url": source_url,
                "raw_file": str(json_path),
            }
        )

    return records


def write_jsonl(
    path: Path,
    records: list[dict],
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


def record_keys(
    record: dict,
) -> list[str]:
    keys = []

    if record.get("pmid"):
        keys.append(
            f"pmid:{record['pmid']}"
        )

    if record.get("pmcid"):
        keys.append(
            f"pmcid:{record['pmcid']}"
        )

    if record.get("doi"):
        keys.append(
            f"doi:{record['doi']}"
        )

    if record.get("normalized_title"):
        keys.append(
            "title:"
            f"{record['normalized_title']}"
        )

    return keys


def deduplicate(
    records: list[dict],
) -> list[dict]:
    groups = []
    key_to_group = {}

    for record in records:
        matching_group_indexes = {
            key_to_group[key]
            for key in record_keys(record)
            if key in key_to_group
        }

        if not matching_group_indexes:
            group_index = len(groups)

            group = {
                "pmid": record.get("pmid"),
                "pmcid": record.get("pmcid"),
                "doi": record.get("doi"),
                "title": record.get("title"),
                "normalized_title": (
                    record.get(
                        "normalized_title"
                    )
                ),
                "matched_cell_types": set(),
                "source_occurrences": [],
            }

            groups.append(group)

        else:
            group_index = min(
                matching_group_indexes
            )
            group = groups[group_index]

        group["pmid"] = (
            group["pmid"]
            or record.get("pmid")
        )
        group["pmcid"] = (
            group["pmcid"]
            or record.get("pmcid")
        )
        group["doi"] = (
            group["doi"]
            or record.get("doi")
        )
        group["title"] = (
            group["title"]
            or record.get("title")
        )
        group["normalized_title"] = (
            group["normalized_title"]
            or record.get("normalized_title")
        )

        group["matched_cell_types"].add(
            record["matched_cell_type"]
        )

        group["source_occurrences"].append(
            {
                "source": record["source"],
                "cell_type": (
                    record[
                        "matched_cell_type"
                    ]
                ),
                "source_url": (
                    record.get("source_url")
                ),
                "raw_file": (
                    record["raw_file"]
                ),
            }
        )

        for key in record_keys(record):
            key_to_group[key] = group_index

    output = []

    for index, group in enumerate(groups, 1):
        group["candidate_id"] = (
            f"candidate_{index:05d}"
        )

        group["matched_cell_types"] = sorted(
            group["matched_cell_types"]
        )

        output.append(group)

    return output


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "data/staging/searches"
        ),
    )

    args = parser.parse_args()
    run_dir = args.run_dir.resolve()

    records = []

    for cell in (
        "hepatocyte",
        "kupffer",
        "lsec",
        "hsc",
    ):
        pubmed_dir = (
            run_dir / "pubmed" / cell
        )

        for path in sorted(
            pubmed_dir.glob(
                "efetch_page_*.xml"
            )
        ):
            records.extend(
                parse_pubmed_page(
                    path,
                    cell,
                )
            )

        europe_dir = (
            run_dir / "europe_pmc" / cell
        )

        for path in sorted(
            europe_dir.glob(
                "search_page_*.json"
            )
        ):
            records.extend(
                parse_europe_pmc_page(
                    path,
                    cell,
                )
            )

    candidate_path = (
        args.output_dir
        / "candidate_records.jsonl"
    )

    deduplicated_path = (
        args.output_dir
        / "deduplicated_papers.jsonl"
    )

    write_jsonl(
        candidate_path,
        records,
    )

    deduplicated = deduplicate(records)

    write_jsonl(
        deduplicated_path,
        deduplicated,
    )

    print(
        f"Source records: {len(records)}"
    )
    print(
        "Unique candidate papers: "
        f"{len(deduplicated)}"
    )
    print(f"Wrote: {candidate_path}")
    print(f"Wrote: {deduplicated_path}")


if __name__ == "__main__":
    main()