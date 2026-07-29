import json
from pathlib import Path

from src.extraction.freeze_v12_baseline import freeze, verify


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_v12_baseline_has_expected_starting_score():
    manifest = json.loads(
        (ROOT / "reports/extraction/v12_baseline/baseline_manifest.json").read_text()
    )

    assert manifest["evaluation"]["recovered"] == 10
    assert manifest["evaluation"]["total"] == 15
    assert manifest["evaluation"]["missing_gold_outcome_ids"] == [
        "GO-002",
        "GO-003",
        "GO-006",
        "GO-017",
        "GO-018",
    ]
    assert manifest["release_gates"]["critical_field_precision_minimum"] == 0.9


def test_frozen_v12_baseline_has_not_drifted():
    assert verify() == []


def test_freeze_can_write_to_an_isolated_directory(tmp_path):
    manifest = freeze(output_root=tmp_path)

    assert (tmp_path / "baseline_manifest.json").exists()
    assert len(manifest["gold_annotations"]) == 7
    assert len(manifest["selected_result_files"]) == 6
