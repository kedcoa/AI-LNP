import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.run_compact_one_call import (
    PRIMARY_ROUTE,
    PRIMARY_ROUTE_VERSION,
    build_openai_request,
    load_packet,
)
from src.rag.compact_api_packet import CompactApiPacket


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _write_packet(root: Path, paper_id="NP-001"):
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": paper_id,
        "blocked_fields": [],
        "sources": [],
        "evidence": [],
    }
    packet = CompactApiPacket.model_validate(
        {**unsigned, "packet_checksum": _sha256(_canonical_json(unsigned))}
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{paper_id}.json").write_text(packet.model_dump_json(), encoding="utf-8")
    return packet


def _support():
    candidates = [
        {
            "candidate_id": f"AOC-{index:02d}",
            "paper_id": "NP-001",
            "evidence_ids": [f"E-{index:02d}"],
            "source_ids": [f"source-{index:02d}"],
            "subject_text": f"subject {index}",
            "endpoint_text": f"endpoint {index}",
            "value_text": f"value {index}",
        }
        for index in range(1, 37)
    ]
    return {
        "support_version": "main-route-recall-support-1.2.0",
        "paper_id": "NP-001",
        "instructions": ["existing support instruction"],
        "provisional_experiments": [],
        "atomic_outcome_candidates": candidates,
        "accepted_visual_claims": [],
        "local_evidence": [
            {
                "evidence_id": candidate["evidence_ids"][0],
                "text": f"support text {index}",
                "source_ids": candidate["source_ids"],
                "source_kind": "text",
                "provenance": candidate["source_ids"],
            }
            for index, candidate in enumerate(candidates, start=1)
        ],
        "estimated_tokens": 123,
    }


@pytest.fixture
def trial_module(monkeypatch):
    from src.extraction import run_primary_accounting_trial as trial

    monkeypatch.setattr(trial, "build_v12_route_support", lambda packet: _support())
    return trial


def _empty_trial_response():
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": "NP-001",
        "eligibility": {
            "decision": "uncertain",
            "reason_codes": ["FULL_TEXT_REQUIRED"],
            "evidence_ids": [],
            "explanation": "No outcome is asserted by this accounting trial fixture.",
        },
        "formulations": [],
        "components": [],
        "experiments": [],
        "outcomes": [],
        "unresolved_items": [],
        "accounting_contract_version": "compact-accounting-trial-1.0.0",
        "candidate_accounting": {
            f"AOC-{index:02d}": {
                "disposition": "insufficient_evidence",
                "linked_outcome_ids": [],
                "evidence_ids": [f"E-{index:02d}"],
                "reason_code": "evidence_does_not_support_outcome",
            }
            for index in range(1, 37)
        },
    }


class _FakeResponse:
    id = "resp-np001"
    model = "gpt-5.6-terra-test"
    output = []

    def __init__(self, output_text):
        self.output_text = output_text
        self.usage = SimpleNamespace(
            model_dump=lambda mode="json": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            }
        )

    def model_dump(self, mode="json"):
        return {"id": self.id, "model": self.model}


class _FakeResponses:
    def __init__(self, output_text):
        self.calls = []
        self.output_text = output_text

    def create(self, **request):
        self.calls.append(request)
        return _FakeResponse(self.output_text)


def _preflight(tmp_path, trial_module):
    packet_root = tmp_path / "packets"
    output_root = tmp_path / "preflight"
    packet = _write_packet(packet_root)
    manifest = trial_module.preflight_trial_request(
        "NP-001",
        model="gpt-5.6-terra",
        packet_root=packet_root,
        output_root=output_root,
    )
    return SimpleNamespace(
        packet=packet,
        packet_root=packet_root,
        output_root=output_root,
        manifest=manifest,
        manifest_path=output_root / "NP-001" / "manifest.json",
        request_path=output_root / "NP-001" / "request.json",
    )


def test_trial_request_is_np001_only_and_binds_ordered_candidate_contract(tmp_path, trial_module):
    packet_root = tmp_path / "packets"
    packet = _write_packet(packet_root)

    request, support, payload, bindings = trial_module.build_trial_request(
        packet, model="gpt-5.6-terra"
    )

    assert support["atomic_outcome_candidates"] == _support()["atomic_outcome_candidates"]
    assert payload["candidate_facts"] == _support()["atomic_outcome_candidates"]
    assert request["max_output_tokens"] == 12_000
    assert bindings["route"] == "primary-candidate-accounting-trial"
    assert bindings["route_version"] == "compact-route-1.3.0-trial"
    assert bindings["core_contract_version"] == "compact-1.1.0"
    assert request["text"]["format"]["schema"] == bindings["dynamic_schema"]
    assert request["text"]["format"]["schema"]["required"][-2:] == [
        "accounting_contract_version",
        "candidate_accounting",
    ]
    assert list(
        request["text"]["format"]["schema"]["properties"]["candidate_accounting"]["properties"]
    ) == [f"AOC-{index:02d}" for index in range(1, 37)]
    assert bindings["candidate_facts_sha256"] == _sha256(
        _canonical_json(payload["candidate_facts"])
    )
    assert bindings["dynamic_schema_sha256"] == _sha256(
        _canonical_json(request["text"]["format"]["schema"])
    )
    assert "extracted" in request["input"][0]["content"]
    assert "ambiguous" in request["input"][0]["content"]

    with pytest.raises(ValueError, match="NP-001"):
        trial_module.preflight_trial_request(
            "GP-001", model="gpt-5.6-terra", packet_root=packet_root, output_root=tmp_path / "out"
        )


