import json

from src.extraction.backfill_v12_structural_coverage import run
from tests.test_deterministic_coverage_v12 import (
    candidate,
    experiment,
    outcome,
    provisional,
)


def test_backfill_uses_stored_artifacts_without_api_calls(tmp_path):
    run_root = tmp_path / "runs"
    paper_root = run_root / "GP-X"
    paper_root.mkdir(parents=True)
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [candidate().model_dump(mode="json")],
        "provisional_experiments": [provisional()],
    }
    (paper_root / "request.json").write_text(
        json.dumps(
            {
                "request_payload": {
                    "outcome_recall_support": support,
                }
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "result.json").write_text(
        json.dumps(
            {
                "experiments": [experiment()],
                "outcomes": [outcome()],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "summary.json"
    summary = run(run_root=run_root, report_path=report_path)
    assert summary["paid_api_requests"] == 0
    assert summary["runs"][0]["status"] == "complete"
    assert (paper_root / "v12_structural_coverage.json").exists()
    assert report_path.exists()
