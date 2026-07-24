from pathlib import Path

import fitz

from src.extraction.pdf_multimodal_contracts import ObjectVisionExtraction
from src.extraction.reconstruct_pdf_objects import (
    CAPTION_RE,
    is_caption_candidate,
    reconstruct_file,
    render,
)
from src.extraction.run_object_vision import audit


def test_reconstruction_creates_caption_linked_crop(tmp_path: Path):
    path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect((50, 50, 350, 300))
    page.insert_text((50, 330), "Figure 2. Phagocytosis index by treatment.")
    doc.save(path)
    rows = reconstruct_file(path, "GP-X", tmp_path / "output")
    assert len(rows) == 1
    assert rows[0].label == "Figure 2."
    assert (Path(rows[0].crop_path).name).endswith(".png")


def test_object_crop_rendering_preserves_small_label_resolution():
    import inspect

    assert inspect.signature(render).parameters["zoom"].default >= 4.0


def test_body_figure_reference_block_is_not_a_caption():
    text = "Fig. 1B Fig. 1E"
    match = CAPTION_RE.match(text)
    assert match is not None
    assert not is_caption_candidate(text, match)


def test_long_caption_without_separator_is_retained():
    text = (
        "Fig. 1 A single IV injection of Luc mRNA-LNP induces robust and restricted "
        "luciferase activity in liver. " + "Caption details. " * 5
    )
    match = CAPTION_RE.match(text)
    assert match is not None
    assert is_caption_candidate(text, match)


def test_axis_tick_numeric_fact_is_rejected():
    result = ObjectVisionExtraction.model_validate({
        "object_id": "O1",
        "readability": "readable",
        "object_type": "bar_chart",
        "panels_detected": ["B"],
        "raw_panel_labels": [],
        "printed_facts": [{
            "fact_id": "F1", "panel": "B", "population": "cells",
            "intervention": "treatment", "endpoint": "index", "value": "34",
            "unit": "%", "visible_support": "axis ticks 0, 20, 40",
            "support_kind": "axis_tick", "confidence": "low",
        }],
        "qualitative_comparisons": [],
        "excluded_estimates": [],
        "unresolved_ambiguities": [],
        "acceptance_status": "machine_readable",
    })
    assert audit(result) == ["F1: axis tick alone cannot support a measured value"]
