from src.extraction.run_v12_docling_visual import normalize_docling


def test_normalize_docling_preserves_table_intersection(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    crop.write_bytes(b"png")
    from src.extraction import run_v12_docling_visual as module
    monkeypatch.setattr(module, "ROOT", tmp_path)
    row = {
        "object_id": "O1",
        "paper_id": "GP-X",
        "source_file": "source.pdf",
        "page": 2,
        "label": "Table S2.",
        "object_type": "table",
        "caption": "Insertion frequency",
        "crop_path": "crop.png",
    }
    exported = {
        "texts": [],
        "pictures": [],
        "tables": [{"data": {"table_cells": [
            {
                "start_row_offset_idx": 0, "end_row_offset_idx": 1,
                "start_col_offset_idx": 1, "end_col_offset_idx": 2,
                "text": "total insertion frequency", "column_header": True,
            },
            {
                "start_row_offset_idx": 1, "end_row_offset_idx": 2,
                "start_col_offset_idx": 0, "end_col_offset_idx": 1,
                "text": "LSEC", "row_header": True,
            },
            {
                "start_row_offset_idx": 1, "end_row_offset_idx": 2,
                "start_col_offset_idx": 1, "end_col_offset_idx": 2,
                "text": "1.01 ± 0.38 %",
            },
        ]}}],
    }
    result = normalize_docling(
        row, exported, parser_version="test", parse_seconds=0.1
    )
    assert result.original_page == 2
    assert result.tables[0].grid == [
        ["", "total insertion frequency"],
        ["LSEC", "1.01 ± 0.38 %"],
    ]
