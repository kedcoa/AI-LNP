from pathlib import Path

from src.extraction.build_consolidated_gold_gap_tasks import OUTPUT_ROOT
from src.extraction.run_consolidated_gap_recovery import load_task


def test_exactly_one_signed_task_per_affected_paper():
    tasks = [
        load_task(OUTPUT_ROOT / paper_id / "task.json")
        for paper_id in ("GP-004", "GP-006", "GP-008")
    ]
    assert [task.paper_id for task in tasks] == ["GP-004", "GP-006", "GP-008"]
    assert all(task.permitted_new_outcomes == 2 for task in tasks)


def test_visual_assets_exist_and_are_checksum_validated():
    for paper_id in ("GP-004", "GP-006", "GP-008"):
        task = load_task(OUTPUT_ROOT / paper_id / "task.json")
        assert task.visual_assets
        assert all(Path(asset.image_path).is_file() for asset in task.visual_assets)


def test_tasks_do_not_embed_frozen_gold_identifiers():
    for paper_id in ("GP-004", "GP-006", "GP-008"):
        text = (OUTPUT_ROOT / paper_id / "task.json").read_text(encoding="utf-8")
        assert "GO-" not in text
        assert "EVID-" not in text
