import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extraction.preflight_compact_requests import (
    preflight_primary_request,
)
from src.extraction.run_compact_one_call import run_one
from src.rag.compact_api_packet import CompactApiPacket


class FakeResponse:
    id = "resp_test"
    model = "gpt-5.6-terra-test"
    output = []
    output_text = ""
    usage = SimpleNamespace(
        model_dump=lambda mode="json": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        }
    )

    def model_dump(self, mode="json"):
        return {"id": self.id, "model": self.model}


class FakeResponses:
    def __init__(self, parsed):
        self.calls = []
        self.parsed = parsed

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = FakeResponse()
        response.output_text = self.parsed.model_dump_json()
        return response


def empty_response(paper_id="GP-TEST"):
    from src.extraction.compact_contracts import CompactExtractionResponse

    return CompactExtractionResponse.model_validate(
        {
            "contract_version": "compact-1.1.0",
            "paper_id": paper_id,
            "eligibility": {
                "decision": "uncertain",
                "reason_codes": ["FULL_TEXT_REQUIRED"],
                "evidence_ids": [],
                "explanation": "No evidence was supplied in this test packet.",
            },
            "formulations": [],
            "components": [],
            "experiments": [],
            "outcomes": [],
            "unresolved_items": [],
        }
    )


def write_packet(root: Path, paper_id="GP-TEST"):
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": paper_id,
        "blocked_fields": [],
        "sources": [],
        "evidence": [],
    }
    checksum = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    packet = CompactApiPacket.model_validate(
        {**unsigned, "packet_checksum": checksum}
    )
    root.mkdir(parents=True)
    (root / f"{paper_id}.json").write_text(packet.model_dump_json())


def approved_primary_request(
    tmp_path,
    *,
    paper_id="GP-TEST",
    model="gpt-5.6-terra",
):
    packet_root = tmp_path / "packets"
    preflight_root = tmp_path / "preflight"
    write_packet(packet_root, paper_id)
    manifest = preflight_primary_request(
        paper_id,
        model=model,
        packet_root=packet_root,
        output_root=preflight_root,
    )
    return SimpleNamespace(
        packet_root=packet_root,
        request_path=Path(manifest["request_path"]),
        sha256=manifest["request_sha256"],
        manifest_path=preflight_root / paper_id / "manifest.json",
        manifest=manifest,
    )


def test_default_primary_preflight_excludes_trial_accounting_fields(tmp_path):
    approved = approved_primary_request(tmp_path)
    request = json.loads(approved.request_path.read_text())
    schema = request["text"]["format"]["schema"]

    assert "accounting_contract_version" not in schema["properties"]
    assert "candidate_accounting" not in schema["properties"]
    assert approved.manifest["route_version"] == "compact-route-1.2.0"


def write_signed_manifest(path: Path, manifest):
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_checksum"
    }
    manifest = {
        **unsigned,
        "manifest_checksum": hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def test_run_one_refuses_without_explicit_paid_call_confirmation(tmp_path):
    approved = approved_primary_request(tmp_path)
    responses = FakeResponses(empty_response())
    client = SimpleNamespace(responses=responses)

    with pytest.raises(PermissionError, match="confirm_paid_call=True"):
        run_one(
            "GP-TEST",
            model="gpt-5.6-terra",
            client=client,
            approved_request_path=approved.request_path,
            approved_request_sha256=approved.sha256,
            preflight_manifest_path=approved.manifest_path,
            confirm_paid_call=False,
            packet_root=approved.packet_root,
            output_root=tmp_path / "output",
        )

    assert responses.calls == []


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("paper_id", "GP-WRONG"),
        ("packet_checksum", "0" * 64),
        ("model", "gpt-wrong"),
        ("request_fingerprint", "1" * 64),
        ("route", "repair"),
        ("route_version", "compact-route-wrong"),
        ("status", "failed"),
    ],
)
def test_run_one_rejects_wrong_signed_primary_binding_before_provider_use(
    tmp_path,
    field,
    wrong_value,
):
    approved = approved_primary_request(tmp_path)
    tampered = {**approved.manifest, field: wrong_value}
    write_signed_manifest(approved.manifest_path, tampered)
    responses = FakeResponses(empty_response())

    with pytest.raises(ValueError, match="approved|manifest|primary"):
        run_one(
            "GP-TEST",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            approved_request_path=approved.request_path,
            approved_request_sha256=approved.sha256,
            preflight_manifest_path=approved.manifest_path,
            confirm_paid_call=True,
            packet_root=approved.packet_root,
            output_root=tmp_path / "output",
        )

    assert responses.calls == []


def test_run_one_rejects_tampered_request_bytes_before_provider_use(
    tmp_path,
):
    approved = approved_primary_request(tmp_path)
    approved.request_path.write_bytes(
        approved.request_path.read_bytes() + b" "
    )
    responses = FakeResponses(empty_response())

    with pytest.raises(ValueError, match="request bytes"):
        run_one(
            "GP-TEST",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            approved_request_path=approved.request_path,
            approved_request_sha256=approved.sha256,
            preflight_manifest_path=approved.manifest_path,
            confirm_paid_call=True,
            packet_root=approved.packet_root,
            output_root=tmp_path / "output",
        )

    assert responses.calls == []


def test_run_one_rejects_tampered_manifest_checksum_before_provider_use(
    tmp_path,
):
    approved = approved_primary_request(tmp_path)
    tampered = {
        **approved.manifest,
        "manifest_checksum": "f" * 64,
    }
    approved.manifest_path.write_text(
        json.dumps(tampered),
        encoding="utf-8",
    )
    responses = FakeResponses(empty_response())

    with pytest.raises(ValueError, match="manifest checksum"):
        run_one(
            "GP-TEST",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            approved_request_path=approved.request_path,
            approved_request_sha256=approved.sha256,
            preflight_manifest_path=approved.manifest_path,
            confirm_paid_call=True,
            packet_root=approved.packet_root,
            output_root=tmp_path / "output",
        )

    assert responses.calls == []


