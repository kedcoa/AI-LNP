from PIL import Image

import src.extraction.build_v12_visual_focus as focus
from src.extraction.build_v12_visual_focus import compute_focus_bbox
from src.extraction.v12_visual_contracts import DoclingVisualObjectV12


def test_focus_bbox_converts_bottom_left_coordinates():
    parsed = DoclingVisualObjectV12.model_validate({
        "object_id": "O1",
        "paper_id": "GP-X",
        "source_file": "supp.pdf",
        "original_page": 4,
        "figure_or_table": "Figure S1",
        "inventory_object_type": "figure",
        "caption": "ZsGreen and Desmin",
        "source_crop": "crop.png",
        "source_crop_sha256": "abc",
        "parser_version": "test",
        "parser_config": {},
        "parse_seconds": 0.1,
        "parse_status": "parsed",
        "text_items": [
            {
                "label": "text",
                "text": "K",
                "page_in_crop": 1,
                "bbox": {
                    "left": 100, "top": 800, "right": 120, "bottom": 780,
                    "coord_origin": "BOTTOMLEFT",
                },
            },
            {
                "label": "text",
                "text": "DAPI/ZsGreen/Desmin",
                "page_in_crop": 1,
                "bbox": {
                    "left": 200, "top": 600, "right": 400, "bottom": 560,
                    "coord_origin": "BOTTOMLEFT",
                },
            },
        ],
        "tables": [],
        "picture_count": 1,
        "warnings": [],
    })
    assert compute_focus_bbox(
        parsed,
        "ZsGreen localization in Desmin-positive HSCs",
        {"K"},
        width=1000,
        height=1000,
        padding=10,
    ) == (90, 190, 410, 450)


def test_stack_regions_preserves_pixels_without_rescaling(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "ROOT", tmp_path)
    source = tmp_path / "source.png"
    image = Image.new("RGB", (20, 20), "white")
    for x in range(0, 10):
        for y in range(0, 5):
            image.putpixel((x, y), (255, 0, 0))
    for x in range(10, 20):
        for y in range(10, 20):
            image.putpixel((x, y), (0, 255, 0))
    image.save(source)
    metadata = focus.stack_regions(
        source.relative_to(tmp_path),
        tmp_path.joinpath("stacked.png").relative_to(tmp_path),
        [(0, 0, 10, 5), (10, 10, 20, 20)],
    )
    with Image.open(tmp_path / "stacked.png") as stacked:
        assert stacked.size == (10, 15)
        assert stacked.getpixel((1, 1)) == (255, 0, 0)
        assert stacked.getpixel((1, 6)) == (0, 255, 0)
    assert metadata["selection_method"].endswith("without_rescaling")
