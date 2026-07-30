import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.rag.compact_api_packet import CompactApiPacket


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _write_packet(root: Path, paper_id="NP-001", include_mouse=True):
    texts = [
        (
            "E-FORM",
            "The DX-loaded LNP formulation contained ALC-0315, DSPC or "
            "DOPE, cholesterol/DX, and ALC-0159.",
        ),
        (
            "E-PAYLOAD",
            "The lipid nanoparticles encapsulated EGFP mRNA payload.",
        ),
        (
            "E-HEPG2-TX",
            "HepG2 cells were transfected and showed EGFP expression.",
        ),
        (
            "E-DC24-TX",
            "DC2.4 dendritic cells were transfected and expressed EGFP.",
        ),
        (
            "E-DC24-IMM",
            "DC2.4 dendritic cells released IL-6 cytokine after delivery.",
        ),
        (
            "E-HPBMC-TX",
            "hPBMCs were transfected and showed reporter expression.",
        ),
        (
            "E-HPBMC-IMM",
            "Human PBMCs mounted a TNF-alpha immune cytokine response.",
        ),
    ]
    if include_mouse:
        texts.append(
            (
                "E-MOUSE-BIO",
                "In vivo mouse biodistribution showed liver accumulation.",
            )
        )
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": paper_id,
        "blocked_fields": [],
        "sources": [],
        "evidence": [
            {
                "evidence_id": evidence_id,
                "text": text,
                "retrieval_field_tags": [],
                "experiment_candidate_ids": [],
                "source_ids": [],
            }
            for evidence_id, text in texts
        ],
    }
    packet = CompactApiPacket.model_validate(
        {
            **unsigned,
            "packet_checksum": _sha256(_canonical_json(unsigned)),
        }
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{paper_id}.json").write_text(
        packet.model_dump_json(),
        encoding="utf-8",
    )
    return packet


def test_preflight_is_np001_only_and_never_needs_a_provider(tmp_path):
    from src.extraction.run_core_slot_trial import preflight_core_slot_trial

    packet_root = tmp_path / "packets"
    _write_packet(packet_root, paper_id="GP-001")

    with pytest.raises(ValueError, match="NP-001"):
        preflight_core_slot_trial(
            "GP-001",
            model="gpt-5.6-terra",
            packet_root=packet_root,
            output_root=tmp_path / "preflight",
        )


