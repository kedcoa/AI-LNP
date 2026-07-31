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


def _write_np002_packet(root: Path) -> None:
    texts = [
        ("E-ROUTE", "Mice were injected intravenously via the lateral tail vein."),
        (
            "E-QUANT-BOUND",
            "We injected mice intravenously with 0.3 mg/kg QUANT DNA carried "
            "by either MC3 or cKK-E12 LNPs and measured biodistribution to "
            "Kupffer cells.",
        ),
        (
            "E-QUANT-OUT",
            "Both cKK-E12 and MC3 distributed to Kupffer cells.",
        ),
        (
            "E-CRE-MODEL",
            "We utilized Ai14 Cre-reporter mice in these experiments.",
        ),
        (
            "E-CRE-1",
            "We administered Cre mRNA at 1.0 mg/kg using cKK-E12 and MC3.",
        ),
        (
            "E-CRE-TARGET",
            "We quantified the percentage of Kupffer cells that were "
            "tdTomato positive.",
        ),
        (
            "E-CRE-03-COND",
            "We repeated the Cre mRNA experiment at 0.3 mg/kg using both "
            "cKK-E12 and MC3 and observed tdTomato positive cells.",
        ),
    ]
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": "NP-002",
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
            "packet_checksum": hashlib.sha256(
                _canonical_json(unsigned).encode("utf-8")
            ).hexdigest(),
        }
    )
    root.mkdir(parents=True)
    (root / "NP-002.json").write_text(
        packet.model_dump_json(),
        encoding="utf-8",
    )


class ExplodingClient:
    @property
    def responses(self):
        raise AssertionError("provider client must not be touched")


def _sign_review(review):
    unsigned = {
        key: value for key, value in review.items() if key != "review_sha256"
    }
    return {
        **unsigned,
        "review_sha256": hashlib.sha256(
            _canonical_json(unsigned).encode("utf-8")
        ).hexdigest(),
    }


def _approved_review(review_path: Path) -> dict:
    review = json.loads(review_path.read_text())
    for row in review["decisions"]:
        row["decision"] = "accept"
        row["reason"] = "Direct packet evidence supports this arm."
    approved = _sign_review(review)
    review_path.write_text(json.dumps(approved), encoding="utf-8")
    return approved


def _prepared_review(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        prepare_arm_review,
    )

    packet_root = tmp_path / "packets"
    review_root = tmp_path / "review"
    _write_np002_packet(packet_root)
    report = prepare_arm_review(
        "NP-002",
        packet_root=packet_root,
        output_root=review_root,
    )
    review_path = Path(report["review_path"])
    return packet_root, review_path, _approved_review(review_path)


def _preflight(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        preflight_kupffer_benchmark,
    )

    packet_root, review_path, _ = _prepared_review(tmp_path)
    output_root = tmp_path / "preflight"
    manifest = preflight_kupffer_benchmark(
        "NP-002",
        model="gpt-test",
        review_path=review_path,
        packet_root=packet_root,
        output_root=output_root,
    )
    return SimpleNamespace(
        manifest=manifest,
        manifest_path=output_root / "NP-002" / "manifest.json",
        request_path=output_root / "NP-002" / "request.json",
    )


def _compact_arm_response(request):
    payload = json.loads(request["input"][1]["content"])
    accounting = {}
    for packet in payload["experimental_arm_packets"]:
        arm = packet["arm"]
        accounting[arm["candidate_id"]] = {
            "disposition": "ambiguous",
            "linked_experiment_ids": [],
            "linked_outcome_ids": [],
            "evidence_ids": [packet["evidence"][0]["evidence_id"]],
            "reason_code": "candidate_not_grounded",
            "explanation": "The benchmark returned a conservative ambiguity.",
        }
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": "NP-002",
        "eligibility": {
            "decision": "uncertain",
            "reason_codes": ["FULL_TEXT_REQUIRED"],
            "evidence_ids": [],
            "explanation": "No arm was structurally linked.",
        },
        "formulations": [],
        "components": [],
        "experiments": [],
        "outcomes": [],
        "unresolved_items": [],
        "experimental_arm_accounting": accounting,
    }


def _reported_value(value, evidence_id):
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": [evidence_id],
        "missing_reason": None,
    }


