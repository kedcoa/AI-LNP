"""Fail loudly unless every permanent v1.2 visual fixture passes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .evaluate_v12_combined_recall import match_go006
from .v12_structure_contracts import AtomicOutcomeCandidateV12


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/v12_visual/benchmark_cases.json"
DOCLING_CANDIDATES = (
    ROOT
    / "data/staging/extraction/v12_docling_candidates"
    / "GP-006-mmc1-p002-table-03/candidates.json"
)
DEFAULT_VLM_REPORT = (
    ROOT
    / "reports/extraction/v12_vlm_benchmarks"
    / "qwen3-vl-8b-instruct-thinking-off"
    / "evaluation.json"
)


def evaluate(
    fixture: dict[str, Any],
    candidates: list[AtomicOutcomeCandidateV12],
    vlm_report: dict[str, Any],
) -> dict[str, Any]:
    cases = {row["query_id"]: row for row in fixture["cases"]}
    vlm_runs: dict[str, list[dict[str, Any]]] = {}
    for row in vlm_report.get("runs", []):
        vlm_runs.setdefault(row["query_id"], []).append(row)
    checks: list[dict[str, Any]] = []
    go006 = match_go006(candidates)
    checks.append({
        "fixture": "GO-006-positive",
        "route": "docling_table_intersection",
        "passed": go006 is not None,
        "details": go006.candidate_id if go006 else "exact candidate missing",
    })
    for query_id in (
        "GO-018-positive",
        "GO-006-adversarial-abstain",
        "GO-018-adversarial-abstain",
    ):
        runs = vlm_runs.get(query_id, [])
        checks.append({
            "fixture": query_id,
            "route": "vlm_visual",
            "passed": bool(
                vlm_report.get("integration_gate_passed")
                and len(runs) >= 3
                and all(run.get("passed") for run in runs)
            ),
            "details": (
                [
                    issue
                    for run in runs
                    for issue in run.get("audit_issues", [])
                ]
                if runs
                else "benchmark result missing"
            ),
            "expected_status": cases[query_id]["expected_status"],
        })
    return {
        "contract_version": "1.0.0",
        "passed": all(row["passed"] for row in checks),
        "checks": checks,
    }


def run(vlm_report: Path = DEFAULT_VLM_REPORT) -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_text())
    candidates = [
        AtomicOutcomeCandidateV12.model_validate(row)
        for row in json.loads(DOCLING_CANDIDATES.read_text())
    ]
    benchmark = json.loads(vlm_report.read_text())
    return evaluate(fixture, candidates, benchmark)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vlm-report", type=Path, default=DEFAULT_VLM_REPORT)
    args = parser.parse_args()
    result = run(args.vlm_report)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
