import json

import httpx
from openai import OpenAI

from src.extraction.preflight_compact_requests import (
    _evidence_checks,
    _schema_checks,
)
from src.extraction.run_compact_one_call import (
    build_openai_request,
    load_packet,
)


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
