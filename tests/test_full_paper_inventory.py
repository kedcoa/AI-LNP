import json
from pathlib import Path

import fitz

from src.extraction.full_paper_inventory import build_full_paper_evidence


def _write_html(path: Path, body: str) -> None:
    path.write_text(f"<!doctype html><html><body>{body}</body></html>")


def _write_pdf(path: Path, pages: list[list[str]]) -> None:
    document = fitz.open()
    for lines in pages:
        page = document.new_page(width=612, height=792)
        for index, line in enumerate(lines):
            page.insert_text((54, 54 + index * 32), line)
    document.save(path)


def test_html_preserves_arbitrary_nested_headings_and_content_types(
    tmp_path: Path,
):
    """Flattening the HTML tree would lose source-native section context."""
    html_path = tmp_path / "paper.html"
    _write_html(
        html_path,
        """
        <h1>A Map Without Conventional Labels</h1>
        <p>Overview evidence remains available.</p>
        <h2>Adaptive Delivery Workflow</h2>
        <p>Formulations were prepared by microfluidic mixing.</p>
        <h3>Readouts Beyond Baseline</h3>
        <ul><li>The payload was messenger RNA.</li></ul>
        <table>
          <caption>Assay overview</caption>
          <tr><th>Model</th><th>Result</th></tr>
          <tr><td>Mouse model</td><td>Increased expression</td></tr>
        </table>
        <figure><figcaption>Primary cells retained reporter activity.</figcaption></figure>
        """,
    )

    inventory = build_full_paper_evidence("PAPER-HTML", html_path)

    assert [block.heading for block in inventory.evidence_blocks] == [
        "A Map Without Conventional Labels",
        "A Map Without Conventional Labels > Adaptive Delivery Workflow",
        (
            "A Map Without Conventional Labels > Adaptive Delivery Workflow"
            " > Readouts Beyond Baseline"
        ),
        (
            "A Map Without Conventional Labels > Adaptive Delivery Workflow"
            " > Readouts Beyond Baseline"
        ),
        (
            "A Map Without Conventional Labels > Adaptive Delivery Workflow"
            " > Readouts Beyond Baseline"
        ),
        (
            "A Map Without Conventional Labels > Adaptive Delivery Workflow"
            " > Readouts Beyond Baseline"
        ),
        (
            "A Map Without Conventional Labels > Adaptive Delivery Workflow"
            " > Readouts Beyond Baseline"
        ),
    ]
    assert [block.text for block in inventory.evidence_blocks] == [
        "Overview evidence remains available.",
        "Formulations were prepared by microfluidic mixing.",
        "The payload was messenger RNA.",
        "Assay overview",
        "Model | Result",
        "Mouse model | Increased expression",
        "Primary cells retained reporter activity.",
    ]
    assert {block.page_number for block in inventory.evidence_blocks} == {1}


def test_html_retains_numbered_list_scientific_evidence(tmp_path: Path):
    """Numbered HTML list evidence must never be reclassified as a heading."""
    html_path = tmp_path / "numbered-list.html"
    _write_html(
        html_path,
        """
        <h2>Study activities</h2>
        <ol>
          <li>1. The formulation was prepared by mixing.</li>
          <li>2. Primary cells showed increased reporter expression.</li>
        </ol>
        """,
    )

    inventory = build_full_paper_evidence("PAPER-LIST", html_path)

    assert [block.text for block in inventory.evidence_blocks] == [
        "1. The formulation was prepared by mixing.",
        "2. Primary cells showed increased reporter expression.",
    ]
    assert [block.heading for block in inventory.evidence_blocks] == [
        "Study activities",
        "Study activities",
    ]
    assert {"formulation", "preparation_method"} <= set(
        inventory.evidence_blocks[0].retrieval_tags
    )


