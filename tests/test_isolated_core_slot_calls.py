import json
from types import SimpleNamespace

import pytest

from tests.test_core_slot_trial import (
    _FakeResponses,
    _trial_response,
    _write_packet,
)


SLOT_IDS = [
    "CORE-HEPG2-TRANSFECTION",
    "CORE-DC24-TRANSFECTION",
    "CORE-DC24-IMMUNE",
    "CORE-HPBMC-TRANSFECTION",
    "CORE-HPBMC-IMMUNE",
    "CORE-MOUSE-BIODISTRIBUTION",
]


def _preflight(tmp_path):
    from src.extraction.run_isolated_core_slot_calls import (
        preflight_isolated_core_calls,
    )

    packet_root = tmp_path / "packets"
    _write_packet(packet_root)
    output_root = tmp_path / "preflight"
    manifest = preflight_isolated_core_calls(
        "NP-001",
        model="gpt-5.6-terra",
        packet_root=packet_root,
        output_root=output_root,
    )
    return SimpleNamespace(
        packet_root=packet_root,
        output_root=output_root,
        manifest=manifest,
    )


def test_preflight_emits_six_ordered_one_slot_extracted_only_requests(
    tmp_path,
):
    approved = _preflight(tmp_path)

    assert approved.manifest["slot_ids"] == SLOT_IDS
    assert approved.manifest["provider_calls"] == 0
    assert len(approved.manifest["requests"]) == 6
    hashes = []
    for index, entry in enumerate(
        approved.manifest["requests"],
        start=1,
    ):
        request = json.loads(open(entry["request_path"]).read())
        payload = json.loads(request["input"][1]["content"])
        schema = request["text"]["format"]["schema"]
        slot_id = SLOT_IDS[index - 1]
        accounting = schema["properties"]["core_slot_accounting"]
        disposition = schema["$defs"]["CoreSlotAccountingEntry"][
            "properties"
        ]["disposition"]

        assert entry["sequence"] == index
        assert entry["slot_id"] == slot_id
        assert len(payload["core_slot_packets"]) == 1
        assert payload["core_slot_packets"][0]["slot_id"] == slot_id
        assert list(accounting["properties"]) == [slot_id]
        assert accounting["required"] == [slot_id]
        assert disposition["enum"] == ["extracted"]
        assert schema["properties"]["experiments"]["minItems"] == 1
        assert schema["properties"]["experiments"]["maxItems"] == 1
        assert schema["properties"]["outcomes"]["minItems"] == 1
        assert schema["properties"]["unresolved_items"]["maxItems"] == 0
        assert entry["provider_calls"] == 0
        hashes.append(entry["request_sha256"])

    assert len(set(hashes)) == 6


def test_runner_dispatches_six_requests_strictly_in_order(tmp_path):
    from src.extraction.run_isolated_core_slot_calls import (
        run_approved_isolated_core_calls,
    )

    approved = _preflight(tmp_path)
    responses = _FakeResponses(json.dumps(_trial_response()))
    approvals = {
        row["slot_id"]: row["request_sha256"]
        for row in approved.manifest["requests"]
    }

    result = run_approved_isolated_core_calls(
        "NP-001",
        model="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
        preflight_manifest_path=(
            approved.output_root / "NP-001" / "manifest.json"
        ),
        approved_request_sha256_by_slot=approvals,
        packet_root=approved.packet_root,
        output_root=tmp_path / "runs",
    )

    called_slots = [
        json.loads(call["input"][1]["content"])[
            "core_slot_packets"
        ][0]["slot_id"]
        for call in responses.calls
    ]
    assert called_slots == SLOT_IDS
    assert result["paid_api_requests"] == 6
    assert result["repair_calls"] == 0
    assert result["vision_calls"] == 0
    assert result["completed_slot_ids"] == SLOT_IDS


def test_runner_stops_sequence_on_provider_ambiguity(tmp_path):
    from src.extraction.run_isolated_core_slot_calls import (
        run_approved_isolated_core_calls,
    )

    approved = _preflight(tmp_path)

    class FailSecond:
        def __init__(self):
            self.calls = []

        def create(self, **request):
            self.calls.append(request)
            if len(self.calls) == 2:
                raise TimeoutError("provider outcome unknown")
            return _FakeResponses(
                json.dumps(_trial_response())
            ).create(**request)

    responses = FailSecond()
    approvals = {
        row["slot_id"]: row["request_sha256"]
        for row in approved.manifest["requests"]
    }

    with pytest.raises(TimeoutError, match="unknown"):
        run_approved_isolated_core_calls(
            "NP-001",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            preflight_manifest_path=(
                approved.output_root / "NP-001" / "manifest.json"
            ),
            approved_request_sha256_by_slot=approvals,
            packet_root=approved.packet_root,
            output_root=tmp_path / "runs",
        )

    assert len(responses.calls) == 2
    second_dir = tmp_path / "runs" / "NP-001" / "02"
    assert (second_dir / "invocation_started.json").exists()
    assert not (tmp_path / "runs" / "NP-001" / "03").exists()
