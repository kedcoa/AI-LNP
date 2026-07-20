import os
import time
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv


load_dotenv()

SEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)
FETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)

# Keep this small while testing.
RESULTS_PER_CELL_TYPE = 3

NCBI_EMAIL = os.getenv("NCBI_EMAIL", "")
TOOL_NAME = "AI_LNP_literature_tool"


LNP_QUERY = """
(
    "lipid nanoparticle"[Title/Abstract]
    OR "lipid nanoparticles"[Title/Abstract]
    OR LNP[Title/Abstract]
    OR LNPs[Title/Abstract]
)
"""


PAYLOAD_QUERY = """
(
    mRNA[Title/Abstract]
    OR "messenger RNA"[Title/Abstract]
    OR siRNA[Title/Abstract]
    OR "small interfering RNA"[Title/Abstract]
    OR saRNA[Title/Abstract]
    OR "self-amplifying RNA"[Title/Abstract]
    OR circRNA[Title/Abstract]
    OR "circular RNA"[Title/Abstract]
)
"""


CELL_QUERIES = {
    "hepatocyte": """
    (
        hepatocyte[Title/Abstract]
        OR hepatocytes[Title/Abstract]
    )
    """,

    "Kupffer cell": """
    (
        "Kupffer cell"[Title/Abstract]
        OR "Kupffer cells"[Title/Abstract]
        OR "liver macrophage"[Title/Abstract]
        OR "liver macrophages"[Title/Abstract]
    )
    """,

    "LSEC": """
    (
        "liver sinusoidal endothelial cell"[Title/Abstract]
        OR "liver sinusoidal endothelial cells"[Title/Abstract]
        OR LSEC[Title/Abstract]
        OR LSECs[Title/Abstract]
    )
    """,

    "HSC": """
    (
        "hepatic stellate cell"[Title/Abstract]
        OR "hepatic stellate cells"[Title/Abstract]
    )
    """,
}


EXCLUSION_QUERY = """
NOT
(
    "CAR-T"[Title/Abstract]
    OR "CAR T"[Title/Abstract]
    OR "chimeric antigen receptor"[Title/Abstract]
    OR CRISPR[Title/Abstract]
    OR Cas9[Title/Abstract]
)
"""


def clean_query(query):
    """Collapse a multiline query into one line."""
    return " ".join(query.split())


def element_text(element):
    """Extract text from a PubMed XML element."""
    if element is None:
        return "not reported"

    return " ".join(
        "".join(element.itertext()).split()
    )


def extract_year(article):
    """Extract the publication year."""
    possible_paths = [
        "./MedlineCitation/Article/Journal/"
        "JournalIssue/PubDate/Year",

        "./MedlineCitation/Article/ArticleDate/Year",

        "./MedlineCitation/DateCompleted/Year",
    ]

    for path in possible_paths:
        element = article.find(path)

        if element is not None and element.text:
            return element.text.strip()

    medline_date = article.find(
        "./MedlineCitation/Article/Journal/"
        "JournalIssue/PubDate/MedlineDate"
    )

    if medline_date is not None and medline_date.text:
        return medline_date.text.strip()[:4]

    return "not reported"


def extract_abstract(article):
    """Combine the sections of a PubMed abstract."""
    elements = article.findall(
        "./MedlineCitation/Article/Abstract/AbstractText"
    )

    if not elements:
        return "not reported"

    sections = []

    for element in elements:
        text = element_text(element)
        label = element.attrib.get("Label")

        if label:
            sections.append(f"{label}: {text}")
        else:
            sections.append(text)

    return " ".join(sections)


def search_pubmed(session, query):
    """Search PubMed and return its count and PMIDs."""
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": RESULTS_PER_CELL_TYPE,
        "retmode": "json",
        "sort": "relevance",
        "tool": TOOL_NAME,
    }

    if NCBI_EMAIL:
        params["email"] = NCBI_EMAIL

    response = session.get(
        SEARCH_URL,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    result = response.json()["esearchresult"]

    return int(result["count"]), result["idlist"]


def fetch_pubmed_records(session, pmids):
    """Retrieve PubMed records for the selected PMIDs."""
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "tool": TOOL_NAME,
    }

    if NCBI_EMAIL:
        params["email"] = NCBI_EMAIL

    response = session.get(
        FETCH_URL,
        params=params,
        timeout=60,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    return root.findall("./PubmedArticle")


def main():
    session = requests.Session()

    # A PMID may be returned by more than one cell-type query.
    pmid_to_cell_types = {}

    print("Testing PubMed searches...\n")

    for cell_type, cell_query in CELL_QUERIES.items():
        full_query = clean_query(
            f"""
            {LNP_QUERY}
            AND {PAYLOAD_QUERY}
            AND {cell_query}
            AND hasabstract
            {EXCLUSION_QUERY}
            """
        )

        total_count, pmids = search_pubmed(
            session,
            full_query,
        )

        print(
            f"{cell_type}: "
            f"{total_count} total matches; "
            f"testing {len(pmids)} records."
        )

        for pmid in pmids:
            pmid_to_cell_types.setdefault(
                pmid,
                set(),
            ).add(cell_type)

        # Keep the request rate gentle for NCBI.
        time.sleep(0.4)

    unique_pmids = list(pmid_to_cell_types)

    print(
        f"\nUnique test records: {len(unique_pmids)}"
    )

    articles = fetch_pubmed_records(
        session,
        unique_pmids,
    )

    for article in articles:
        pmid = element_text(
            article.find("./MedlineCitation/PMID")
        )

        title = element_text(
            article.find(
                "./MedlineCitation/Article/ArticleTitle"
            )
        )

        year = extract_year(article)
        abstract = extract_abstract(article)

        matched_cells = ", ".join(
            sorted(pmid_to_cell_types.get(pmid, set()))
        )

        print("\n" + "=" * 70)
        print(f"PMID: {pmid}")
        print(f"Matched cell type: {matched_cells}")
        print(f"Year: {year}")
        print(f"Title: {title}")
        print(f"Abstract: {abstract}")
        print(
            f"URL: https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        )

    print(
        "\nPubMed connection test successful. "
        "No files were saved."
    )


if __name__ == "__main__":
    main()