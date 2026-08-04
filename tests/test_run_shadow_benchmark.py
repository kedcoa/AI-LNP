import json
import subprocess
from pathlib import Path

import pytest

from src.extraction.build_shadow_benchmark import (
    build_audit_cases,
    build_gate_b_cases,
)
from src.extraction.run_shadow_benchmark import (
    codex_command,
    run_case,
    run_cases,
    select_installed_model,
)


ROOT = Path(__file__).resolve().parents[1]


def _completed(stdout: str, returncode: int = 0):
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], returncode, stdout, "")

    return runner


def _valid_audit_json() -> str:
    return (
        ROOT / "tests/fixtures/codex_ollama_shadow/fake_audit_response.json"
    ).read_text(encoding="utf-8")


def test_ollama_command_is_ephemeral_read_only_and_local(tmp_path):
    case = build_gate_b_cases(ROOT)[0]
    schema = tmp_path / "schema.json"
    command = codex_command(
        case,
        backend="ollama",
        model="qwen3:8b",
        schema_path=schema,
        workdir=tmp_path,
    )

    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--oss") : command.index("--oss") + 4] == [
        "--oss",
        "--local-provider",
        "ollama",
        "--model",
    ]
    assert command[command.index("--sandbox") : command.index("--sandbox") + 2] == [
        "--sandbox",
        "read-only",
    ]
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert command[-1] == "-"


def test_legacy_runner_rejects_audit_cases(tmp_path):
    case = build_audit_cases(ROOT)[0]

    with pytest.raises(ValueError, match="sealed audit packets"):
        run_case(
            case,
            backend="codex",
            model="hosted-default",
            run_root=tmp_path,
            timeout_seconds=30,
            runner=_completed(_valid_audit_json()),
        )


def test_malformed_output_is_a_schema_failure(tmp_path):
    case = build_gate_b_cases(ROOT)[0]

    result = run_case(
        case,
        backend="codex",
        model="hosted-default",
        run_root=tmp_path,
        timeout_seconds=30,
        runner=_completed("not-json"),
    )

    assert result.terminal_disposition == "schema_failure"
    assert result.parsed_result is None
    assert result.validation_issues


def test_schema_json_that_violates_gate_b_rules_is_rejected_by_validation(tmp_path):
    case = build_gate_b_cases(ROOT)[0]

    result = run_case(
        case,
        backend="ollama",
        model="qwen3:8b",
        run_root=tmp_path,
        timeout_seconds=30,
        runner=_completed("{}"),
    )

    assert result.terminal_disposition == "rejected_by_validation"
    assert any("candidate" in issue.lower() for issue in result.validation_issues)


def test_nonzero_exit_is_a_runtime_failure(tmp_path):
    case = build_gate_b_cases(ROOT)[0]

    result = run_case(
        case,
        backend="codex",
        model="hosted-default",
        run_root=tmp_path,
        timeout_seconds=30,
        runner=_completed("", returncode=1),
    )

    assert result.terminal_disposition == "timeout_or_runtime_failure"
    assert result.exit_code == 1


def test_timeout_is_a_runtime_failure(tmp_path):
    case = build_gate_b_cases(ROOT)[0]

    def timeout_runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    result = run_case(
        case,
        backend="codex",
        model="hosted-default",
        run_root=tmp_path,
        timeout_seconds=30,
        runner=timeout_runner,
    )

    assert result.terminal_disposition == "timeout_or_runtime_failure"
    assert result.exit_code is None


def test_case_output_is_append_only(tmp_path):
    case = build_gate_b_cases(ROOT)[0]
    kwargs = {
        "backend": "codex",
        "model": "hosted-default",
        "run_root": tmp_path,
        "timeout_seconds": 30,
        "runner": _completed(_valid_audit_json()),
    }
    run_case(case, **kwargs)

    with pytest.raises(FileExistsError):
        run_case(case, **kwargs)


def test_three_consecutive_schema_failures_stop_remaining_cases(tmp_path):
    cases = build_gate_b_cases(ROOT)[:5]

    attempts, unattempted = run_cases(
        cases,
        backend="codex",
        model="hosted-default",
        run_root=tmp_path,
        timeout_seconds=30,
        runner=_completed("not-json"),
    )

    assert len(attempts) == 3
    assert [row.terminal_disposition for row in attempts] == [
        "schema_failure",
        "schema_failure",
        "schema_failure",
    ]
    assert unattempted == [row.case_id for row in cases[3:]]


def test_installed_model_selection_uses_fixed_preference_order():
    tags = {
        "models": [
            {"name": "zeta:latest", "digest": "z" * 64},
            {"name": "gemma3:4b", "digest": "g" * 64},
            {"name": "qwen3:8b", "digest": "q" * 64},
        ]
    }

    assert select_installed_model(tags) == ("qwen3:8b", "q" * 64)


def test_installed_model_selection_fails_when_ollama_has_no_models():
    with pytest.raises(RuntimeError, match="no installed models"):
        select_installed_model({"models": []})
