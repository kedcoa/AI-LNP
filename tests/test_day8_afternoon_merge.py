from src.extraction.merge_day8_evidence import audit_source, key
from src.extraction.pdf_multimodal_contracts import MergedEvidenceSource


def source(**changes):
    values = {
        "source_id": "s1", "source_kind": "object_vision", "file_name": "x.pdf",
        "page": 2, "figure_or_table": "Figure 1", "panel_or_cell": "B",
        "evidence_quote": "Q2 9.92", "value": "9.92", "unit": "%",
        "measurement_status": "exact_reported", "confidence": "high",
        "crop_path": "crop.png",
    }
    values.update(changes)
    return MergedEvidenceSource.model_validate(values)


def test_merge_key_is_case_and_punctuation_stable():
    assert key("GP-8", "Macrophages", "LNP/ZsGreen", "Q2 (%)") == key(
        "gp-8", "macrophages", "LNP/ZsGreen", "Q2 %"
    )


def test_visual_estimate_requires_human_verification():
    assert "derived_value_requires_human_verification" in audit_source(
        source(measurement_status="visually_estimated")
    )


def test_object_record_requires_figure_identity():
    assert "missing_figure_or_table" in audit_source(source(figure_or_table=None))
