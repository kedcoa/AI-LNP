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


def test_inventory_requires_every_tag_for_compound_category_coverage(tmp_path: Path):
    """A ratio without its basis must remain an actionable partial coverage gap."""
    pdf_path = tmp_path / "partial-ratio.pdf"
    _write_pdf(
        pdf_path,
        [["Ratio Details", "Components were combined at a 3:1 ratio."]],
    )

    inventory = build_full_paper_evidence("PAPER-4", pdf_path)
    diagnostic = next(
        row for row in inventory.coverage_diagnostics
        if row.category == "component_ratios"
    )

    assert diagnostic.status == "missing"
    assert diagnostic.evidence_ids == [inventory.evidence_blocks[0].evidence_id]
    assert diagnostic.evidence_ids_by_tag == {
        "component_ratio": [inventory.evidence_blocks[0].evidence_id],
        "ratio_basis": [],
    }
    assert "component_ratios" in inventory.missing_categories


def test_inventory_assigns_distinct_ids_to_duplicate_source_blocks(tmp_path: Path):
    """Two separately located identical blocks need separate provenance IDs."""
    pdf_path = tmp_path / "duplicates.pdf"
    _write_pdf(
        pdf_path,
        [["Methods", "Payload was prepared by mixing.", "Payload was prepared by mixing."]],
    )

    inventory = build_full_paper_evidence("PAPER-5", pdf_path)

    assert [block.text for block in inventory.evidence_blocks] == [
        "Payload was prepared by mixing.", "Payload was prepared by mixing.",
    ]
    assert len({block.evidence_id for block in inventory.evidence_blocks}) == 2


def test_inventory_retains_non_enumerated_title_like_heading(tmp_path: Path):
    """Unknown section titles must retain their exact source heading context."""
    pdf_path = tmp_path / "heading.pdf"
    _write_pdf(
        pdf_path,
        [["Adaptive Delivery Workflow", "Payload was prepared by mixing."]],
    )

    inventory = build_full_paper_evidence("PAPER-6", pdf_path)

    payload = next(
        block for block in inventory.evidence_blocks
        if block.text == "Payload was prepared by mixing."
    )
    assert payload.heading == "Adaptive Delivery Workflow"


def test_inventory_retains_numbered_prose_list_item_as_evidence(tmp_path: Path):
    """A numbered list item is evidence, not an automatically inferred section."""
    pdf_path = tmp_path / "numbered-list.pdf"
    _write_pdf(
        pdf_path,
        [["1. The formulation was prepared by mixing"]],
    )

    inventory = build_full_paper_evidence("PAPER-7", pdf_path)

    assert [block.text for block in inventory.evidence_blocks] == [
        "1. The formulation was prepared by mixing",
    ]
    assert {"formulation", "preparation_method"} <= set(
        inventory.evidence_blocks[0].retrieval_tags
    )


def test_inventory_recognizes_numbered_title_like_section_heading(tmp_path: Path):
    """A numbered title-like label still supplies section context."""
    pdf_path = tmp_path / "numbered-heading.pdf"
    _write_pdf(
        pdf_path,
        [["2. Adaptive Delivery Workflow", "Payload was prepared by mixing."]],
    )

    inventory = build_full_paper_evidence("PAPER-8", pdf_path)

    assert [block.heading for block in inventory.evidence_blocks] == [
        "2. Adaptive Delivery Workflow",
    ]


def test_inventory_recognizes_numbered_sentence_case_section_headings(tmp_path: Path):
    """Sentence-case numbered section labels must retain their exact context."""
    pdf_path = tmp_path / "sentence-case-numbered-headings.pdf"
    _write_pdf(
        pdf_path,
        [
            [
                "2. Adaptive delivery workflow",
                "Payload was prepared by mixing.",
                "2. In vivo evaluation",
                "The animal model received the dose by intravenous route.",
            ],
        ],
    )

    inventory = build_full_paper_evidence("PAPER-9", pdf_path)

    assert [block.heading for block in inventory.evidence_blocks] == [
        "2. Adaptive delivery workflow",
        "2. In vivo evaluation",
    ]


def test_inventory_recognizes_concise_numbered_labels_without_lexical_vetoes(
    tmp_path: Path,
):
    """Numbered labels remain headings regardless of generic wording."""
    pdf_path = tmp_path / "concise-numbered-labels.pdf"
    _write_pdf(
        pdf_path,
        [
            [
                "2. Materials used",
                "Payload was prepared by mixing.",
                "3. Outcomes measured",
                "Primary cells showed increased expression.",
                "4. The impact of formulation on delivery",
                "The animal model received the dose by intravenous route.",
            ],
        ],
    )

    inventory = build_full_paper_evidence("PAPER-10", pdf_path)

    assert [block.heading for block in inventory.evidence_blocks] == [
        "2. Materials used",
        "3. Outcomes measured",
        "4. The impact of formulation on delivery",
    ]
