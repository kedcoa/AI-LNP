from pathlib import Path

import fitz

from src.extraction.full_paper_inventory import build_full_paper_evidence


def _write_pdf(path: Path, pages: list[list[str]]) -> None:
    document = fitz.open()
    for lines in pages:
        page = document.new_page(width=612, height=792)
        for index, line in enumerate(lines):
            page.insert_text((54, 54 + index * 32), line)
    document.save(path)


def test_inventory_retains_generic_full_paper_evidence_by_section(tmp_path: Path):
    """A dropped category tag or heading association loses usable local evidence."""
    pdf_path = tmp_path / "paper.pdf"
    _write_pdf(
        pdf_path,
        [
            [
                "Methods",
                "Formulations were prepared by microfluidic mixing.",
                "Components were combined at a 50:10:40 molar ratio.",
                "The payload was messenger RNA.",
            ],
            [
                "Results",
                "The rodent model received the dose by intravenous route.",
                "Primary cells showed increased reporter expression.",
            ],
        ],
    )

    inventory = build_full_paper_evidence("PAPER-1", pdf_path)

    assert [block.page_number for block in inventory.evidence_blocks] == [1, 1, 1, 2, 2]
    assert [block.heading for block in inventory.evidence_blocks] == [
        "Methods", "Methods", "Methods", "Results", "Results",
    ]
    assert [block.text for block in inventory.evidence_blocks] == [
        "Formulations were prepared by microfluidic mixing.",
        "Components were combined at a 50:10:40 molar ratio.",
        "The payload was messenger RNA.",
        "The rodent model received the dose by intravenous route.",
        "Primary cells showed increased reporter expression.",
    ]
    tags = {tag for block in inventory.evidence_blocks for tag in block.retrieval_tags}
    assert {
        "formulation", "preparation_method", "component_ratio", "ratio_basis",
        "payload", "model", "species", "route", "cell", "outcome",
    } <= tags
    assert inventory.missing_categories == []
    assert all(row.status == "covered" for row in inventory.coverage_diagnostics)


def test_inventory_ids_are_stable_for_equivalent_normalized_pdf_text(tmp_path: Path):
    """Whitespace-only extraction differences must not create different evidence IDs."""
    first_pdf = tmp_path / "first.pdf"
    second_pdf = tmp_path / "second.pdf"
    _write_pdf(first_pdf, [["Methods", "Payload   was\tprepared  by mixing."]])
    _write_pdf(second_pdf, [["Methods", "Payload was prepared by mixing."]])

    first = build_full_paper_evidence("PAPER-2", first_pdf)
    second = build_full_paper_evidence("PAPER-2", second_pdf)

    assert first.evidence_blocks[0].text == "Payload was prepared by mixing."
    assert second.evidence_blocks[0].text == "Payload was prepared by mixing."
    assert first.evidence_blocks[0].evidence_id == second.evidence_blocks[0].evidence_id


def test_inventory_reports_missing_categories_without_creating_evidence(tmp_path: Path):
    """Absent evidence must remain an explicit gap rather than an inferred fact."""
    pdf_path = tmp_path / "empty.pdf"
    _write_pdf(pdf_path, [["Introduction", "This article introduces a general problem."]])

    inventory = build_full_paper_evidence("PAPER-3", pdf_path)

    assert [block.text for block in inventory.evidence_blocks] == [
        "This article introduces a general problem.",
    ]
    assert inventory.missing_categories == [
        "formulation_preparation", "component_ratios", "payload",
        "model_species_route_cell", "outcomes",
    ]
    assert all(
        diagnostic.evidence_ids == []
        for diagnostic in inventory.coverage_diagnostics
        if diagnostic.status == "missing"
    )
