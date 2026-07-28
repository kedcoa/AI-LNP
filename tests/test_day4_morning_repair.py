import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extraction.build_repair_tasks import build_task
from src.extraction.compact_validation import (
    ValidationFinding,
    ValidationReport,
    validate_candidate,
)
from src.extraction.repair_contracts import (
    RepairEvidence,
    RepairResponse,
    RepairTask,
)
from src.extraction.run_narrow_repair import run_repair
from src.rag.compact_api_packet import ApiEvidence, CompactApiPacket


def _canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _packet(evidence):
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": "GP-TEST",
        "blocked_fields": [],
        "sources": [],
        "evidence": [row.model_dump(mode="json", exclude_none=True) for row in evidence],
    }
    checksum = hashlib.sha256(_canonical_json(unsigned).encode()).hexdigest()
    return CompactApiPacket.model_validate(
        {**unsigned, "packet_checksum": checksum}
    )


def _task():
    finding = ValidationFinding(
        finding_id="VF-test",
        code="unknown_evidence_id",
        message="Unknown evidence ID",
        location=["formulations", 0, "np_ratio"],
        record_collection="formulations",
        record_index=0,
        field_name="np_ratio",
        cited_evidence_ids=["E-1"],
        repairable=True,
    )
    unsigned = {
        "task_version": "narrow-repair-task-1.0.0",
        "paper_id": "GP-TEST",
        "finding": finding.model_dump(mode="json"),
        "invalid_record": {
            "formulation_id": "F-1",
            "formulation_name": {
                "value": "LNP-1",
                "status": "reported",
                "evidence_ids": ["E-1"],
                "missing_reason": None,
            },
            "composition": {
                "value": None,
                "status": "missing",
                "evidence_ids": [],
                "missing_reason": "Not reported.",
            },
            "composition_basis": {
                "value": None,
                "status": "missing",
                "evidence_ids": [],
                "missing_reason": "Not reported.",
            },
            "np_ratio": {
                "value": 8.0,
                "status": "reported",
                "evidence_ids": ["E-1"],
                "missing_reason": None,
            },
        },
        "relevant_cited_evidence": [
            RepairEvidence(
                evidence_id="E-1", text="The N/P ratio was 8.", source_ids=["S-1"]
            ).model_dump(mode="json")
        ],
        "additional_targeted_passages": [],
        "expected_schema_fragment": {
            "field_name": "np_ratio",
            "schema": {},
            "$defs": {},
        },
        "source_candidate_sha256": "a" * 64,
    }
    checksum = hashlib.sha256(_canonical_json(unsigned).encode()).hexdigest()
    return RepairTask.model_validate({**unsigned, "task_checksum": checksum})


def test_validation_normalizes_field_level_pydantic_error():
    candidate = {
        "contract_version": "compact-1.1.0",
        "paper_id": "GP-TEST",
        "eligibility": {
            "decision": "eligible",
            "reason_codes": [
                "ORIGINAL_EXPERIMENT",
                "IDENTIFIABLE_LNP",
                "SUPPORTED_PAYLOAD",
                "TARGET_CELL_EVIDENCE",
                "USABLE_FORMULATION_OUTCOME_LINKAGE",
            ],
            "evidence_ids": ["E-1"],
            "explanation": "Eligible.",
        },
        "formulations": [
            {
                "formulation_id": "F-1",
                "formulation_name": {
                    "value": "LNP-1",
                    "status": "reported",
                    "evidence_ids": ["E-1"],
                    "missing_reason": None,
                },
                "composition": {
                    "value": None,
                    "status": "missing",
                    "evidence_ids": [],
                    "missing_reason": "Not supplied.",
                },
                "composition_basis": {
                    "value": None,
                    "status": "missing",
                    "evidence_ids": [],
                    "missing_reason": "Not supplied.",
                },
                "np_ratio": {
                    "value": "not-a-number",
                    "status": "reported",
                    "evidence_ids": ["E-1"],
                    "missing_reason": None,
                },
            }
        ],
        "components": [],
        "experiments": [],
        "outcomes": [],
        "unresolved_items": [],
    }
    parsed, report = validate_candidate(
        json.dumps(candidate),
        paper_id="GP-TEST",
        allowed_evidence_ids={"E-1"},
    )
    assert parsed is None
    field_finding = next(
        row for row in report.findings if row.field_name == "np_ratio"
    )
    assert field_finding.repairable is True
    assert field_finding.record_collection == "formulations"
    assert field_finding.cited_evidence_ids == ["E-1"]


