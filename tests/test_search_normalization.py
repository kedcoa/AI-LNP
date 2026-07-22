from src.search.build_candidate_index import (
    normalize_doi,
    normalize_pmcid,
    normalize_title,
)


def test_normalize_doi() -> None:
    assert (
        normalize_doi(
            "https://doi.org/10.1000/ABC"
        )
        == "10.1000/abc"
    )


def test_normalize_pmcid() -> None:
    assert normalize_pmcid("12345") == "PMC12345"
    assert (
        normalize_pmcid("pmc12345")
        == "PMC12345"
    )


def test_normalize_title() -> None:
    assert (
        normalize_title(
            "Lipid Nanoparticles: A Study!"
        )
        == "lipid nanoparticles a study"
    )