def _wrong_arm_evidence_response(request):
    response = _compact_arm_response(request)
    wrong_evidence_id = "E-CRE-03-COND"

    def value(item):
        return _reported_value(item, wrong_evidence_id)

    response["eligibility"] = {
        "decision": "eligible",
        "reason_codes": [
            "ORIGINAL_EXPERIMENT",
            "IDENTIFIABLE_LNP",
            "SUPPORTED_PAYLOAD",
            "TARGET_CELL_EVIDENCE",
            "USABLE_FORMULATION_OUTCOME_LINKAGE",
        ],
        "evidence_ids": [wrong_evidence_id],
        "explanation": "A deliberately cross-arm evidence test.",
    }
    response["formulations"] = [
        {
            "formulation_id": "F-MC3",
            "formulation_name": value("MC3"),
            "composition": value("lipids"),
            "composition_basis": value("reported"),
            "np_ratio": value(6.0),
        }
    ]
    response["experiments"] = [
        {
            "experiment_id": "EXP-KUP-01",
            "formulation_id": "F-MC3",
            "payload_type": value("DNA"),
            "payload_name": value("QUANT DNA"),
            "encoded_product": value("QUANT"),
            "molecular_target": value("Kupffer cells"),
            "delivery_recipient_cell": value("Kupffer cells"),
            "therapeutic_target_cell": value("Kupffer cells"),
            "tissue_or_organ": value("liver"),
            "species": value("Mus musculus"),
            "disease_model": value("mice"),
            "experimental_context": value("in_vivo"),
            "dose": value(0.3),
            "dose_unit": value("mg/kg"),
            "route": value("IV"),
            "timepoint": value(6.0),
            "timepoint_unit": value("hours"),
        }
    ]
    response["outcomes"] = [
        {
            "outcome_id": "OUT-KUP-01",
            "experiment_id": "EXP-KUP-01",
            "assay": value("ddPCR"),
            "endpoint": value("QUANT copies"),
            "comparator": value("control"),
            "outcome_value": value(1.0),
            "outcome_unit": value("percent"),
            "qualitative_outcome": value("reported Kupffer-cell result"),
        }
    ]
    response["experimental_arm_accounting"]["KUP-01"] = {
        "disposition": "extracted",
        "linked_experiment_ids": ["EXP-KUP-01"],
        "linked_outcome_ids": ["OUT-KUP-01"],
        "evidence_ids": [wrong_evidence_id],
        "reason_code": "extracted",
        "explanation": "The records match but cite another arm's evidence.",
    }
    return response


class _FakeResponse:
    id = "resp-kupffer"
    model = "gpt-test-returned"
    output = []

    def __init__(self, output_text):
        self.output_text = output_text
        self.usage = SimpleNamespace(
            model_dump=lambda mode="json": {
                "input_tokens": 500,
                "output_tokens": 100,
                "total_tokens": 600,
            }
        )

    def model_dump(self, mode="json"):
        return {"id": self.id, "model": self.model}


class _FakeResponses:
    def __init__(self, *, marker_path=None, response_builder=None):
        self.calls = []
        self.marker_path = marker_path
        self.response_builder = response_builder or _compact_arm_response

    def create(self, **request):
        if self.marker_path is not None:
            assert self.marker_path.is_file()
            assert json.loads(self.marker_path.read_text())["status"] == (
                "invocation_started"
            )
        self.calls.append(request)
        return _FakeResponse(json.dumps(self.response_builder(request)))


class _FailingResponses:
    def __init__(self, marker_path):
        self.calls = []
        self.marker_path = marker_path

    def create(self, **request):
        assert self.marker_path.is_file()
        self.calls.append(request)
        raise TimeoutError("provider outcome is unknown")


def test_prepare_review_is_local_pending_and_evidence_readable(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        prepare_arm_review,
    )

    packet_root = tmp_path / "packets"
    output_root = tmp_path / "review"
    _write_np002_packet(packet_root)

    report = prepare_arm_review(
        "NP-002",
        packet_root=packet_root,
        output_root=output_root,
    )

    proposal = json.loads(
        (output_root / "NP-002" / "proposal.json").read_text()
    )
    review = json.loads(
        (output_root / "NP-002" / "review_template.json").read_text()
    )
    markdown = (
        output_root / "NP-002" / "experimental_arms_review.md"
    ).read_text()
    assert report["provider_calls"] == 0
    assert len(proposal["proposed_arms"]) == 6
    assert all(row["decision"] == "pending" for row in review["decisions"])
    evidence_text = {
        row["evidence_id"]: row["text"]
        for row in proposal["packet_evidence"]
    }
    for arm in proposal["proposed_arms"]:
        for evidence_id in (
            arm["existence_evidence_ids"] + arm["outcome_evidence_ids"]
        ):
            assert evidence_text[evidence_id] in markdown


