import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from src.extraction import run_shadow_benchmark as benchmark_runner
from src.extraction.run_shadow_benchmark import (
    parse_codex_jsonl,
    run_audit_packet_benchmark,
    run_codex_packet,
    run_codex_packets,
)
from src.extraction.build_shadow_benchmark import build_audit_packets


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


def _sealed_packet() -> dict:
    packet_root = FIXTURE_ROOT.parent / "audit_packets"
    return build_audit_packets(
        json.loads((packet_root / "replayed.json").read_text(encoding="utf-8")),
        json.loads((packet_root / "evidence.json").read_text(encoding="utf-8")),
    )[0]


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


def test_run_codex_packet_rejects_incoherent_disposition_after_schema_validation(
    tmp_path,
):
    sealed = _sealed_packet()
    packet = tmp_path / "packet.json"
    schema = tmp_path / "schema.json"
    packet.write_text(json.dumps(sealed), encoding="utf-8")
    schema.write_text(json.dumps(sealed["output_schema"]), encoding="utf-8")
    invalid = {
        "disposition": "abstained",
        "proposals": [
            {
                "proposal_id": "AP-1",
                "proposal_type": "add_fact",
                "experiment_id": None,
                "candidate_id": None,
                "field_name": "formulation_name",
                "raw_values": ["Lipid A"],
                "evidence_ids": [sealed["issued_ids"]["evidence_ids"][0]],
                "quoted_support": "Lipid A",
            }
        ],
        "unresolved_reason": "not enough evidence",
    }

    result = run_codex_packet(
        packet,
        schema,
        30,
        runner=_completed_with_final(_fixture("success.jsonl"), json.dumps(invalid)),
    )

    assert result["terminal_disposition"] == "schema_failure"
    assert any("Abstained disposition" in issue for issue in result["validation_issues"])


def test_run_codex_packet_retries_timeout_once_and_records_each_raw_stream(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)
    calls = 0
    timed_out_raw_jsonl = _fixture("success.jsonl").encode("utf-8") + b"\xff\n"

    def timeout_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=timed_out_raw_jsonl)

    result = run_codex_packet(packet, schema, 30, runner=timeout_runner)

    assert calls == 2
    assert result["terminal_disposition"] == "timeout_or_runtime_failure"
    assert result["attempt_count"] == 2
    assert result["retry_count"] == 1
    assert len(result["raw_jsonl_paths"]) == 2
    assert all(
        Path(path).read_bytes() == timed_out_raw_jsonl
        for path in result["raw_jsonl_paths"]
    )


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


def test_run_codex_packet_preserves_complete_records_for_both_attempts(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)
    calls = 0

    def eventually_successful_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                command, 17, _fixture("success.jsonl").encode(), b"first failed"
            )
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(_fixture("valid_final.json"), encoding="utf-8")
        return subprocess.CompletedProcess(
            command, 0, _fixture("success.jsonl").encode(), b""
        )

    result = run_codex_packet(packet, schema, 30, runner=eventually_successful_runner)

    assert result["terminal_disposition"] == "accepted"
    assert result["attempt_count"] == 2
    assert len(result["attempts"]) == 2
    first, second = result["attempts"]
    assert first["terminal_disposition"] == "timeout_or_runtime_failure"
    assert first["exit_code"] == 17
    assert first["model"] == "gpt-5-codex"
    assert first["input_tokens"] == 120
    assert first["output_tokens"] == 30
    assert first["cached_input_tokens"] == 40
    assert "status 17" in first["validation_issues"][0]
    assert Path(first["attempt_record_path"]).is_file()
    persisted_first = json.loads(
        Path(first["attempt_record_path"]).read_text(encoding="utf-8")
    )
    assert persisted_first == first
    assert second["terminal_disposition"] == "accepted"
    assert second["exit_code"] == 0
    assert second["token_measurement_reason"] is None


def test_run_codex_packet_preserves_raw_jsonl_bytes_and_reports_decode_failure(tmp_path):
    packet, schema = _packet_and_schema(tmp_path)
    raw_jsonl = b'{"type":"thread.started","model":"gpt-5-codex"}\r\n\xff\n'
    command_kwargs: list[dict] = []

    def non_utf8_runner(command, **kwargs):
        command_kwargs.append(kwargs)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(_fixture("valid_final.json"), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, raw_jsonl, b"")

    result = run_codex_packet(packet, schema, 30, runner=non_utf8_runner)

    assert command_kwargs[0]["text"] is False
    assert result["terminal_disposition"] == "schema_failure"
    assert Path(result["raw_jsonl_paths"][0]).read_bytes() == raw_jsonl
    assert any("not valid UTF-8" in issue for issue in result["validation_issues"])


