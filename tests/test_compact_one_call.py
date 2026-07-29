from pathlib import Path
from types import SimpleNamespace
import json

import pytest

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
    import hashlib
    import json

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


def test_run_one_makes_exactly_one_structured_call_and_records_usage(tmp_path):
    packet_root = tmp_path / "packets"
    output_root = tmp_path / "output"
    write_packet(packet_root)
    responses = FakeResponses(empty_response())
    client = SimpleNamespace(responses=responses)

    manifest = run_one(
        "GP-TEST",
        model="gpt-5.6-terra",
        client=client,
        packet_root=packet_root,
        output_root=output_root,
    )

    assert len(responses.calls) == 1
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
    request_snapshot = json.loads(
        (run_root / "request.json").read_text()
    )
    assert request_snapshot["api_request"] == responses.calls[0]


def test_run_one_refuses_duplicate_paid_call(tmp_path):
    packet_root = tmp_path / "packets"
    output_root = tmp_path / "output"
    write_packet(packet_root)
    responses = FakeResponses(empty_response())
    client = SimpleNamespace(responses=responses)
    run_one(
        "GP-TEST",
        model="gpt-5.6-terra",
        client=client,
        packet_root=packet_root,
        output_root=output_root,
    )

    with pytest.raises(FileExistsError, match="duplicate paid call"):
        run_one(
            "GP-TEST",
            model="gpt-5.6-terra",
            client=client,
            packet_root=packet_root,
            output_root=output_root,
        )
    assert len(responses.calls) == 1