def test_run_one_rejects_approved_output_limit_other_than_12000(
    tmp_path,
):
    approved = approved_primary_request(tmp_path)
    request = json.loads(approved.request_path.read_bytes())
    request["max_output_tokens"] = 11_999
    request_bytes = (
        json.dumps(request, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    approved.request_path.write_bytes(request_bytes)
    request_sha = hashlib.sha256(request_bytes).hexdigest()
    tampered = {
        **approved.manifest,
        "request_sha256": request_sha,
        "request_bytes": len(request_bytes),
        "max_output_tokens": 11_999,
    }
    write_signed_manifest(approved.manifest_path, tampered)
    responses = FakeResponses(empty_response())

    with pytest.raises(ValueError, match="12,000"):
        run_one(
            "GP-TEST",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            approved_request_path=approved.request_path,
            approved_request_sha256=request_sha,
            preflight_manifest_path=approved.manifest_path,
            confirm_paid_call=True,
            packet_root=approved.packet_root,
            output_root=tmp_path / "output",
        )

    assert responses.calls == []


def test_run_one_sends_exact_approved_request_and_records_usage(
    tmp_path,
    monkeypatch,
):
    output_root = tmp_path / "output"
    approved = approved_primary_request(tmp_path)
    approved_request_bytes = approved.request_path.read_bytes()
    approved_request = json.loads(approved_request_bytes)
    responses = FakeResponses(empty_response())
    client = SimpleNamespace(responses=responses)
    monkeypatch.setattr(
        "src.extraction.run_compact_one_call.build_openai_request",
        lambda *args, **kwargs: pytest.fail(
            "run_one must not rebuild an approved request"
        ),
    )

    manifest = run_one(
        "GP-TEST",
        model="gpt-5.6-terra",
        client=client,
        approved_request_path=approved.request_path,
        approved_request_sha256=approved.sha256,
        preflight_manifest_path=approved.manifest_path,
        confirm_paid_call=True,
        packet_root=approved.packet_root,
        output_root=output_root,
    )

    assert len(responses.calls) == 1
    assert responses.calls[0] == approved_request
    assert responses.calls[0]["store"] is False
    assert responses.calls[0]["service_tier"] == "default"
    assert len(responses.calls[0]["prompt_cache_key"]) <= 64
    assert responses.calls[0]["text"]["format"]["strict"] is True
    payload = json.loads(responses.calls[0]["input"][1]["content"])
    assert payload["evidence_packet"]["paper_id"] == "GP-TEST"
    assert payload["outcome_recall_support"]["support_version"] == (
        "main-route-recall-support-1.2.0"
    )
    assert manifest["paid_api_requests"] == 1
    assert manifest["checks"]["v12_recall_support_in_request"] is True
    assert manifest["usage"]["total_tokens"] == 120
    assert manifest["eligibility"]["decision"] == "uncertain"
    run_root = output_root / "GP-TEST"
    assert (run_root / "result.json").exists()
    assert (run_root / "request.json").read_bytes() == (
        approved_request_bytes
    )
    request_metadata = json.loads(
        (run_root / "request_metadata.json").read_text()
    )
    assert request_metadata["approved_request_sha256"] == approved.sha256


def test_run_one_rechecks_request_bytes_immediately_before_provider_use(
    tmp_path,
    monkeypatch,
):
    approved = approved_primary_request(tmp_path)
    responses = FakeResponses(empty_response())
    real_read_bytes = Path.read_bytes
    approved_path = approved.request_path.resolve()
    approved_reads = 0

    def changed_after_initial_validation(path):
        nonlocal approved_reads
        original = real_read_bytes(path)
        if path.resolve() == approved_path:
            approved_reads += 1
            if approved_reads > 1:
                return original + b" "
        return original

    monkeypatch.setattr(Path, "read_bytes", changed_after_initial_validation)

    with pytest.raises(
        ValueError,
        match="request bytes changed after validation",
    ):
        run_one(
            "GP-TEST",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            approved_request_path=approved.request_path,
            approved_request_sha256=approved.sha256,
            preflight_manifest_path=approved.manifest_path,
            confirm_paid_call=True,
            packet_root=approved.packet_root,
            output_root=tmp_path / "output",
        )

    assert approved_reads == 2
    assert responses.calls == []


def test_run_one_refuses_duplicate_paid_call(tmp_path):
    output_root = tmp_path / "output"
    approved = approved_primary_request(tmp_path)
    responses = FakeResponses(empty_response())
    client = SimpleNamespace(responses=responses)
    run_one(
        "GP-TEST",
        model="gpt-5.6-terra",
        client=client,
        approved_request_path=approved.request_path,
        approved_request_sha256=approved.sha256,
        preflight_manifest_path=approved.manifest_path,
        confirm_paid_call=True,
        packet_root=approved.packet_root,
        output_root=output_root,
    )

    with pytest.raises(FileExistsError, match="duplicate paid call"):
        run_one(
            "GP-TEST",
            model="gpt-5.6-terra",
            client=client,
            approved_request_path=approved.request_path,
            approved_request_sha256=approved.sha256,
            preflight_manifest_path=approved.manifest_path,
            confirm_paid_call=True,
            packet_root=approved.packet_root,
            output_root=output_root,
        )
    assert len(responses.calls) == 1