def test_run_audit_packet_benchmark_executes_sealed_packet_with_its_schema(tmp_path):
    packet = _sealed_packet()
    commands: list[list[str]] = []

    def runner(command, **kwargs):
        commands.append(command)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(_fixture("valid_final.json"), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, _fixture("success.jsonl").encode(), b"")

    results, unattempted = run_audit_packet_benchmark(
        [packet], run_root=tmp_path, timeout_seconds=30, runner=runner
    )

    assert not unattempted
    assert results[0]["terminal_disposition"] == "accepted"
    isolation = json.loads(
        (tmp_path / "audit_packets/gold_isolation.json").read_text(encoding="utf-8")
    )
    assert isolation["passed"] is True
    assert isolation["checked_file_count"] == 3
    command = commands[0]
    assert "--json" in command
    schema_path = Path(command[command.index("--output-schema") + 1])
    assert json.loads(schema_path.read_text(encoding="utf-8")) == packet["output_schema"]


def test_main_audit_route_uses_sealed_packet_runner_not_legacy_audit_path(
    tmp_path, monkeypatch
):
    packet = _sealed_packet()

    def runner(command, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(_fixture("valid_final.json"), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, _fixture("success.jsonl").encode(), b"")

    monkeypatch.setattr(benchmark_runner, "REPORT_ROOT", tmp_path)
    monkeypatch.setattr(benchmark_runner, "_build_executable_audit_packets", lambda: [packet])
    monkeypatch.setattr(
        benchmark_runner,
        "run_cases",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy route used")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_shadow_benchmark.py",
            "--run-id",
            "fixture-audit",
            "--route",
            "audit",
            "--backend",
            "codex",
            "--model",
            "hosted-default",
        ],
    )

    benchmark_runner.main(packet_runner=runner)

    manifest = json.loads(
        (tmp_path / "fixture-audit/audit-codex/run_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["attempt_count"] == 1
    assert manifest["terminal_dispositions"] == {"accepted": 1}
    packet_results = json.loads(
        (tmp_path / "fixture-audit/audit-codex/packet_results.json").read_text(
            encoding="utf-8"
        )
    )
    assert packet_results["packet_count"] == 1
    assert packet_results["results"][0]["parsed_result"]["disposition"] == "abstained"
    assert packet_results["results"][0]["packet_path"].endswith("packet.json")


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


def test_run_codex_packets_executes_at_most_two_packets_concurrently(tmp_path):
    packets_and_schemas = [
        _packet_and_schema(tmp_path, f"packet-{number}") for number in range(4)
    ]
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def concurrent_runner(command, **kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        barrier.wait(timeout=2)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(_fixture("valid_final.json"), encoding="utf-8")
        with lock:
            active -= 1
        return subprocess.CompletedProcess(
            command, 0, _fixture("success.jsonl").encode(), b""
        )

    results, unattempted = run_codex_packets(
        packets_and_schemas,
        timeout_seconds=30,
        concurrency=2,
        max_wall_seconds=60,
        runner=concurrent_runner,
    )

    assert maximum_active == 2
    assert [Path(result["packet_path"]).stem for result in results] == [
        f"packet-{number}" for number in range(4)
    ]
    assert unattempted == []


def test_run_codex_packets_stops_issuing_work_after_wall_clock_cutoff(tmp_path):
    packets_and_schemas = [
        _packet_and_schema(tmp_path, f"packet-{number}") for number in range(4)
    ]
    calls = 0

    def slow_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        time.sleep(0.03)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(_fixture("valid_final.json"), encoding="utf-8")
        return subprocess.CompletedProcess(
            command, 0, _fixture("success.jsonl").encode(), b""
        )

    results, unattempted = run_codex_packets(
        packets_and_schemas,
        timeout_seconds=30,
        concurrency=2,
        max_wall_seconds=0.01,
        runner=slow_runner,
    )

    assert calls == 2
    assert len(results) == 2
    assert unattempted == [path for path, _schema in packets_and_schemas[2:]]