def test_pdf_reuses_docling_text_order_heading_levels_and_page_provenance(
    tmp_path: Path,
):
    """Ignoring Docling body structure would flatten headings or reorder evidence."""
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"Docling structure is supplied; PDF is not opened.")
    docling_path = tmp_path / "paper.docling.json"
    docling_path.write_text(
        json.dumps(
            {
                "schema_name": "DoclingDocument",
                "version": "1.9.0",
                "name": "paper",
                "body": {
                    "self_ref": "#/body",
                    "children": [
                        {"$ref": "#/texts/0"},
                        {"$ref": "#/texts/1"},
                        {"$ref": "#/groups/0"},
                    ],
                },
                "groups": [
                    {
                        "self_ref": "#/groups/0",
                        "name": "nested section",
                        "children": [
                            {"$ref": "#/texts/2"},
                            {"$ref": "#/texts/3"},
                        ],
                    }
                ],
                "texts": [
                    {
                        "self_ref": "#/texts/0",
                        "label": "section_header",
                        "level": 1,
                        "text": "Unconventional Framework",
                        "prov": [{"page_no": 1}],
                    },
                    {
                        "self_ref": "#/texts/1",
                        "label": "text",
                        "text": "The payload was messenger RNA.",
                        "prov": [{"page_no": 1}],
                    },
                    {
                        "self_ref": "#/texts/2",
                        "label": "section_header",
                        "level": 2,
                        "text": "Evaluation in living systems",
                        "prov": [{"page_no": 3}],
                    },
                    {
                        "self_ref": "#/texts/3",
                        "label": "list_item",
                        "enumerated": True,
                        "marker": "1.",
                        "text": "The mouse model received an intravenous injection.",
                        "prov": [{"page_no": 3}],
                    },
                ],
                "tables": [],
            }
        )
    )

    inventory = build_full_paper_evidence(
        "PAPER-DOCLING",
        pdf_path,
        docling_path=docling_path,
    )

    assert [block.text for block in inventory.evidence_blocks] == [
        "The payload was messenger RNA.",
        "1. The mouse model received an intravenous injection.",
    ]
    assert [block.heading for block in inventory.evidence_blocks] == [
        "Unconventional Framework",
        "Unconventional Framework > Evaluation in living systems",
    ]
    assert [block.page_number for block in inventory.evidence_blocks] == [1, 3]


def test_raw_pdf_retains_numbered_text_without_heading_inference(tmp_path: Path):
    """Any raw-PDF heading classifier could discard ambiguous numbered evidence."""
    pdf_path = tmp_path / "paper.pdf"
    _write_pdf(
        pdf_path,
        [
            [
                "2. Adaptive delivery workflow",
                "1. The formulation was prepared by mixing",
                "Primary cells showed increased reporter expression.",
            ],
            ["3. Outcomes measured"],
        ],
    )

    inventory = build_full_paper_evidence("PAPER-RAW", pdf_path)

    assert [block.text for block in inventory.evidence_blocks] == [
        "2. Adaptive delivery workflow",
        "1. The formulation was prepared by mixing",
        "Primary cells showed increased reporter expression.",
        "3. Outcomes measured",
    ]
    assert [block.heading for block in inventory.evidence_blocks] == [
        "Unsectioned (page 1)",
        "Unsectioned (page 1)",
        "Unsectioned (page 1)",
        "Unsectioned (page 2)",
    ]
    assert [block.page_number for block in inventory.evidence_blocks] == [1, 1, 1, 2]


def test_inventory_retains_generic_semantic_coverage(tmp_path: Path):
    """Dropping a tag loses required ratio, payload, model, route, cell, or outcome coverage."""
    html_path = tmp_path / "coverage.html"
    _write_html(
        html_path,
        """
        <h1>Experimental record</h1>
        <p>Formulations were prepared by microfluidic mixing.</p>
        <p>Components were combined at a 50:10:40 molar ratio.</p>
        <p>The payload was messenger RNA.</p>
        <p>The mouse model received the dose by intravenous route.</p>
        <p>Primary cells showed increased reporter expression.</p>
        """,
    )

    inventory = build_full_paper_evidence("PAPER-COVERAGE", html_path)

    tags = {tag for block in inventory.evidence_blocks for tag in block.retrieval_tags}
    assert {
        "formulation",
        "preparation_method",
        "component_ratio",
        "ratio_basis",
        "payload",
        "model",
        "species",
        "route",
        "cell",
        "outcome",
    } <= tags
    assert inventory.missing_categories == []
    assert all(row.status == "covered" for row in inventory.coverage_diagnostics)


