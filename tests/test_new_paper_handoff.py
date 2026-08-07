from __future__ import annotations

from pathlib import Path

from src.extraction.new_paper_handoff import (
    ScreenedCandidate,
    run_new_paper_handoff,
)


FIXTURE = Path(__file__).parent / "fixtures/new_paper_handoff"


def fixture_candidate(paper_id: str) -> ScreenedCandidate:
    return ScreenedCandidate(
        paper_id=paper_id,
        title="Generic new-paper fixture",
        screening_disposition="include",
        source_paths=(FIXTURE / "article.nxml",),
        extraction_bundle_path=FIXTURE / "extraction_bundle.json",
    )


def test_new_paper_reaches_combined_table_without_special_case(
    tmp_path: Path,
) -> None:
    result = run_new_paper_handoff(
        fixture_candidate("NEW-TEST-001"), tmp_path
    )

    assert result.screening_disposition == "include"
    assert result.source_fact_accounting_balanced is True
    assert result.imported_arm_ids
    assert result.visible_in_combined_table is True
    assert result.discovered_assets == ("supplement.pdf",)
    assert result.paper_specific_adapter is None
    assert result.database_path.is_file()


def test_new_paper_handoff_rejects_bundle_for_another_paper(
    tmp_path: Path,
) -> None:
    candidate = fixture_candidate("WRONG-ID")

    try:
        run_new_paper_handoff(candidate, tmp_path)
    except ValueError as error:
        assert "paper ID" in str(error)
    else:
        raise AssertionError("mismatched paper ID was accepted")
