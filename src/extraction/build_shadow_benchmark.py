"""Build immutable, gold-blind cases for the Codex/Ollama shadow benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.extraction.missing_record_contracts import (
    MissingRecordFragment,
    MissingRecordTask,
)
from src.extraction.run_missing_record_repair import PROMPT as GATE_B_PROMPT
from src.extraction.shadow_benchmark_contracts import (
    AuditResponse,
    BenchmarkCase,
)


ROOT = Path(__file__).resolve().parents[2]
PAPERS = ("GP-004", "GP-006", "GP-008")
STRUCTURAL_ROOT = ROOT / "data/staging/extraction/v12_structural_primary_v6"
ACCEPTED_ROOT = ROOT / "data/staging/extraction/g1_fulltext_rag"
TASK_AUDIT = ROOT / "reports/extraction/v12_structural_primary_v6/task_audit.json"
OUTPUT_ROOT = ROOT / "data/staging/extraction/codex_ollama_shadow"

AUDIT_PROMPT = """You are a read-only scientific audit agent. Review only the supplied
paper artifacts. Identify likely omissions, unsupported relationships, wrong-arm
associations, incomplete application-critical fields, and COMET-readiness gaps.
Use only record and evidence IDs present in the payload. Do not rewrite records,
estimate missing numbers, or claim evidence that is not supplied. Return only JSON
matching the provided schema."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_path(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def _combined_source_sha(root: Path, paths: list[Path]) -> str:
    rows = [
        {"path": _relative(root, path), "sha256": _sha_path(path)}
        for path in paths
    ]
    return _sha_bytes(_canonical(rows).encode("utf-8"))


def _task_audit_by_paper(root: Path) -> dict[str, dict[str, Any]]:
    report = _load(root / TASK_AUDIT.relative_to(ROOT))
    return {row["paper_id"]: row for row in report["papers"]}


def build_audit_cases(root: Path = ROOT) -> list[BenchmarkCase]:
    audit_rows = _task_audit_by_paper(root)
    cases = []
    for paper_id in PAPERS:
        accepted = root / ACCEPTED_ROOT.relative_to(ROOT) / paper_id / "accepted_graph.json"
        coverage = (
            root
            / STRUCTURAL_ROOT.relative_to(ROOT)
            / paper_id
            / "v12_structural_coverage.json"
        )
        paths = [accepted, coverage, root / TASK_AUDIT.relative_to(ROOT)]
        payload = {
            "paper_id": paper_id,
            "accepted_graph": _load(accepted),
            "structural_coverage": _load(coverage),
            "task_audit": audit_rows[paper_id],
        }
        cases.append(
            BenchmarkCase(
                case_id=f"audit-{paper_id}",
                route="audit",
                paper_id=paper_id,
                source_paths=[_relative(root, path) for path in paths],
                source_sha256=_combined_source_sha(root, paths),
                prompt=AUDIT_PROMPT,
                payload=payload,
                output_schema=AuditResponse.model_json_schema(),
            )
        )
    return cases


def build_gate_b_cases(root: Path = ROOT) -> list[BenchmarkCase]:
    cases = []
    structural_root = root / STRUCTURAL_ROOT.relative_to(ROOT)
    for path in sorted(structural_root.glob("GP-*/structural_repair_tasks/task_*.json")):
        task = MissingRecordTask.model_validate_json(path.read_text(encoding="utf-8"))
        if task.paper_id not in PAPERS:
            continue
        relative = _relative(root, path)
        cases.append(
            BenchmarkCase(
                case_id=(
                    f"gate-b-{task.paper_id}-{path.stem.replace('_', '-')}"
                ),
                route="gate_b",
                paper_id=task.paper_id,
                source_paths=[relative],
                source_sha256=_sha_path(path),
                prompt=GATE_B_PROMPT,
                payload=task.model_dump(mode="json"),
                output_schema=MissingRecordFragment.model_json_schema(),
            )
        )
    return cases


def build_all_cases(root: Path = ROOT) -> list[BenchmarkCase]:
    cases = [*build_audit_cases(root), *build_gate_b_cases(root)]
    ids = [row.case_id for row in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Benchmark case IDs must be unique")
    return cases


def write_case_manifest(
    cases: list[BenchmarkCase], destination: Path
) -> Path:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    route_counts = Counter(row.route for row in cases)
    payload = {
        "benchmark_version": "codex-ollama-shadow-1.0.0",
        "case_count": len(cases),
        "route_counts": dict(sorted(route_counts.items())),
        "paid_api_requests": 0,
        "cases": [row.model_dump(mode="json") for row in cases],
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    destination = (
        args.root
        / OUTPUT_ROOT.relative_to(ROOT)
        / args.run_id
        / "case_manifest.json"
    )
    path = write_case_manifest(build_all_cases(args.root), destination)
    print(path)


if __name__ == "__main__":
    main()
