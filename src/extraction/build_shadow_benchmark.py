"""Build immutable, gold-blind cases for the Codex/Ollama shadow benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.extraction.full_paper_contracts import ContextTask
from src.extraction.shadow_benchmark_contracts import (
    AuditResponse,
    BenchmarkCase,
)


ROOT = Path(__file__).resolve().parents[2]
PAPERS = ("PILOT-001", "PILOT-002", "PILOT-003")
PILOT_REPORT = ROOT / "reports/extraction/application_pilot_final.json"
GATE_B_FIXTURE_ROOT = (
    ROOT / "tests/fixtures/codex_ollama_shadow/application_pilot_gate_b"
)
OUTPUT_ROOT = ROOT / "data/staging/extraction/codex_ollama_shadow"

AUDIT_PROMPT = """You are a read-only scientific audit agent. Review only the supplied
paper artifacts. Identify likely omissions, unsupported relationships, wrong-arm
associations, incomplete application-critical fields, and COMET-readiness gaps.
Use only experiment, candidate, record, and evidence IDs present in the payload.
Inventory every supported application-relevant fact as an observation with its
field name, raw value, experiment scope, and evidence IDs. Also report audit
findings. Do not rewrite records, estimate missing numbers, or claim evidence that
is not supplied. Return only JSON matching the provided schema."""


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


def build_audit_cases(root: Path = ROOT) -> list[BenchmarkCase]:
    report_path = root / PILOT_REPORT.relative_to(ROOT)
    report = _load(report_path)
    extraction_by_paper = {
        row["paper_id"]: row for row in report["extraction"]["papers"]
    }
    cases = []
    for paper_id in PAPERS:
        paths = [report_path]
        payload = {
            "paper_id": paper_id,
            "merged_extraction": extraction_by_paper[paper_id],
            "validation": [
                row for row in report["validation"] if row["paper_id"] == paper_id
            ],
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
    fixture_root = root / GATE_B_FIXTURE_ROOT.relative_to(ROOT)
    paths = sorted(
        fixture_root.glob("REQ-*.json"),
        key=lambda path: int(path.stem.split("-")[1]),
    )
    for path in paths:
        request = _load(path)
        messages = request["input"]
        prompt = messages[0]["content"]
        task_payload = json.loads(messages[1]["content"])
        paper_id = task_payload["paper_id"]
        response_schema = request["text"]["format"]["schema"]
        task = ContextTask(
            context_task_version="full-paper-context-task-1.2.0",
            task_id=path.stem,
            paper_id=paper_id,
            context_key=task_payload["context_key"],
            token_budget=100_000,
            estimated_input_tokens=0,
            shared_formulations=task_payload["shared_formulations"],
            shared_payloads=task_payload["shared_payloads"],
            candidates=task_payload["candidates"],
            evidence=task_payload["evidence"],
            candidate_evidence_envelopes=task_payload[
                "candidate_evidence_envelopes"
            ],
            payload=task_payload,
            response_schema=response_schema,
        )
        relative = _relative(root, path)
        cases.append(
            BenchmarkCase(
                case_id=f"gate-b-{paper_id}-{path.stem.lower()}",
                route="gate_b",
                paper_id=paper_id,
                source_paths=[relative],
                source_sha256=_sha_path(path),
                prompt=prompt,
                payload=task.model_dump(mode="json"),
                output_schema=response_schema,
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