def test_inventory_ids_are_stable_for_equivalent_normalized_html_text(
    tmp_path: Path,
):
    """Whitespace-only source differences must not change evidence IDs."""
    first_html = tmp_path / "first.html"
    second_html = tmp_path / "second.html"
    _write_html(first_html, "<h1>Methods</h1><p>Payload   was prepared by mixing.</p>")
    _write_html(second_html, "<h1>Methods</h1><p>Payload was prepared by mixing.</p>")

    first = build_full_paper_evidence("PAPER-STABLE", first_html)
    second = build_full_paper_evidence("PAPER-STABLE", second_html)

    assert first.evidence_blocks[0].text == "Payload was prepared by mixing."
    assert second.evidence_blocks[0].text == "Payload was prepared by mixing."
    assert first.evidence_blocks[0].evidence_id == second.evidence_blocks[0].evidence_id


def test_inventory_reports_missing_categories_without_creating_evidence(
    tmp_path: Path,
):
    """Absent source evidence must remain a gap rather than an inferred fact."""
    html_path = tmp_path / "empty.html"
    _write_html(
        html_path,
        "<h1>Opening perspective</h1><p>This article introduces a general problem.</p>",
    )

    inventory = build_full_paper_evidence("PAPER-MISSING", html_path)

    assert [block.text for block in inventory.evidence_blocks] == [
        "This article introduces a general problem.",
    ]
    assert inventory.missing_categories == [
        "formulation_preparation",
        "component_ratios",
        "payload",
        "model_species_route_cell",
        "outcomes",
    ]
    assert all(
        diagnostic.evidence_ids == []
        for diagnostic in inventory.coverage_diagnostics
        if diagnostic.status == "missing"
    )


def test_inventory_requires_every_tag_for_compound_category_coverage(
    tmp_path: Path,
):
    """A ratio without its basis must remain an actionable partial coverage gap."""
    html_path = tmp_path / "partial-ratio.html"
    _write_html(
        html_path,
        "<h1>Ratio details</h1><p>Components were combined at a 3:1 ratio.</p>",
    )

    inventory = build_full_paper_evidence("PAPER-PARTIAL", html_path)
    diagnostic = next(
        row
        for row in inventory.coverage_diagnostics
        if row.category == "component_ratios"
    )

    assert diagnostic.status == "missing"
    assert diagnostic.evidence_ids == [inventory.evidence_blocks[0].evidence_id]
    assert diagnostic.evidence_ids_by_tag == {
        "component_ratio": [inventory.evidence_blocks[0].evidence_id],
        "ratio_basis": [],
    }
    assert "component_ratios" in inventory.missing_categories


def test_inventory_assigns_distinct_ids_to_duplicate_source_blocks(
    tmp_path: Path,
):
    """Separately located identical blocks need distinct provenance IDs."""
    html_path = tmp_path / "duplicates.html"
    _write_html(
        html_path,
        """
        <h1>Methods</h1>
        <p>Payload was prepared by mixing.</p>
        <p>Payload was prepared by mixing.</p>
        """,
    )

    inventory = build_full_paper_evidence("PAPER-DUPLICATES", html_path)

    assert [block.text for block in inventory.evidence_blocks] == [
        "Payload was prepared by mixing.",
        "Payload was prepared by mixing.",
    ]
    assert len({block.evidence_id for block in inventory.evidence_blocks}) == 2