def test_builder_limits_packet_to_cited_plus_three_targeted_passages():
    candidate = {"formulations": [_task().invalid_record]}
    report = ValidationReport(
        paper_id="GP-TEST", status="invalid", findings=[_task().finding]
    )
    evidence = [
        ApiEvidence(
            evidence_id="E-1",
            text="The N/P ratio was 8.",
            retrieval_field_tags=["np_ratio"],
            source_ids=["S-1"],
        ),
        *[
            ApiEvidence(
                evidence_id=f"E-{number}",
                text=f"Targeted N/P evidence {number}.",
                retrieval_field_tags=["np_ratio"],
                source_ids=[f"S-{number}"],
            )
            for number in range(2, 7)
        ],
        ApiEvidence(
            evidence_id="E-OTHER",
            text="Unrelated background.",
            retrieval_field_tags=["disease_model"],
            source_ids=["S-X"],
        ),
    ]
    candidate_bytes = json.dumps(candidate).encode()
    task = build_task(
        candidate=candidate,
        candidate_bytes=candidate_bytes,
        report=report,
        finding_id="VF-test",
        packet=_packet(evidence),
    )
    assert [row.evidence_id for row in task.relevant_cited_evidence] == ["E-1"]
    assert len(task.additional_targeted_passages) == 3
    assert "E-OTHER" not in {
        row.evidence_id for row in task.additional_targeted_passages
    }
    assert set(task.model_payload()) == {
        "paper_id",
        "invalid_record",
        "validation_finding",
        "relevant_cited_evidence",
        "additional_targeted_passages",
        "expected_schema_fragment",
    }


class FakeResponse:
    id = "resp_repair_test"
    model = "gpt-5.6-terra-test"
    output_text = RepairResponse(
        finding_id="VF-test",
        disposition="corrected",
        corrected_fragment={
            "np_ratio": {
                "value": 8.0,
                "status": "reported",
                "evidence_ids": ["E-1"],
                "missing_reason": None,
            }
        },
        evidence_ids=["E-1"],
        explanation="The cited passage explicitly reports the N/P ratio.",
    ).model_dump_json()
    usage = SimpleNamespace(
        model_dump=lambda mode="json": {
            "input_tokens": 200,
            "output_tokens": 40,
            "total_tokens": 240,
        }
    )

    def model_dump(self, mode="json"):
        return {"id": self.id, "model": self.model}


class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse()


def test_repair_is_one_field_and_identical_rerun_uses_local_cache(tmp_path):
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    task = _task()
    first = run_repair(
        task,
        model="gpt-5.6-terra",
        client=client,
        output_root=tmp_path,
    )
    second = run_repair(
        task,
        model="gpt-5.6-terra",
        client=client,
        output_root=tmp_path,
    )
    assert len(responses.calls) == 1
    assert first["paid_api_requests"] == 1
    assert second["cache_hit"] is True
    assert second["paid_api_requests_this_run"] == 0
    user_payload = json.loads(responses.calls[0]["input"][1]["content"])
    assert "packet" not in user_payload
    assert "outcomes" not in user_payload


def test_repair_rejects_more_than_one_corrected_field():
    response = RepairResponse(
        finding_id="VF-test",
        disposition="corrected",
        corrected_fragment={
            "np_ratio": {
                "value": 8.0,
                "status": "reported",
                "evidence_ids": ["E-1"],
                "missing_reason": None,
            },
            "composition": {
                "value": "extra change",
                "status": "reported",
                "evidence_ids": ["E-1"],
                "missing_reason": None,
            },
        },
        evidence_ids=["E-1"],
        explanation="Too broad.",
    )
    from src.extraction.run_narrow_repair import validate_response

    with pytest.raises(ValueError, match="exactly one"):
        validate_response(response, _task())


def test_repair_rejects_unknown_evidence_inside_corrected_field():
    response = RepairResponse(
        finding_id="VF-test",
        disposition="corrected",
        corrected_fragment={
            "np_ratio": {
                "value": 8.0,
                "status": "reported",
                "evidence_ids": ["E-NOT-IN-TASK"],
                "missing_reason": None,
            }
        },
        evidence_ids=["E-1"],
        explanation="Bad evidence reference.",
    )
    from src.extraction.run_narrow_repair import validate_response

    with pytest.raises(ValueError, match="unknown evidence"):
        validate_response(response, _task())
