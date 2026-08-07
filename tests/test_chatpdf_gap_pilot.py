from __future__ import annotations

from pypdf import PdfWriter

from src.extraction.run_chatpdf_gap_pilot import build_prompt, build_preflight


def test_gp002_preflight_allows_one_pdf_and_one_message(tmp_path) -> None:
    pdf = tmp_path / "gp002.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as handle:
        writer.write(handle)

    preflight = build_preflight("GP-002", pdf)

    assert preflight["pdf_pages"] == 1
    assert preflight["upload_requests"] == 1
    assert preflight["message_requests"] == 1
    assert preflight["maximum_message_requests"] == 1


def test_prompt_requires_shared_protocol_scope_and_separate_target_semantics() -> None:
    prompt = build_prompt("GP-002")

    assert "shared protocol" in prompt
    assert "target_or_recipient_organ" in prompt
    assert "intended_target_cell" in prompt
    assert "observed_transfected_cell" in prompt
    assert "JSON object only" in prompt