def test_cli_without_subcommand_dispatches_to_preflight(monkeypatch, capsys, trial_module):
    calls = []

    def fake_preflight(paper_id, **kwargs):
        calls.append({"paper_id": paper_id, **kwargs})
        return {"status": "passed"}

    monkeypatch.setattr(trial_module, "preflight_trial_request", fake_preflight)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_primary_accounting_trial.py",
            "--paper-id",
            "NP-001",
            "--packet-root",
            "/tmp/packets",
            "--output-root",
            "/tmp/output",
        ],
    )

    trial_module.main()

    assert calls == [{
        "paper_id": "NP-001",
        "model": "gpt-5.6-terra",
        "packet_root": Path("/tmp/packets"),
        "output_root": Path("/tmp/output"),
    }]
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


def test_default_primary_request_stays_on_its_existing_contract(tmp_path):
    packet = _write_packet(tmp_path / "packets")
    request, _support, _payload, _fingerprint = build_openai_request(
        packet, model="gpt-5.6-terra"
    )

    assert PRIMARY_ROUTE == "primary"
    assert PRIMARY_ROUTE_VERSION == "compact-route-1.2.0"
    assert "candidate_accounting" not in request["text"]["format"]["schema"]["properties"]


def test_preflight_persists_exact_request_audits_preview_and_signed_bindings(tmp_path, trial_module):
    approved = _preflight(tmp_path, trial_module)
    request_bytes = approved.request_path.read_bytes()
    manifest = approved.manifest

    assert json.loads(request_bytes)["max_output_tokens"] == 12_000
    assert (approved.output_root / "NP-001" / "audits.json").exists()
    preview = (approved.output_root / "NP-001" / "preview.txt").read_text()
    assert str(approved.request_path.resolve()) in preview
    assert manifest["request_sha256"] in preview
    assert "Estimated input tokens:" in preview
    assert "Output cap: 12000" in preview
    assert "Candidates: 36" in preview
    assert "Proposed paid calls: 1" in preview
    assert manifest["provider_calls"] == 0
    assert manifest["packet_checksum"] == approved.packet.packet_checksum
    assert manifest["candidate_facts_sha256"] == _sha256(_canonical_json(_support()["atomic_outcome_candidates"]))
    assert manifest["dynamic_schema_sha256"] == _sha256(
        _canonical_json(json.loads(request_bytes)["text"]["format"]["schema"])
    )
    assert manifest["request_sha256"] == _sha256(request_bytes)
    assert manifest["manifest_checksum"] == _sha256(_canonical_json({
        key: value for key, value in manifest.items() if key != "manifest_checksum"
    }))


@pytest.mark.parametrize("approved_sha", [None, "0" * 64])
def test_run_approved_refuses_missing_or_mismatched_approval_without_provider(tmp_path, trial_module, approved_sha):
    approved = _preflight(tmp_path, trial_module)
    responses = _FakeResponses(json.dumps(_empty_trial_response()))

    with pytest.raises((PermissionError, ValueError), match="approval|SHA"):
        trial_module.run_approved_trial(
            "NP-001",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            manifest_path=approved.manifest_path,
            approved_request_sha256=approved_sha,
            packet_root=approved.packet_root,
            output_root=tmp_path / "runs",
        )

    assert responses.calls == []


def test_run_approved_refuses_modified_bytes_and_existing_completion_without_provider(tmp_path, trial_module):
    approved = _preflight(tmp_path, trial_module)
    approved.request_path.write_bytes(approved.request_path.read_bytes() + b" ")
    responses = _FakeResponses(json.dumps(_empty_trial_response()))

    with pytest.raises(ValueError, match="request bytes"):
        trial_module.run_approved_trial(
            "NP-001", model="gpt-5.6-terra", client=SimpleNamespace(responses=responses),
            manifest_path=approved.manifest_path,
            approved_request_sha256=approved.manifest["request_sha256"],
            packet_root=approved.packet_root, output_root=tmp_path / "runs",
        )
    assert responses.calls == []

    fresh = _preflight(tmp_path / "fresh", trial_module)
    run_dir = tmp_path / "completed" / "NP-001"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="completed"):
        trial_module.run_approved_trial(
            "NP-001", model="gpt-5.6-terra", client=SimpleNamespace(responses=responses),
            manifest_path=fresh.manifest_path,
            approved_request_sha256=fresh.manifest["request_sha256"],
            packet_root=fresh.packet_root, output_root=tmp_path / "completed",
        )
    assert responses.calls == []


def test_run_approved_sends_the_signed_request_once_and_persists_trial_validator_artifacts(tmp_path, trial_module):
    approved = _preflight(tmp_path, trial_module)
    responses = _FakeResponses(json.dumps(_empty_trial_response()))
    output_root = tmp_path / "runs"

    manifest = trial_module.run_approved_trial(
        "NP-001",
        model="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
        manifest_path=approved.manifest_path,
        approved_request_sha256=approved.manifest["request_sha256"],
        packet_root=approved.packet_root,
        output_root=output_root,
    )

    assert responses.calls == [json.loads(approved.request_path.read_bytes())]
    assert manifest["paid_api_requests"] == 1
    assert manifest["repair_calls"] == 0
    assert manifest["vision_calls"] == 0
    assert manifest["candidate_count"] == 36
    report = json.loads((output_root / "NP-001" / "accounting_report.json").read_text())
    assert report["candidates_accounted_for"] == 36
    assert report["errors"] == []
    assert json.loads((output_root / "NP-001" / "result.json").read_text())["paper_id"] == "NP-001"
