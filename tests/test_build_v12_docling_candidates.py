from src.extraction.build_v12_docling_candidates import build_for_object
from src.extraction.v12_visual_contracts import DoclingVisualObjectV12


def test_table_intersection_becomes_atomic_candidate(monkeypatch):
    parsed = DoclingVisualObjectV12.model_validate({
        "object_id": "O1",
        "paper_id": "GP-X",
        "source_file": "supp.pdf",
        "original_page": 2,
        "figure_or_table": "Table S2",
        "inventory_object_type": "table",
        "caption": "Cas9/sgRNA LNP insertion frequency",
        "source_crop": "crop.png",
        "source_crop_sha256": "abc",
        "parser_version": "test",
        "parser_config": {},
        "parse_seconds": 0.1,
        "parse_status": "parsed",
        "text_items": [],
        "tables": [{
            "table_index": 0,
            "rows": 2,
            "columns": 2,
            "grid": [
                ["", "total insertion frequency"],
                ["LSEC", "1.01 ± 0.38 %"],
            ],
            "cells": [
                {
                    "row": 0, "column": 1, "row_span": 1, "column_span": 1,
                    "text": "total insertion frequency",
                    "is_row_header": False, "is_column_header": True,
                },
                {
                    "row": 1, "column": 0, "row_span": 1, "column_span": 1,
                    "text": "LSEC",
                    "is_row_header": True, "is_column_header": False,
                },
                {
                    "row": 1, "column": 1, "row_span": 1, "column_span": 1,
                    "text": "1.01 ± 0.38 %",
                    "is_row_header": False, "is_column_header": False,
                },
            ],
        }],
        "picture_count": 0,
        "warnings": [],
    })
    monkeypatch.setattr(
        "src.extraction.build_v12_docling_candidates._experiment",
        lambda _: ("PEX-GP-X-test", ["cas9/sgrna"]),
    )
    claims, candidates = build_for_object(parsed)
    assert len(claims) == len(candidates) == 1
    candidate = candidates[0]
    assert candidate.subject_text == "LSEC"
    assert candidate.endpoint_text == "total insertion frequency"
    assert candidate.numeric_value == 1.01
    assert candidate.value_text == "1.01 ± 0.38 %"
    assert candidate.route_hint == "vision"