def test_prepare_review_rejects_any_paper_other_than_np002(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        prepare_arm_review,
    )

    with pytest.raises(ValueError, match="NP-002"):
        prepare_arm_review(
            "NP-001",
            packet_root=tmp_path / "packets",
            output_root=tmp_path / "review",
        )


def test_preflight_persists_one_exact_six_arm_request(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        preflight_kupffer_benchmark,
    )

    packet_root, review_path, _ = _prepared_review(tmp_path)
    output_root = tmp_path / "preflight"
    manifest = preflight_kupffer_benchmark(
        "NP-002",
        model="gpt-test",
        review_path=review_path,
        packet_root=packet_root,
        output_root=output_root,
    )

    request_path = Path(manifest["request_path"])
    request_bytes = request_path.read_bytes()
    request = json.loads(request_bytes)
    payload = json.loads(request["input"][1]["content"])
    schema = request["text"]["format"]["schema"]
    accounting = schema["properties"]["experimental_arm_accounting"]
    assert len(payload["experimental_arm_packets"]) == 6
    assert set(accounting["required"]) == {
        f"KUP-{number:02d}" for number in range(1, 7)
    }
    dispositions = {
        row["properties"]["disposition"]["const"]
        for row in schema["$defs"]["ExperimentalArmAccountingEntry"]["oneOf"]
    }
    assert dispositions == {"extracted", "ambiguous"}
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] == 12_000
    assert "independently interpreted" in request["input"][0]["content"]
    assert "incompatible dose/payload arms" in request["input"][0]["content"]
    assert manifest["provider_calls"] == 0
    assert manifest["proposed_calls"] == 1
    assert manifest["model"] == "gpt-test"
    assert manifest["request_sha256"] == hashlib.sha256(
        request_bytes
    ).hexdigest()
    assert manifest["request_bytes"] == len(request_bytes)
    assert manifest["estimated_input_tokens"] > 0
    assert manifest["max_output_tokens"] == 12_000
    assert manifest["packet_checksum"]
    assert Path(manifest["preview_path"]).is_file()
    assert (output_root / "NP-002" / "manifest.json").is_file()


@pytest.mark.parametrize("bad_decision", ["pending", "invalid"])
def test_preflight_rejects_unapproved_review_decisions(
    tmp_path,
    bad_decision,
):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        preflight_kupffer_benchmark,
    )

    packet_root, review_path, review = _prepared_review(tmp_path)
    review["decisions"][0]["decision"] = bad_decision
    review_path.write_text(json.dumps(_sign_review(review)), encoding="utf-8")
    with pytest.raises(ValueError, match="decision"):
        preflight_kupffer_benchmark(
            "NP-002",
            model="gpt-test",
            review_path=review_path,
            packet_root=packet_root,
            output_root=tmp_path / "preflight",
        )


def test_preflight_rejects_review_sha_mismatch(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        preflight_kupffer_benchmark,
    )

    packet_root, review_path, review = _prepared_review(tmp_path)
    review["decisions"][0]["reason"] = "Modified after signing."
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="review SHA-256"):
        preflight_kupffer_benchmark(
            "NP-002",
            model="gpt-test",
            review_path=review_path,
            packet_root=packet_root,
            output_root=tmp_path / "preflight",
        )