def test_preflight_writes_qualified_only_exact_request_and_signed_preview(
    tmp_path,
):
    from src.extraction.run_core_slot_trial import preflight_core_slot_trial

    packet_root = tmp_path / "packets"
    packet = _write_packet(packet_root, include_mouse=False)
    output_root = tmp_path / "preflight"

    manifest = preflight_core_slot_trial(
        "NP-001",
        model="gpt-5.6-terra",
        packet_root=packet_root,
        output_root=output_root,
    )

    paper_root = output_root / "NP-001"
    request_bytes = (paper_root / "request.json").read_bytes()
    request = json.loads(request_bytes)
    payload = json.loads(request["input"][1]["content"])
    qualification = json.loads(
        (paper_root / "slot_qualification.json").read_text()
    )
    schema = request["text"]["format"]["schema"]
    qualified_ids = [
        row["slot_id"] for row in qualification["qualified_slots"]
    ]
    excluded_ids = [
        row["slot_id"]
        for row in qualification["evaluated_slots"]
        if not row["qualified"]
    ]

    assert len(qualification["evaluated_slots"]) == 6
    assert qualified_ids == [
        "CORE-HEPG2-TRANSFECTION",
        "CORE-DC24-TRANSFECTION",
        "CORE-DC24-IMMUNE",
        "CORE-HPBMC-TRANSFECTION",
        "CORE-HPBMC-IMMUNE",
    ]
    assert excluded_ids == ["CORE-MOUSE-BIODISTRIBUTION"]
    assert [
        row["slot_id"] for row in payload["core_slot_packets"]
    ] == qualified_ids
    for slot_packet in payload["core_slot_packets"]:
        allowed = next(
            row["evidence_ids"]
            for row in qualification["qualified_slots"]
            if row["slot_id"] == slot_packet["slot_id"]
        )
        assert [
            row["evidence_id"] for row in slot_packet["evidence"]
        ] == allowed
    accounting = schema["properties"]["core_slot_accounting"]
    assert list(accounting["properties"]) == qualified_ids
    assert accounting["required"] == qualified_ids

    assert manifest["preflight_version"] == (
        "compact-core-slot-preflight-1.0.0"
    )
    assert manifest["route"] == "primary-core-biological-slot-trial"
    assert manifest["route_version"] == "compact-route-1.4.0-trial"
    assert manifest["paper_id"] == "NP-001"
    assert manifest["model"] == "gpt-5.6-terra"
    assert manifest["packet_checksum"] == packet.packet_checksum
    assert manifest["slot_qualification_sha256"] == _sha256(
        _canonical_json(qualification)
    )
    assert manifest["dynamic_schema_sha256"] == _sha256(
        _canonical_json(schema)
    )
    assert manifest["request_sha256"] == _sha256(request_bytes)
    assert manifest["provider_calls"] == 0
    assert manifest["proposed_calls"] == 1
    assert manifest["estimated_input_tokens"] > 0
    assert manifest["max_output_tokens"] > 0
    preview = (paper_root / "preview.txt").read_text()
    assert f"Qualified slots: {', '.join(qualified_ids)}" in preview
    assert "Excluded slots: CORE-MOUSE-BIODISTRIBUTION" in preview
    assert "Estimated input tokens:" in preview
    assert "Output cap:" in preview
    assert "Proposed calls: 1" in preview
    assert "Provider calls: 0" in preview
    assert not (paper_root / "invocation_started.json").exists()
    assert not (paper_root / "response.json").exists()


def _trial_response():
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": "NP-001",
        "eligibility": {
            "decision": "uncertain",
            "reason_codes": ["FULL_TEXT_REQUIRED"],
            "evidence_ids": [],
            "explanation": "Synthetic guarded-execution fixture.",
        },
        "formulations": [],
        "components": [],
        "experiments": [],
        "outcomes": [],
        "unresolved_items": [],
        "core_slot_contract_version": (
            "compact-core-slot-trial-1.0.0"
        ),
        "core_slot_accounting": {},
    }


class _FakeResponse:
    id = "resp-core-slot"
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
    def __init__(self, output_text, before_return=None):
        self.calls = []
        self.output_text = output_text
        self.before_return = before_return

    def create(self, **request):
        self.calls.append(request)
        if self.before_return:
            self.before_return()
        return _FakeResponse(self.output_text)


class _FailingResponses:
    def __init__(self, before_raise):
        self.calls = []
        self.before_raise = before_raise

    def create(self, **request):
        self.calls.append(request)
        self.before_raise()
        raise TimeoutError("provider outcome is unknown")


def _preflight(tmp_path):
    from src.extraction.run_core_slot_trial import (
        preflight_core_slot_trial,
    )

    packet_root = tmp_path / "packets"
    _write_packet(packet_root)
    output_root = tmp_path / "preflight"
    manifest = preflight_core_slot_trial(
        "NP-001",
        model="gpt-5.6-terra",
        packet_root=packet_root,
        output_root=output_root,
    )
    return SimpleNamespace(
        packet_root=packet_root,
        output_root=output_root,
        manifest=manifest,
        manifest_path=output_root / "NP-001" / "manifest.json",
        request_path=output_root / "NP-001" / "request.json",
    )


@pytest.mark.parametrize("approved_sha", [None, "0" * 64])
def test_run_refuses_missing_or_mismatched_approval_before_provider(
    tmp_path,
    approved_sha,
):
    from src.extraction.run_core_slot_trial import (
        run_approved_core_slot_trial,
    )

    approved = _preflight(tmp_path)
    responses = _FakeResponses(json.dumps(_trial_response()))

    with pytest.raises((PermissionError, ValueError), match="approval|SHA"):
        run_approved_core_slot_trial(
            "NP-001",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            manifest_path=approved.manifest_path,
            approved_request_sha256=approved_sha,
            packet_root=approved.packet_root,
            output_root=tmp_path / "runs",
        )

    assert responses.calls == []


