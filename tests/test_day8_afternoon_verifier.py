from pathlib import Path

import fitz

from src.extraction.verify_day8_evidence import page_pdf, pages_pdf


def test_targeted_verifier_page_preserves_single_original_page(tmp_path: Path):
    path = tmp_path / "paper.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(path)
    result = fitz.open(stream=page_pdf(path, 2), filetype="pdf")
    assert result.page_count == 1


def test_verifier_can_attach_figure_and_caption_continuation_pages(tmp_path: Path):
    path = tmp_path / "paper.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.new_page()
    doc.save(path)
    result = fitz.open(stream=pages_pdf(path, [2, 3]), filetype="pdf")
    assert result.page_count == 2