def test_preflight_requires_exactly_six_approved_arms(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        preflight_kupffer_benchmark,
    )

    packet_root, review_path, review = _prepared_review(tmp_path)
    review["decisions"][0] = {
        "candidate_id": "KUP-01",
        "decision": "remove",
        "reason": "Human reviewer excluded this arm.",
    }
    review_path.write_text(json.dumps(_sign_review(review)), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly six"):
        preflight_kupffer_benchmark(
            "NP-002",
            model="gpt-test",
            review_path=review_path,
            packet_root=packet_root,
            output_root=tmp_path / "preflight",
        )


def test_preflight_rejects_modified_proposal_and_wrong_paper(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        preflight_kupffer_benchmark,
    )

    packet_root, review_path, _ = _prepared_review(tmp_path)
    proposal_path = review_path.with_name("proposal.json")
    proposal = json.loads(proposal_path.read_text())
    proposal["proposed_arms"][0]["dose"] = 99
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    with pytest.raises(ValueError, match="proposal was modified"):
        preflight_kupffer_benchmark(
            "NP-002",
            model="gpt-test",
            review_path=review_path,
            packet_root=packet_root,
            output_root=tmp_path / "preflight",
        )
    with pytest.raises(ValueError, match="NP-002"):
        preflight_kupffer_benchmark(
            "NP-001",
            model="gpt-test",
            review_path=review_path,
            packet_root=packet_root,
            output_root=tmp_path / "preflight",
        )


def test_preflight_rejects_rechecksummed_packet_changed_after_review(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        preflight_kupffer_benchmark,
    )

    packet_root, review_path, _ = _prepared_review(tmp_path)
    packet_path = packet_root / "NP-002.json"
    packet = json.loads(packet_path.read_text())
    packet["evidence"][0]["text"] += " Changed after human review."
    unsigned = CompactApiPacket.model_validate(
        {**packet, "packet_checksum": "recomputed"}
    ).model_dump(
        mode="json",
        exclude={"packet_checksum"},
        exclude_none=True,
    )
    packet["packet_checksum"] = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(ValueError, match="packet|proposal"):
        preflight_kupffer_benchmark(
            "NP-002",
            model="gpt-test",
            review_path=review_path,
            packet_root=packet_root,
            output_root=tmp_path / "preflight",
        )
    assert not (tmp_path / "preflight" / "NP-002").exists()


@pytest.mark.parametrize("approval_sha256", ["", "0" * 64])
def test_run_refuses_missing_or_wrong_approval_without_a_call(
    tmp_path,
    approval_sha256,
):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        run_approved_kupffer_benchmark,
    )

    approved = _preflight(tmp_path)
    responses = _FakeResponses()
    with pytest.raises((PermissionError, ValueError), match="approval|SHA"):
        run_approved_kupffer_benchmark(
            manifest_path=approved.manifest_path,
            approval_sha256=approval_sha256,
            output_root=tmp_path / "runs",
            client=SimpleNamespace(responses=responses),
        )
    assert responses.calls == []


def test_run_refuses_modified_request_bytes_without_a_call(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        run_approved_kupffer_benchmark,
    )

    approved = _preflight(tmp_path)
    approved.request_path.write_bytes(approved.request_path.read_bytes() + b" ")
    responses = _FakeResponses()
    with pytest.raises(ValueError, match="request bytes"):
        run_approved_kupffer_benchmark(
            manifest_path=approved.manifest_path,
            approval_sha256=approved.manifest["request_sha256"],
            output_root=tmp_path / "runs",
            client=SimpleNamespace(responses=responses),
        )
    assert responses.calls == []


def test_one_call_marker_duplicate_guard_and_complete_artifacts(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        run_approved_kupffer_benchmark,
    )

    approved = _preflight(tmp_path)
    run_root = tmp_path / "runs"
    run_dir = run_root / "NP-002"
    marker_path = run_dir / "invocation_started.json"
    responses = _FakeResponses(marker_path=marker_path)
    args = {
        "manifest_path": approved.manifest_path,
        "approval_sha256": approved.manifest["request_sha256"],
        "output_root": run_root,
        "client": SimpleNamespace(responses=responses),
    }
    manifest = run_approved_kupffer_benchmark(**args)

    assert len(responses.calls) == 1
    assert responses.calls[0] == json.loads(approved.request_path.read_bytes())
    assert manifest["paid_api_requests"] == 1
    assert manifest["repair_calls"] == 0
    assert manifest["vision_calls"] == 0
    assert manifest["request_sha256"] == approved.manifest["request_sha256"]
    assert manifest["response_sha256"]
    assert manifest["result_sha256"]
    assert manifest["validation_sha256"]
    for name in (
        "response.json",
        "trial_response.json",
        "result.json",
        "scientific_validation.json",
        "usage.json",
        "manifest.json",
    ):
        assert (run_dir / name).is_file()
    validation = json.loads(
        (run_dir / "scientific_validation.json").read_text()
    )
    assert validation["ambiguous"] == 6
    with pytest.raises(FileExistsError, match="invocation|duplicate"):
        run_approved_kupffer_benchmark(**args)
    assert len(responses.calls) == 1


