from pathlib import Path

import fitz
from src.extraction.pdf_multimodal_contracts import VisualEvidenceRecord
from src.extraction.run_day8_pdf import inventory_pdf


def test_inventory_tracks_geometry_text_and_images(tmp_path: Path):
    path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((20, 40), "Figure 1. Hepatocyte expression")
    doc.save(path)
    row = inventory_pdf(path, "GP-X")
    assert row["page_count"] == 1
    assert row["has_selectable_text"] is True
    assert row["pages"][0]["width"] == 300
    assert row["pages"][0]["figure_table_references"] == ["Figure 1."]


def test_visual_estimate_remains_parseable_for_human_review():
    payload = {
        "record_id": "R1", "paper_id": "GP-X", "experiment_id": "E1",
        "population": "hepatocytes", "intervention": "LNP-A",
        "endpoint": "expression", "value": "about 60", "unit": "%",
        "location": {
            "file_name": "paper.pdf", "page": 2, "figure_or_table": "Figure 2",
            "panel_or_cell": "A", "evidence_source_type": "figure",
            "evidence_quote": "Figure 2A",
        },
        "measurement_status": "visually_estimated", "confidence": "medium",
        "ambiguity": None,
    }
    row = VisualEvidenceRecord.model_validate(payload)
    assert row.measurement_status == "visually_estimated"
    assert row.ambiguity is None
