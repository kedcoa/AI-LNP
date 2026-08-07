from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from src.init_db import initialize_database
from src.screening.start_new_paper_batch import (
    deduplicate_against_database,
    select_balanced_full_text_batch,
    screen_candidate,
)


def candidate(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "candidate_id": "candidate_00001",
        "pmid": "123",
        "pmcid": "PMC123",
        "doi": "10.1/example",
        "title": "mRNA LNP delivery to Kupffer cells",
        "abstract": (
            "We administered an ionizable lipid nanoparticle carrying mRNA "
            "to mice and measured reporter expression in Kupffer cells. "
            "The tested LNP increased expression relative to control."
        ),
        "publication_types": ["Journal Article"],
        "matched_cell_types": ["kupffer"],
    }
    value.update(updates)
    return value


def database_with_existing_paper(path: Path) -> Path:
    initialize_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO paper (
                source_paper_id,pmid,pmcid,doi,title,source_type,
                retrieval_date,screening_status,import_status
            ) VALUES ('OLD-1','123','PMC123','10.1/example','Different title',
                      'full_text','2026-08-07','include','ready')
            """
        )
    return path


def test_deduplication_uses_stable_identifiers_before_title(tmp_path: Path) -> None:
    database = database_with_existing_paper(tmp_path / "evidence.db")

    novel, duplicates = deduplicate_against_database(
        [candidate(), candidate(candidate_id="candidate_00002", pmid="999", pmcid="PMC999", doi="10.1/new")],
        database,
    )

    assert [row["candidate_id"] for row in novel] == ["candidate_00002"]
    assert duplicates[0]["duplicate_of"] == "OLD-1"
    assert "pmid:123" in duplicates[0]["matching_keys"]


def test_strong_original_abstract_is_provisionally_included() -> None:
    decision = screen_candidate(candidate())

    assert decision["decision"] == "include"
    assert decision["screening_scope"] == "automatic_abstract_screen"
    assert set(decision["reason_codes"]) == {
        "ORIGINAL_EXPERIMENT",
        "IDENTIFIABLE_LNP",
        "SUPPORTED_PAYLOAD",
        "TARGET_CELL_EVIDENCE",
        "USABLE_FORMULATION_OUTCOME_LINKAGE",
    }


def test_ambiguous_abstract_waits_for_full_text() -> None:
    decision = screen_candidate(
        candidate(abstract="Lipid nanoparticles and hepatocytes are discussed.")
    )

    assert decision["decision"] == "manual_review"
    assert decision["reason_codes"] == ["FULL_TEXT_REQUIRED"]


def test_polymeric_micelle_comparator_is_not_mistaken_for_an_lnp() -> None:
    decision = screen_candidate(
        candidate(
            title="Ionizable polymeric micelles for siRNA delivery",
            abstract=(
                "Lipid nanoparticles have limitations. We developed ionizable "
                "polymeric micelles carrying siRNA for hepatic stellate cells, "
                "a delivery system differentiated from LNPs."
            ),
            matched_cell_types=["hsc"],
        )
    )

    assert decision["decision"] == "exclude"
    assert decision["reason_codes"] == ["NOT_ELIGIBLE_LNP"]


def test_full_text_selection_is_balanced_and_requires_pmcid() -> None:
    screened = []
    cell_names = {
        "hepatocyte": "hepatocytes",
        "kupffer": "Kupffer cells",
        "lsec": "liver sinusoidal endothelial cells",
    }
    for index, cell in enumerate(("hepatocyte", "hepatocyte", "kupffer", "lsec"), 1):
        row = candidate(
            candidate_id=f"candidate_{index:05d}",
            pmid=str(index),
            pmcid=None if index == 2 else f"PMC{index}",
            doi=f"10.1/{index}",
            matched_cell_types=[cell],
            abstract=(
                "We administered an ionizable lipid nanoparticle carrying "
                f"mRNA to mice and measured reporter expression in {cell_names[cell]}. "
                "The tested LNP increased expression relative to control."
            ),
        )
        screened.append({**row, **screen_candidate(row)})

    selected = select_balanced_full_text_batch(screened, per_cell=1)

    assert [row["candidate_id"] for row in selected] == [
        "candidate_00001",
        "candidate_00003",
        "candidate_00004",
    ]