def test_request_is_rechecked_immediately_before_dispatch(
    tmp_path,
    monkeypatch,
):
    from src.extraction import run_np002_kupffer_arm_benchmark as benchmark

    approved = _preflight(tmp_path)
    responses = _FakeResponses()
    original_read_bytes = Path.read_bytes
    request_reads = 0

    def mutate_second_request_read(path):
        nonlocal request_reads
        value = original_read_bytes(path)
        if path == approved.request_path:
            request_reads += 1
            if request_reads == 2:
                return value + b" "
        return value

    monkeypatch.setattr(Path, "read_bytes", mutate_second_request_read)
    with pytest.raises(ValueError, match="changed before dispatch"):
        benchmark.run_approved_kupffer_benchmark(
            manifest_path=approved.manifest_path,
            approval_sha256=approved.manifest["request_sha256"],
            output_root=tmp_path / "runs",
            client=SimpleNamespace(responses=responses),
        )
    assert responses.calls == []


def test_provider_failure_leaves_marker_and_blocks_redispatch(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        run_approved_kupffer_benchmark,
    )

    approved = _preflight(tmp_path)
    run_root = tmp_path / "runs"
    marker = run_root / "NP-002" / "invocation_started.json"
    responses = _FailingResponses(marker)
    args = {
        "manifest_path": approved.manifest_path,
        "approval_sha256": approved.manifest["request_sha256"],
        "output_root": run_root,
        "client": SimpleNamespace(responses=responses),
    }
    with pytest.raises(TimeoutError, match="outcome is unknown"):
        run_approved_kupffer_benchmark(**args)
    assert marker.is_file()
    with pytest.raises(FileExistsError, match="invocation|duplicate"):
        run_approved_kupffer_benchmark(**args)
    assert len(responses.calls) == 1


def test_validation_cannot_confirm_arm_with_another_arms_evidence(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        run_approved_kupffer_benchmark,
    )

    approved = _preflight(tmp_path)
    responses = _FakeResponses(response_builder=_wrong_arm_evidence_response)
    manifest = run_approved_kupffer_benchmark(
        manifest_path=approved.manifest_path,
        approval_sha256=approved.manifest["request_sha256"],
        output_root=tmp_path / "runs",
        client=SimpleNamespace(responses=responses),
    )
    validation = json.loads(
        (
            tmp_path
            / "runs"
            / "NP-002"
            / "scientific_validation.json"
        ).read_text()
    )
    assert "KUP-01" not in validation["confirmed_candidate_ids"]
    assert validation["scientifically_confirmed"] == 0
    assert manifest["scientifically_confirmed"] == 0
    assert any(
        row["code"] == "candidate_evidence_outside_arm_envelope"
        and row["candidate_id"] == "KUP-01"
        for row in validation["errors"]
    )
    assert len(responses.calls) == 1


def test_run_rejects_response_for_another_paper_before_completion(tmp_path):
    from src.extraction.run_np002_kupffer_arm_benchmark import (
        run_approved_kupffer_benchmark,
    )

    approved = _preflight(tmp_path)

    def wrong_paper(request):
        response = _compact_arm_response(request)
        response["paper_id"] = "NP-001"
        return response

    responses = _FakeResponses(response_builder=wrong_paper)
    run_dir = tmp_path / "runs" / "NP-002"
    with pytest.raises(ValueError, match="paper_id.*NP-002"):
        run_approved_kupffer_benchmark(
            manifest_path=approved.manifest_path,
            approval_sha256=approved.manifest["request_sha256"],
            output_root=tmp_path / "runs",
            client=SimpleNamespace(responses=responses),
        )
    assert len(responses.calls) == 1
    assert (run_dir / "invocation_started.json").is_file()
    assert not (run_dir / "response.json").exists()
    assert not (run_dir / "result.json").exists()
    assert not (run_dir / "scientific_validation.json").exists()
    assert not (run_dir / "manifest.json").exists()


def test_default_client_disables_retries(tmp_path, monkeypatch):
    from src.extraction import run_np002_kupffer_arm_benchmark as benchmark

    approved = _preflight(tmp_path)
    observed = {}
    responses = _FakeResponses()

    def fake_openai(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(responses=responses)

    monkeypatch.setattr(benchmark, "OpenAI", fake_openai)
    benchmark.run_approved_kupffer_benchmark(
        manifest_path=approved.manifest_path,
        approval_sha256=approved.manifest["request_sha256"],
        output_root=tmp_path / "runs",
    )
    assert observed["max_retries"] == 0
    assert len(responses.calls) == 1
