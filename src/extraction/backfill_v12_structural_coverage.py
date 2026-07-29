"""Backfill deterministic structural coverage for completed v1.2 runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.extraction.v12_main_route import (
    evaluate_v12_structural_result_coverage,
)


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "data/staging/extraction/compact_one_call_v1_2"
REPORT_PATH = (
    ROOT
    / "reports/extraction/v12_structural_coverage_backfill/summary.json"
)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def backfill_run(run_dir: Path) -> dict[str, Any]:
    request_path = run_dir / "request.json"
    result_path = run_dir / "result.json"
    if not request_path.exists() or not result_path.exists():
        raise FileNotFoundError(
            f"{run_dir} requires both request.json and result.json"
        )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    support = request["request_payload"]["outcome_recall_support"]
    report = evaluate_v12_structural_result_coverage(support, result)
    output_path = run_dir / "v12_structural_coverage.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "paper_id": report["paper_id"],
        "run_dir": _display_path(run_dir),
        "output_path": _display_path(output_path),
        "status": report["status"],
        "counts": report["counts"],
        "routes": report["routes"],
        "integration_blocked": report["integration_blocked"],
    }


def run(
    *,
    paper_ids: list[str] | None = None,
    run_root: Path = RUN_ROOT,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    selected = set(paper_ids or [])
    rows = [
        backfill_run(run_dir)
        for run_dir in sorted(path for path in run_root.glob("GP-*") if path.is_dir())
        if not selected or run_dir.name in selected
    ]
    summary = {
        "backfill_version": "v12-structural-coverage-backfill-1.0.0",
        "scope": "stored requests and results only",
        "runs": rows,
        "paid_api_requests": 0,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                paper_ids=args.paper_id,
                run_root=args.run_root,
                report_path=args.report_path,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
