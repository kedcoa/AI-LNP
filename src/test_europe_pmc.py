import time

import requests


SEARCH_URL = (
    "https://www.ebi.ac.uk/europepmc/"
    "webservices/rest/search"
)

# Keep this small for a connection test.
RESULTS_PER_CELL_TYPE = 3


LNP_QUERY = """
(
    TITLE_ABS:"lipid nanoparticle"
    OR TITLE_ABS:"lipid nanoparticles"
    OR TITLE_ABS:LNP
    OR TITLE_ABS:LNPs
)
"""


PAYLOAD_QUERY = """
(
    TITLE_ABS:mRNA
    OR TITLE_ABS:"messenger RNA"
    OR TITLE_ABS:siRNA
    OR TITLE_ABS:"small interfering RNA"
    OR TITLE_ABS:saRNA
    OR TITLE_ABS:"self-amplifying RNA"
    OR TITLE_ABS:circRNA
    OR TITLE_ABS:"circular RNA"
)
"""


CELL_QUERIES = {
    "hepatocyte": """
    (
        TITLE_ABS:hepatocyte
        OR TITLE_ABS:hepatocytes
    )
    """,

    "Kupffer cell": """
    (
        TITLE_ABS:"Kupffer cell"
        OR TITLE_ABS:"Kupffer cells"
        OR TITLE_ABS:"liver macrophage"
        OR TITLE_ABS:"liver macrophages"
    )
    """,

    "LSEC": """
    (
        TITLE_ABS:"liver sinusoidal endothelial cell"
        OR TITLE_ABS:"liver sinusoidal endothelial cells"
        OR TITLE_ABS:LSEC
        OR TITLE_ABS:LSECs
    )
    """,

    "HSC": """
    (
        TITLE_ABS:"hepatic stellate cell"
        OR TITLE_ABS:"hepatic stellate cells"
    )
    """,
}


EXCLUSION_QUERY = """
NOT
(
    TITLE_ABS:"CAR-T"
    OR TITLE_ABS:"CAR T"
    OR TITLE_ABS:"chimeric antigen receptor"
    OR TITLE_ABS:CRISPR
    OR TITLE_ABS:Cas9
)
"""


def clean_query(query):
    """Collapse a multiline query into one line."""
    return " ".join(query.split())


def search_europe_pmc(session, query):
    """Search Europe PMC and return its count and records."""
    response = session.get(
        SEARCH_URL,
        params={
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": RESULTS_PER_CELL_TYPE,
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    hit_count = int(data.get("hitCount", 0))

    results = (
        data.get("resultList", {})
        .get("result", [])
    )

    return hit_count, results


def record_identifier(record):
    """
    Produce a stable identifier for deduplication.

    Prefer PMID, then PMCID, then the article's Europe PMC ID.
    """
    pmid = record.get("pmid")

    if pmid:
        return f"PMID:{pmid}"

    pmcid = record.get("pmcid")

    if pmcid:
        return f"PMCID:{pmcid}"

    source = record.get("source", "unknown")
    article_id = record.get("id", "")

    if article_id:
        return f"{source}:{article_id}"

    # Last-resort identifier for unusual records.
    title = record.get("title", "untitled")
    return f"TITLE:{title.lower().strip()}"


def article_url(record):
    """Create a browser URL for a Europe PMC record."""
    pmid = record.get("pmid")

    if pmid:
        return f"https://europepmc.org/article/MED/{pmid}"

    pmcid = record.get("pmcid")

    if pmcid:
        return f"https://europepmc.org/article/PMC/{pmcid}"

    source = record.get("source")
    article_id = record.get("id")

    if source and article_id:
        return (
            f"https://europepmc.org/article/"
            f"{source}/{article_id}"
        )

    return "not reported"


def main():
    session = requests.Session()

    # Each identifier maps to its record and matching cell types.
    unique_records = {}

    print("Testing Europe PMC searches...\n")

    for cell_type, cell_query in CELL_QUERIES.items():
        full_query = clean_query(
            f"""
            {LNP_QUERY}
            AND {PAYLOAD_QUERY}
            AND {cell_query}
            AND HAS_ABSTRACT:Y
            {EXCLUSION_QUERY}
            """
        )

        hit_count, results = search_europe_pmc(
            session,
            full_query,
        )

        print(
            f"{cell_type}: "
            f"{hit_count} total matches; "
            f"testing {len(results)} records."
        )

        for record in results:
            identifier = record_identifier(record)

            if identifier not in unique_records:
                unique_records[identifier] = {
                    "record": record,
                    "cell_types": set(),
                }

            unique_records[identifier][
                "cell_types"
            ].add(cell_type)

        # Avoid sending requests too quickly.
        time.sleep(0.3)

    print(
        f"\nUnique test records: {len(unique_records)}"
    )

    for item in unique_records.values():
        record = item["record"]
        matched_cells = ", ".join(
            sorted(item["cell_types"])
        )

        pmid = record.get("pmid", "not reported")
        pmcid = record.get("pmcid", "not reported")
        year = record.get("pubYear", "not reported")
        title = record.get("title", "not reported")
        abstract = record.get(
            "abstractText",
            "not reported",
        )
        authors = record.get(
            "authorString",
            "not reported",
        )
        journal = record.get(
            "journalTitle",
            "not reported",
        )
        open_access = record.get(
            "isOpenAccess",
            "not reported",
        )

        print("\n" + "=" * 70)
        print(f"Matched cell type: {matched_cells}")
        print(f"PMID: {pmid}")
        print(f"PMCID: {pmcid}")
        print(f"Year: {year}")
        print(f"Title: {title}")
        print(f"Authors: {authors}")
        print(f"Journal: {journal}")
        print(f"Open access: {open_access}")
        print(f"Abstract: {abstract}")
        print(f"URL: {article_url(record)}")

    print(
        "\nEurope PMC connection test successful. "
        "No files were saved."
    )


if __name__ == "__main__":
    main()