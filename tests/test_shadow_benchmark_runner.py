import json
import subprocess
from pathlib import Path

from src.extraction.run_shadow_benchmark import (
    parse_codex_jsonl,
    run_codex_packet,
    run_codex_packets,
)


FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures/codex_ollama_shadow/codex_jsonl"
)


def _fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def _packet_and_schema(tmp_path: Path, name: str = "packet") -> tuple[Path, Path]:
    packet = tmp_path / f"{name}.json"
    packet.write_text(json.dumps({"packet_id": name}) + "\n", encoding="utf-8")
    schema = tmp_path / f"{name}.schema.json"
    schema.write_text(_fixture("audit_packet_output_schema.json"), encoding="utf-8")
    return packet, schema


def _completed_with_final(jsonl: str, final: str, returncode: int = 0):
    def runner(command, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(final, encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode, jsonl, "test stderr")

    return runner


def test_parse_codex_jsonl_extracts_reported_usage_model_and_latency():
    telemetry = parse_codex_jsonl(_fixture("success.jsonl").splitlines())

    assert telemetry == {
        "model": "gpt-5-codex",
        "input_tokens": 120,
        "output_tokens": 30,
        "cached_input_tokens": 40,
        "latency_seconds": 2.5,
        "parse_issues": [],
    }


def test_run_codex_packet_uses_packet_schema_and_persists_raw_jsonl(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)
    commands: list[list[str]] = []

    def runner(command, **kwargs):
        commands.append(command)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(_fixture("valid_final.json"), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, _fixture("success.jsonl"), "test stderr")

    result = run_codex_packet(packet, schema, 30, runner=runner)

    assert result["terminal_disposition"] == "accepted"
    assert result["parsed_result"]["disposition"] == "abstained"
    assert result["model"] == "gpt-5-codex"
    assert result["input_tokens"] == 120
    assert result["output_tokens"] == 30
    assert result["cached_input_tokens"] == 40
    assert result["latency_seconds"] == 2.5
    assert result["attempt_count"] == 1
    assert result["retry_count"] == 0
    assert Path(result["raw_jsonl_paths"][0]).read_text(encoding="utf-8") == _fixture(
        "success.jsonl"
    )
    command = commands[0]
    assert command[:3] == ["codex", "exec", "--json"]
    assert command[command.index("--sandbox") : command.index("--sandbox") + 2] == [
        "--sandbox",
        "read-only",
    ]
    assert Path(command[command.index("-C") + 1]).name == "attempt-01"
    persisted_schema = Path(command[command.index("--output-schema") + 1])
    assert persisted_schema.read_text(encoding="utf-8") == schema.read_text(encoding="utf-8")


def test_run_codex_packet_rejects_final_output_that_violates_packet_schema(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)

    result = run_codex_packet(
        packet,
        schema,
        30,
        runner=_completed_with_final(
            _fixture("success.jsonl"), _fixture("malformed_final.json")
        ),
    )

    assert result["terminal_disposition"] == "schema_failure"
    assert result["parsed_result"] is None
    assert any("unresolved_reason" in issue for issue in result["validation_issues"])


def test_run_codex_packet_retries_timeout_once_and_records_each_raw_stream(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)
    calls = 0

    def timeout_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=_fixture("success.jsonl"))

    result = run_codex_packet(packet, schema, 30, runner=timeout_runner)

    assert calls == 2
    assert result["terminal_disposition"] == "timeout_or_runtime_failure"
    assert result["attempt_count"] == 2
    assert result["retry_count"] == 1
    assert len(result["raw_jsonl_paths"]) == 2
    assert all(Path(path).read_text(encoding="utf-8") == _fixture("success.jsonl") for path in result["raw_jsonl_paths"])


def test_run_codex_packet_retries_nonzero_exit_once(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)
    calls = 0

    def nonzero_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 17, _fixture("success.jsonl"), "failed")

    result = run_codex_packet(packet, schema, 30, runner=nonzero_runner)

    assert calls == 2
    assert result["terminal_disposition"] == "timeout_or_runtime_failure"
    assert result["exit_code"] == 17
    assert result["attempt_count"] == 2
    assert result["retry_count"] == 1


def test_run_codex_packet_retries_cli_launch_failure_and_persists_error(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)
    calls = 0

    def unavailable_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        raise FileNotFoundError("codex executable unavailable")

    result = run_codex_packet(packet, schema, 30, runner=unavailable_runner)

    assert calls == 2
    assert result["terminal_disposition"] == "timeout_or_runtime_failure"
    assert result["attempt_count"] == 2
    assert result["retry_count"] == 1
    assert all(Path(path).read_text(encoding="utf-8") == "" for path in result["raw_jsonl_paths"])
    assert "executable unavailable" in Path(result["stderr_paths"][-1]).read_text(
        encoding="utf-8"
    )


def test_run_codex_packet_leaves_usage_unmeasured_when_jsonl_omits_it(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)

    result = run_codex_packet(
        packet,
        schema,
        30,
        runner=_completed_with_final(
            _fixture("missing_usage.jsonl"), _fixture("valid_final.json")
        ),
    )

    assert result["terminal_disposition"] == "accepted"
    assert result["input_tokens"] is None
    assert result["output_tokens"] is None
    assert result["cached_input_tokens"] is None
    assert result["token_measurement_reason"] == "Codex JSONL did not report usage"


def test_run_codex_packets_stops_after_three_consecutive_systemic_failures(tmp_path):
    packets_and_schemas = [
        _packet_and_schema(tmp_path, f"packet-{number}") for number in range(4)
    ]
    calls = 0

    def failing_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, _fixture("success.jsonl"), "failed")

    results, unattempted = run_codex_packets(
        packets_and_schemas,
        timeout_seconds=30,
        runner=failing_runner,
    )

    assert calls == 6
    assert len(results) == 3
    assert [result["terminal_disposition"] for result in results] == [
        "timeout_or_runtime_failure",
        "timeout_or_runtime_failure",
        "timeout_or_runtime_failure",
    ]
    assert unattempted == [packets_and_schemas[3][0]]


def test_run_codex_packets_treats_repeated_schema_failures_as_systemic(tmp_path):
    packets_and_schemas = [
        _packet_and_schema(tmp_path, f"packet-{number}") for number in range(4)
    ]
    calls = 0

    def malformed_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(_fixture("malformed_final.json"), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, _fixture("success.jsonl"), "")

    results, unattempted = run_codex_packets(
        packets_and_schemas,
        timeout_seconds=30,
        runner=malformed_runner,
    )

    assert calls == 3
    assert len(results) == 3
    assert unattempted == [packets_and_schemas[3][0]]
