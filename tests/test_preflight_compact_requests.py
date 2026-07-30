import hashlib
import json

import httpx
from openai import OpenAI

from src.extraction import preflight_compact_requests as preflight_module
from src.extraction.preflight_compact_requests import (
    _evidence_checks,
    _schema_checks,
)
from src.extraction.run_compact_one_call import (
    build_openai_request,
    load_packet,
)
from src.rag.compact_api_packet import CompactApiPacket


def write_packet(root, paper_id="GP-TEST"):
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
    (root / f"{paper_id}.json").write_text(
        packet.model_dump_json(),
        encoding="utf-8",
    )
    return packet


def test_primary_preflight_persists_exact_request_and_signed_manifest_locally(
    tmp_path,
    monkeypatch,
):
    packet_root = tmp_path / "packets"
    output_root = tmp_path / "preflight"
    packet = write_packet(packet_root)
    calls = []
    real_builder = preflight_module.build_openai_request

    def counted_builder(*args, **kwargs):
        calls.append((args, kwargs))
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(
        preflight_module,
        "build_openai_request",
        counted_builder,
    )

    manifest = preflight_module.preflight_primary_request(
        "GP-TEST",
        model="gpt-5.6-terra",
        packet_root=packet_root,
        output_root=output_root,
    )

    request_path = output_root / "GP-TEST" / "request.json"
    request_bytes = request_path.read_bytes()
    unsigned_manifest = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_checksum"
    }
    assert len(calls) == 1
    assert manifest["preflight_version"] == (
        "compact-primary-request-preflight-1.2.0"
    )
    assert manifest["status"] == "passed"
    assert manifest["human_approval_required"] is True
    assert manifest["request_path"] == str(request_path.resolve())
    assert manifest["request_sha256"] == hashlib.sha256(
        request_bytes
    ).hexdigest()
    assert manifest["paper_id"] == "GP-TEST"
    assert manifest["model"] == "gpt-5.6-terra"
    assert manifest["packet_checksum"] == packet.packet_checksum
    assert manifest["request_bytes"] == len(request_bytes)
    assert manifest["estimated_input_tokens"] > 0
    assert manifest["max_output_tokens"] == 12_000
    assert manifest["schema_checks"]["all_object_fields_required"]
    assert manifest["evidence_checks"][
        "all_support_evidence_ids_resolve"
    ]
    assert manifest["provider_calls"] == 0
    assert manifest["manifest_checksum"] == hashlib.sha256(
        json.dumps(
            unsigned_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert json.loads(
        (output_root / "GP-TEST" / "manifest.json").read_bytes()
    ) == manifest


def test_primary_preflight_batch_runner_requires_no_provider_client(tmp_path):
    packet_root = tmp_path / "packets"
    output_root = tmp_path / "preflight"
    write_packet(packet_root)

    report = preflight_module.run(
        ["GP-TEST"],
        model="gpt-5.6-terra",
        packet_root=packet_root,
        output_root=output_root,
    )

    assert report["status"] == "passed"
    assert report["provider_calls"] == 0
    assert report["papers"][0]["paper_id"] == "GP-TEST"


def test_exact_request_passes_local_schema_and_evidence_preflight():
    packet = load_packet("GP-008")
    request, support, _payload, fingerprint = build_openai_request(
        packet,
        model="gpt-5.6-terra",
    )
    schema = _schema_checks(request["text"]["format"]["schema"])
    evidence = _evidence_checks(request, support)

    assert len(fingerprint) == 64
    assert schema["root_is_object"]
    assert schema["root_is_not_any_of"]
    assert schema["all_object_fields_required"]
    assert schema["all_objects_disallow_extra_properties"]
    assert schema["within_5000_property_limit"]
    assert schema["within_10_level_object_limit"]
    assert evidence["all_support_evidence_ids_resolve"]
    assert len(support["accepted_visual_claims"]) == 1


def test_installed_openai_sdk_serializes_exact_generation_request():
    captured = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_mock",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "gpt-5.6-terra",
                "output": [],
            },
        )

    client = OpenAI(
        api_key="test",
        base_url="https://mock.invalid/v1",
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
    )
    request, _support, _payload, _fingerprint = build_openai_request(
        load_packet("GP-008"),
        model="gpt-5.6-terra",
    )
    client.responses.create(**request)

    assert captured["path"] == "/v1/responses"
    assert captured["body"] == request
