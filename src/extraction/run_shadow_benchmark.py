"""Run gold-blind benchmark cases through Codex CLI without production writes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Callable

from pydantic import ValidationError

from src.extraction.missing_record_contracts import (
    MissingRecordFragment,
    MissingRecordTask,
)
from src.extraction.run_missing_record_repair import validate_response
from src.extraction.shadow_benchmark_contracts import (
    AttemptResult,
    AuditResponse,
    BenchmarkCase,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _model_prompt(case: BenchmarkCase) -> str:
    return f"{case.prompt}\n\nCASE PAYLOAD:\n{_canonical(case.payload)}"


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
                    response = MissingRecordFragment.model_validate(raw)
                    parsed_result = response.model_dump(mode="json")
                    try:
                        validate_response(
                            response, MissingRecordTask.model_validate(case.payload)
                        )
                    except ValueError as exc:
                        disposition = "rejected_by_validation"
                        issues.append(str(exc))
                    else:
                        disposition = (
                            "model_abstained"
                            if response.disposition == "unresolved"
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
