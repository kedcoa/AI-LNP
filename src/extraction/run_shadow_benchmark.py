"""Run gold-blind benchmark cases through Codex CLI without production writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from src.extraction.full_paper_contracts import ContextTask
from src.extraction.full_paper_tasks import validate_context_response
from src.extraction.shadow_benchmark_contracts import (
    AttemptResult,
    AuditResponse,
    BenchmarkCase,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
ROOT = Path(__file__).resolve().parents[2]
CASE_ROOT = ROOT / "data/staging/extraction/codex_ollama_shadow"
REPORT_ROOT = ROOT / "reports/extraction/codex_ollama_shadow"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
MODEL_PREFERENCE = ("qwen3:8b", "qwen3:4b", "gemma3:12b", "gemma3:4b")


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _first_number(value: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return float(candidate)
    return None


def parse_codex_jsonl(lines: Iterable[str]) -> dict[str, Any]:
    """Extract Codex execution telemetry from its JSONL event stream.

    The CLI event format evolves independently of the final response schema, so
    this parser only consumes documented telemetry-shaped fields and leaves
    absent measurements as ``None``.
    """

    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    latency_seconds: float | None = None
    parse_issues: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            parse_issues.append(f"Malformed Codex JSONL line {line_number}: {exc.msg}")
            continue
        if not isinstance(event, dict):
            parse_issues.append(f"Codex JSONL line {line_number} is not an object")
            continue
        event_model = event.get("model")
        if isinstance(event_model, str):
            model = event_model
        usage = event.get("usage")
        if isinstance(usage, Mapping):
            reported_input = _first_number(usage, "input_tokens")
            reported_output = _first_number(usage, "output_tokens")
            reported_cached = _first_number(
                usage, "cached_input_tokens", "cache_read_input_tokens"
            )
            if reported_input is not None:
                input_tokens = int(reported_input)
            if reported_output is not None:
                output_tokens = int(reported_output)
            if reported_cached is not None:
                cached_input_tokens = int(reported_cached)
        reported_latency = _first_number(event, "latency_seconds", "duration_seconds")
        if reported_latency is None:
            reported_latency_ms = _first_number(event, "latency_ms", "duration_ms")
            if reported_latency_ms is not None:
                reported_latency = reported_latency_ms / 1_000
        if reported_latency is not None:
            latency_seconds = reported_latency
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "latency_seconds": latency_seconds,
        "parse_issues": parse_issues,
    }


def _packet_execution_root(packet_path: Path) -> Path:
    return packet_path.parent / f"{packet_path.stem}.codex_exec"


def _packet_command(
    *, schema_path: Path, last_message_path: Path, workdir: Path
) -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(last_message_path),
        "-C",
        str(workdir),
        "-",
    ]


def _validate_packet_final_message(
    final_message_path: Path, output_schema: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    if not final_message_path.exists():
        return None, ["Codex CLI did not write the requested final-message file"]
    raw_final = final_message_path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw_final)
    except json.JSONDecodeError as exc:
        return None, [f"Malformed final model output: {exc}"]
    if not isinstance(parsed, dict):
        return None, ["Final model output must be a JSON object"]
    try:
        validator = Draft202012Validator(output_schema)
    except SchemaError as exc:
        return None, [f"Invalid packet output schema: {exc.message}"]
    issues = [error.message for error in sorted(validator.iter_errors(parsed), key=str)]
    return (parsed if not issues else None), issues


def _run_codex_packet_attempt(
    packet_text: str,
    schema_text: str,
    *,
    execution_root: Path,
    attempt_number: int,
    timeout_seconds: int,
    runner: Runner,
) -> dict[str, Any]:
    attempt_dir = execution_root / f"attempt-{attempt_number:02d}"
    attempt_dir.mkdir(parents=True)
    packet_copy = attempt_dir / "packet.json"
    schema_copy = attempt_dir / "output_schema.json"
    last_message_path = attempt_dir / "last_message.json"
    raw_jsonl_path = attempt_dir / "raw.jsonl"
    stderr_path = attempt_dir / "stderr.txt"
    packet_copy.write_text(packet_text, encoding="utf-8")
    schema_copy.write_text(schema_text, encoding="utf-8")
    command = _packet_command(
        schema_path=schema_copy,
        last_message_path=last_message_path,
        workdir=attempt_dir,
    )
    started = monotonic()
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    disposition = "timeout_or_runtime_failure"
    parsed_result: dict[str, Any] | None = None
    validation_issues: list[str] = []
    try:
        completed = runner(
            command,
            input=packet_text,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = _as_text(completed.stdout)
        stderr = _as_text(completed.stderr)
        exit_code = completed.returncode
        if exit_code != 0:
            validation_issues.append(f"Codex CLI exited with status {exit_code}")
        else:
            try:
                output_schema = json.loads(schema_text)
            except json.JSONDecodeError as exc:
                output_schema = None
                validation_issues.append(f"Invalid packet output schema JSON: {exc}")
            if isinstance(output_schema, Mapping):
                parsed_result, validation_issues = _validate_packet_final_message(
                    last_message_path, output_schema
                )
                disposition = "accepted" if parsed_result is not None else "schema_failure"
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(getattr(exc, "stdout", None) or exc.output)
        stderr = _as_text(getattr(exc, "stderr", None))
        validation_issues.append(f"Codex CLI timed out after {timeout_seconds} seconds")
    except OSError as exc:
        stderr = str(exc)
        validation_issues.append(f"Codex CLI could not start: {exc}")
    raw_jsonl_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    telemetry = parse_codex_jsonl(stdout.splitlines())
    validation_issues.extend(telemetry["parse_issues"])
    if telemetry["parse_issues"] and disposition == "accepted":
        disposition = "schema_failure"
        parsed_result = None
    latency_seconds = telemetry["latency_seconds"]
    if latency_seconds is None:
        latency_seconds = monotonic() - started
    missing_usage = (
        telemetry["input_tokens"] is None or telemetry["output_tokens"] is None
    )
    return {
        "exit_code": exit_code,
        "terminal_disposition": disposition,
        "parsed_result": parsed_result,
        "validation_issues": validation_issues,
        "model": telemetry["model"],
        "input_tokens": telemetry["input_tokens"],
        "output_tokens": telemetry["output_tokens"],
        "cached_input_tokens": telemetry["cached_input_tokens"],
        "token_measurement_reason": (
            "Codex JSONL did not report usage" if missing_usage else None
        ),
        "latency_seconds": latency_seconds,
        "raw_jsonl_path": str(raw_jsonl_path),
        "stderr_path": str(stderr_path),
        "last_message_path": str(last_message_path),
    }


def run_codex_packet(
    packet_path: Path,
    output_schema: Path,
    timeout_seconds: int,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Run one sealed audit packet, retrying one runtime failure at most once."""

    packet_path = packet_path.resolve()
    output_schema = output_schema.resolve()
    if not packet_path.is_file():
        raise FileNotFoundError(packet_path)
    if not output_schema.is_file():
        raise FileNotFoundError(output_schema)
    execution_root = _packet_execution_root(packet_path)
    if execution_root.exists():
        raise FileExistsError(f"Refusing to overwrite {execution_root}")
    execution_root.mkdir()
    packet_text = packet_path.read_text(encoding="utf-8")
    schema_text = output_schema.read_text(encoding="utf-8")
    attempts: list[dict[str, Any]] = []
    for attempt_number in (1, 2):
        attempt = _run_codex_packet_attempt(
            packet_text,
            schema_text,
            execution_root=execution_root,
            attempt_number=attempt_number,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
        attempts.append(attempt)
        if attempt["terminal_disposition"] != "timeout_or_runtime_failure":
            break
    terminal = attempts[-1]
    return {
        **terminal,
        "packet_path": str(packet_path),
        "output_schema_path": str(output_schema),
        "attempt_count": len(attempts),
        "retry_count": len(attempts) - 1,
        "raw_jsonl_paths": [attempt["raw_jsonl_path"] for attempt in attempts],
        "stderr_paths": [attempt["stderr_path"] for attempt in attempts],
        "last_message_paths": [attempt["last_message_path"] for attempt in attempts],
    }


def run_codex_packets(
    packet_schemas: Sequence[tuple[Path, Path]],
    *,
    timeout_seconds: int,
    runner: Runner = subprocess.run,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Run packets until three consecutive systemic failures trip the breaker."""

    results: list[dict[str, Any]] = []
    consecutive_systemic_failures = 0
    for index, (packet_path, output_schema) in enumerate(packet_schemas):
        result = run_codex_packet(
            packet_path,
            output_schema,
            timeout_seconds,
            runner=runner,
        )
        results.append(result)
        if result["terminal_disposition"] in {
            "schema_failure",
            "timeout_or_runtime_failure",
        }:
            consecutive_systemic_failures += 1
        else:
            consecutive_systemic_failures = 0
        if consecutive_systemic_failures == 3:
            return results, [path for path, _schema in packet_schemas[index + 1 :]]
    return results, []


def _model_prompt(case: BenchmarkCase) -> str:
    payload = (
        case.payload["payload"]
        if case.route == "gate_b" and "payload" in case.payload
        else case.payload
    )
    return f"{case.prompt}\n\nCASE PAYLOAD:\n{_canonical(payload)}"


def select_installed_model(tags: dict) -> tuple[str, str]:
    installed = {
        row["name"]: str(row.get("digest") or "")
        for row in tags.get("models", [])
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    if not installed:
        raise RuntimeError("Ollama reported no installed models")
    for preferred in MODEL_PREFERENCE:
        if preferred in installed:
            return preferred, installed[preferred]
    name = sorted(installed)[0]
    return name, installed[name]


def fetch_ollama_tags(timeout_seconds: int = 30) -> dict:
    with urllib.request.urlopen(OLLAMA_TAGS, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def codex_command(
    case: BenchmarkCase,
    *,
    backend: str,
    model: str,
    schema_path: Path,
    workdir: Path,
) -> list[str]:
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema_path),
        "-C",
        str(workdir),
    ]
    if backend == "ollama":
        command.extend(["--oss", "--local-provider", "ollama", "--model", model])
    elif backend != "codex":
        raise ValueError(f"Unsupported backend: {backend}")
    command.append("-")
    return command


def _write_attempt(
    run_root: Path,
    attempt_dir: Path,
    result: AttemptResult,
) -> None:
    (attempt_dir / "attempt.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def run_case(
    case: BenchmarkCase,
    *,
    backend: str,
    model: str,
    run_root: Path,
    timeout_seconds: int,
    runner: Runner = subprocess.run,
) -> AttemptResult:
    attempt_dir = run_root / "attempts" / case.case_id
    if attempt_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {attempt_dir}")
    input_dir = attempt_dir / "input"
    input_dir.mkdir(parents=True)
    schema_path = input_dir / "output_schema.json"
    schema_path.write_text(
        json.dumps(case.output_schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (input_dir / "case.json").write_text(
        case.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    prompt = _model_prompt(case)
    command = codex_command(
        case,
        backend=backend,
        model=model,
        schema_path=schema_path,
        workdir=input_dir,
    )
    started = datetime.now(timezone.utc)
    timer = monotonic()
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    disposition = "timeout_or_runtime_failure"
    parsed_result = None
    issues: list[str] = []
    try:
        completed = runner(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = completed.returncode
        if completed.returncode != 0:
            issues.append(f"Codex CLI exited with status {completed.returncode}")
        else:
            try:
                raw = json.loads(stdout)
                if case.route == "audit":
                    response = AuditResponse.model_validate(raw)
                    parsed_result = response.model_dump(mode="json")
                    disposition = (
                        "model_abstained"
                        if response.disposition == "abstained"
                        else "accepted"
                    )
                else:
                    parsed_result = raw
                    report = validate_context_response(
                        raw, ContextTask.model_validate(case.payload)
                    )
                    if report.status != "valid":
                        disposition = "rejected_by_validation"
                        issues.extend(
                            f"{finding.code}: {finding.message}"
                            for finding in report.findings
                        )
                    else:
                        accounting = raw.get("context_candidate_accounting", {})
                        extracted = any(
                            isinstance(row, dict)
                            and row.get("disposition") == "extracted"
                            for row in accounting.values()
                        )
                        disposition = (
                            "model_abstained"
                            if not extracted
                            else "accepted"
                        )
            except (json.JSONDecodeError, ValidationError) as exc:
                disposition = "schema_failure"
                issues.append(str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else exc.stdout or ""
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else exc.stderr or ""
        )
        issues.append(f"Codex CLI timed out after {timeout_seconds} seconds")

    stdout_path = attempt_dir / "stdout.txt"
    stderr_path = attempt_dir / "stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    completed_at = datetime.now(timezone.utc)
    result = AttemptResult(
        case_id=case.case_id,
        route=case.route,
        backend=backend,
        model=model,
        source_sha256=case.source_sha256,
        prompt_sha256=_sha_text(prompt),
        started_at=started,
        completed_at=completed_at,
        duration_seconds=monotonic() - timer,
        exit_code=exit_code,
        terminal_disposition=disposition,
        input_tokens=None,
        output_tokens=None,
        token_measurement_reason="Codex CLI final output did not report usage",
        stdout_path=str(stdout_path.relative_to(run_root)),
        stderr_path=str(stderr_path.relative_to(run_root)),
        parsed_result=parsed_result,
        validation_issues=issues,
        paid_api_requests=0,
        production_writes=0,
    )
    _write_attempt(run_root, attempt_dir, result)
    return result


def run_cases(
    cases: list[BenchmarkCase],
    *,
    backend: str,
    model: str,
    run_root: Path,
    timeout_seconds: int,
    runner: Runner = subprocess.run,
) -> tuple[list[AttemptResult], list[str]]:
    attempts: list[AttemptResult] = []
    consecutive_class: str | None = None
    consecutive_count = 0
    for index, case in enumerate(cases):
        result = run_case(
            case,
            backend=backend,
            model=model,
            run_root=run_root,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
        attempts.append(result)
        if result.terminal_disposition in {
            "schema_failure",
            "timeout_or_runtime_failure",
        }:
            if result.terminal_disposition == consecutive_class:
                consecutive_count += 1
            else:
                consecutive_class = result.terminal_disposition
                consecutive_count = 1
        else:
            consecutive_class = None
            consecutive_count = 0
        if consecutive_count == 3:
            return attempts, [row.case_id for row in cases[index + 1 :]]
    return attempts, []


def _load_cases(run_id: str, route: str) -> list[BenchmarkCase]:
    path = CASE_ROOT / run_id / "case_manifest.json"
    manifest = _load_json(path)
    return [
        BenchmarkCase.model_validate(row)
        for row in manifest["cases"]
        if row["route"] == route
    ]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--route", choices=("audit", "gate-b"), required=True)
    parser.add_argument("--backend", choices=("codex", "ollama"), required=True)
    parser.add_argument("--model", default="auto-installed")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    route = args.route.replace("-", "_")
    model = args.model
    model_digest = None
    if args.backend == "ollama" and model == "auto-installed":
        model, model_digest = select_installed_model(fetch_ollama_tags())
    elif args.backend == "codex" and model == "auto-installed":
        model = "hosted-default"
    run_root = REPORT_ROOT / args.run_id / f"{route}-{args.backend}"
    if run_root.exists():
        raise FileExistsError(f"Refusing to overwrite {run_root}")
    run_root.mkdir(parents=True)
    attempts, unattempted = run_cases(
        _load_cases(args.run_id, route),
        backend=args.backend,
        model=model,
        run_root=run_root,
        timeout_seconds=args.timeout_seconds,
    )
    manifest = {
        "run_id": args.run_id,
        "route": route,
        "backend": args.backend,
        "model": model,
        "model_digest": model_digest,
        "attempt_count": len(attempts),
        "unattempted_case_ids": unattempted,
        "terminal_dispositions": {
            disposition: sum(
                row.terminal_disposition == disposition for row in attempts
            )
            for disposition in sorted(
                {row.terminal_disposition for row in attempts}
            )
        },
        "paid_api_requests": 0,
        "production_writes": sum(row.production_writes for row in attempts),
    }
    (run_root / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
