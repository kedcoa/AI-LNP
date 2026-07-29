"""Freeze the pre-v1.2 extraction benchmark without making API calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GOLD_ROOT = ROOT / "data/annotations/gold_v1"
EVALUATION_PATH = ROOT / "reports/extraction/final_gold_dynamic_v1/evaluation.json"
OUTPUT_ROOT = ROOT / "reports/extraction/v12_baseline"
RESULT_ROOTS = [
    ROOT / "data/staging/extraction/consolidated_gold_gap_merged_v1",
    ROOT / "data/staging/extraction/compact_merged_v1_1",
    ROOT / "data/staging/extraction/compact_merged_v1",
    ROOT / "data/staging/extraction/compact_one_call_v1",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _result_path(paper_id: str) -> Path | None:
    for root in RESULT_ROOTS:
        for name in ("final_result.json", "result.json"):
            path = root / paper_id / name
            if path.exists():
                return path
    return None


def freeze(*, output_root: Path = OUTPUT_ROOT) -> dict:
    evaluation = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))
    paper_ids = sorted({row["paper_id"] for row in evaluation["results"]})
    gold_files = sorted(GOLD_ROOT.glob("*.csv"))
    result_files = [
        path
        for paper_id in paper_ids
        if (path := _result_path(paper_id)) is not None
    ]
    manifest = {
        "baseline_version": "v12-preimplementation-1.0.0",
        "frozen_on": date.today().isoformat(),
        "purpose": (
            "Immutable pre-v1.2 comparison inputs. Gold IDs and answers remain "
            "evaluation-only and must not enter extraction prompts or builders."
        ),
        "evaluation": {
            "path": _relative(EVALUATION_PATH),
            "sha256": _sha256(EVALUATION_PATH),
            "recovered": evaluation["recovered"],
            "total": evaluation["total"],
            "rate": evaluation["rate"],
            "missing_gold_outcome_ids": evaluation["missing_gold_outcome_ids"],
        },
        "gold_annotations": [
            {"path": _relative(path), "sha256": _sha256(path)}
            for path in gold_files
        ],
        "selected_result_files": [
            {"path": _relative(path), "sha256": _sha256(path)}
            for path in result_files
        ],
        "release_gates": {
            "previously_recovered_outcomes_retained": "10/10",
            "development_outcome_recall_target": "15/15",
            "critical_field_precision_minimum": 0.90,
            "unsupported_accepted_outcomes": 0,
            "wrong_experiment_links": 0,
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "baseline_manifest.json"
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify(*, manifest_path: Path = OUTPUT_ROOT / "baseline_manifest.json") -> list[str]:
    """Return drift errors without rewriting the frozen baseline."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    tracked = [
        manifest["evaluation"],
        *manifest["gold_annotations"],
        *manifest["selected_result_files"],
    ]
    for item in tracked:
        path = ROOT / item["path"]
        if not path.exists():
            errors.append(f"missing: {item['path']}")
        elif _sha256(path) != item["sha256"]:
            errors.append(f"sha256 drift: {item['path']}")

    evaluation = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))
    for field in ("recovered", "total", "rate", "missing_gold_outcome_ids"):
        if evaluation[field] != manifest["evaluation"][field]:
            errors.append(f"evaluation drift: {field}")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the frozen files without rewriting the manifest",
    )
    args = parser.parse_args()
    if args.check:
        drift = verify()
        if drift:
            print(json.dumps({"ok": False, "errors": drift}, indent=2))
            raise SystemExit(1)
        print(json.dumps({"ok": True, "errors": []}, indent=2))
    else:
        print(json.dumps(freeze(), ensure_ascii=False, indent=2))