def test_run_refuses_modified_request_bytes_before_provider(tmp_path):
    from src.extraction.run_core_slot_trial import (
        run_approved_core_slot_trial,
    )

    approved = _preflight(tmp_path)
    approved.request_path.write_bytes(
        approved.request_path.read_bytes() + b" "
    )
    responses = _FakeResponses(json.dumps(_trial_response()))

    with pytest.raises(ValueError, match="request bytes"):
        run_approved_core_slot_trial(
            "NP-001",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            manifest_path=approved.manifest_path,
            approved_request_sha256=approved.manifest["request_sha256"],
            packet_root=approved.packet_root,
            output_root=tmp_path / "runs",
        )

    assert responses.calls == []


def test_provider_failure_keeps_durable_marker_and_blocks_redispatch(
    tmp_path,
):
    from src.extraction.run_core_slot_trial import (
        run_approved_core_slot_trial,
    )

    approved = _preflight(tmp_path)
    run_root = tmp_path / "runs"
    marker_path = run_root / "NP-001" / "invocation_started.json"
    responses = _FailingResponses(
        lambda: (
            marker_path.exists()
            and json.loads(marker_path.read_text())["status"]
            == "invocation_started"
        )
        or pytest.fail("durable marker was not written before dispatch")
    )
    arguments = {
        "paper_id": "NP-001",
        "model": "gpt-5.6-terra",
        "client": SimpleNamespace(responses=responses),
        "manifest_path": approved.manifest_path,
        "approved_request_sha256": approved.manifest["request_sha256"],
        "packet_root": approved.packet_root,
        "output_root": run_root,
    }

    with pytest.raises(TimeoutError, match="outcome is unknown"):
        run_approved_core_slot_trial(**arguments)
    assert marker_path.exists()
    assert len(responses.calls) == 1

    with pytest.raises(FileExistsError, match="invocation|duplicate"):
        run_approved_core_slot_trial(**arguments)
    assert len(responses.calls) == 1


def test_run_sends_exact_request_once_and_persists_validation_artifacts(
    tmp_path,
):
    from src.extraction.run_core_slot_trial import (
        run_approved_core_slot_trial,
    )

    approved = _preflight(tmp_path)
    responses = _FakeResponses(json.dumps(_trial_response()))
    run_root = tmp_path / "runs"

    manifest = run_approved_core_slot_trial(
        "NP-001",
        model="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
        manifest_path=approved.manifest_path,
        approved_request_sha256=approved.manifest["request_sha256"],
        packet_root=approved.packet_root,
        output_root=run_root,
    )

    assert responses.calls == [
        json.loads(approved.request_path.read_bytes())
    ]
    assert manifest["paid_api_requests"] == 1
    assert manifest["repair_calls"] == 0
    assert manifest["vision_calls"] == 0
    assert manifest["usage"]["total_tokens"] == 120
    paper_root = run_root / "NP-001"
    assert (paper_root / "response.json").exists()
    assert (paper_root / "trial_response.json").exists()
    assert (paper_root / "result.json").exists()
    report = json.loads(
        (paper_root / "scientific_validation.json").read_text()
    )
    assert report["slots_sent"] == 6
    assert report["slots_accounted_for"] == 0
    assert manifest["scientifically_confirmed"] == 0

    with pytest.raises(FileExistsError, match="completed|duplicate"):
        run_approved_core_slot_trial(
            "NP-001",
            model="gpt-5.6-terra",
            client=SimpleNamespace(responses=responses),
            manifest_path=approved.manifest_path,
            approved_request_sha256=approved.manifest["request_sha256"],
            packet_root=approved.packet_root,
            output_root=run_root,
        )
    assert len(responses.calls) == 1
