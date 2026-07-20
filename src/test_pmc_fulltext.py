import xml.etree.ElementTree as ET

import requests


EUROPE_PMC_SEARCH_URL = (
    "https://www.ebi.ac.uk/europepmc/"
    "webservices/rest/search"
)

NCBI_PMC_FETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/"
    "entrez/eutils/efetch.fcgi"
)


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


LIVER_CELL_QUERY = """
(
    TITLE_ABS:hepatocyte
    OR TITLE_ABS:hepatocytes
    OR TITLE_ABS:"Kupffer cell"
    OR TITLE_ABS:"Kupffer cells"
    OR TITLE_ABS:"liver macrophage"
    OR TITLE_ABS:"liver macrophages"
    OR TITLE_ABS:"liver sinusoidal endothelial cell"
    OR TITLE_ABS:"liver sinusoidal endothelial cells"
    OR TITLE_ABS:LSEC
    OR TITLE_ABS:LSECs
    OR TITLE_ABS:"hepatic stellate cell"
    OR TITLE_ABS:"hepatic stellate cells"
)
"""


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


def element_text(element):
    """Extract and clean all text inside an XML element."""
    if element is None:
        return "not reported"

    return " ".join(
        "".join(element.itertext()).split()
    )


def find_open_access_paper():
    """
    Find one relevant open-access paper with a PMCID.

    Europe PMC is used to locate the paper and its PMCID.
    """
    query = clean_query(
        f"""
        {LNP_QUERY}
        AND {PAYLOAD_QUERY}
        AND {LIVER_CELL_QUERY}
        AND OPEN_ACCESS:Y
        AND HAS_FT:Y
        {EXCLUSION_QUERY}
        """
    )

    response = requests.get(
        EUROPE_PMC_SEARCH_URL,
        params={
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": 10,
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    results = (
        data.get("resultList", {})
        .get("result", [])
    )

    for result in results:
        if result.get("pmcid"):
            return result

    raise RuntimeError(
        "No relevant open-access paper with a PMCID "
        "was found by the test query."
    )


def fetch_pmc_full_text(pmcid):
    """
    Retrieve one full-text article from NCBI PMC as XML.
    """
    # NCBI EFetch accepts the numeric portion of the PMCID.
    numeric_pmcid = pmcid.removeprefix("PMC")

    response = requests.get(
        NCBI_PMC_FETCH_URL,
        params={
            "db": "pmc",
            "id": numeric_pmcid,
            "retmode": "xml",
        },
        timeout=60,
    )
    response.raise_for_status()

    return response.content


def parse_full_text(xml_content):
    """
    Extract the article body and selected metadata from PMC XML.
    """
    root = ET.fromstring(xml_content)

    article_title = element_text(
        root.find(".//article-title")
    )

    body = root.find(".//body")

    if body is None:
        raise RuntimeError(
            "PMC returned XML, but an article body "
            "was not found."
        )

    full_text = element_text(body)

    if full_text == "not reported":
        raise RuntimeError(
            "PMC returned an empty article body."
        )

    return article_title, full_text


def main():
    print(
        "Searching for one relevant open-access "
        "PMC paper..."
    )

    paper = find_open_access_paper()

    pmid = paper.get("pmid", "not reported")
    pmcid = paper.get("pmcid")
    search_title = paper.get(
        "title",
        "not reported",
    )
    year = paper.get(
        "pubYear",
        "not reported",
    )

    print("\nPaper selected:")
    print(f"PMID: {pmid}")
    print(f"PMCID: {pmcid}")
    print(f"Year: {year}")
    print(f"Title: {search_title}")

    print("\nRetrieving full text from NCBI PMC...")

    xml_content = fetch_pmc_full_text(pmcid)

    article_title, full_text = parse_full_text(
        xml_content
    )

    print("\nPMC full-text connection successful.")
    print(f"Article title: {article_title}")
    print(f"Full-text characters retrieved: {len(full_text)}")
    print(
        "PMC URL: "
        f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    )

    print("\nBeginning of the article body:")
    print("-" * 70)
    print(full_text[:500])
    print("-" * 70)

    print(
        "\nTest complete. No files were saved."
    )


if __name__ == "__main__":
    main()