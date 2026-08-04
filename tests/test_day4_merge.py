import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from src.extraction.compact_validation import ValidationFinding, ValidationReport
from src.extraction.merge_compact_results import merge_results
from src.extraction.repair_contracts import RepairEvidence, RepairResponse, RepairTask
from src.extraction.selective_vision_contracts import (
    SelectiveVisionResponse,
    SelectiveVisionTask,
    VisionTextEvidence,
)
from src.rag.compact_api_packet import ApiEvidence, CompactApiPacket


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _field(value, evidence="E-1"):
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": [evidence],
        "missing_reason": None,
    }


def _missing(reason="Not reported."):
    return {
        "value": None,
        "status": "missing",
        "evidence_ids": [],
        "missing_reason": reason,
    }


def _candidate():
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": "GP-MERGE",
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
                "formulation_name": _field("LNP-1"),
                "composition": _field("ionizable lipid/DSPC/cholesterol/PEG-lipid"),
                "composition_basis": _missing(),
                "np_ratio": _missing(),
            }
        ],
        "components": [],
        "experiments": [
            {
                "experiment_id": "X-1",
                "formulation_id": "F-1",
                "payload_type": _field("mRNA"),
                "payload_name": _missing(),
                "encoded_product": _missing(),
                "molecular_target": _missing(),
                "delivery_recipient_cell": _field("LSEC"),
                "therapeutic_target_cell": _missing(),
                "tissue_or_organ": _field("liver"),
                "species": _field("mouse"),
                "disease_model": _missing(),
                "experimental_context": _field("in_vivo"),
                "dose": _missing(),
                "dose_unit": _missing(),
                "route": _missing(),
                "timepoint": _missing(),
                "timepoint_unit": _missing(),
            }
        ],
        "outcomes": [
            {
                "outcome_id": "O-1",
                "experiment_id": "X-1",
                "assay": _field("insertion sequencing"),
                "endpoint": _field("total insertion frequency"),
                "comparator": _missing(),
                "outcome_value": {
                    "value": "not-a-number",
                    "status": "reported",
                    "evidence_ids": ["E-1"],
                    "missing_reason": None,
                },
                "outcome_unit": _field("percent"),
                "qualitative_outcome": _missing(),
            }
        ],
        "unresolved_items": [],
    }


def _finding():
    return ValidationFinding(
        finding_id="VF-MERGE",
        code="pydantic.float_parsing",
        message="Input should be a valid number",
        location=["outcomes", 0, "outcome_value", "value"],
        record_collection="outcomes",
        record_index=0,
        field_name="outcome_value",
        cited_evidence_ids=["E-1"],
        repairable=True,
    )


def _write_inputs(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(_candidate()) + "\n")
    report = ValidationReport(
        paper_id="GP-MERGE", status="invalid", findings=[_finding()]
    )
    report_path = tmp_path / "validation_report.json"
    report_path.write_text(report.model_dump_json())
    evidence = [
        ApiEvidence(
            evidence_id="E-1",
            text="The result is shown in Table S2.",
            retrieval_field_tags=["outcome_value"],
            source_ids=["S-1"],
        )
    ]
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": "GP-MERGE",
        "blocked_fields": [],
        "sources": [],
        "evidence": [row.model_dump(mode="json", exclude_none=True) for row in evidence],
    }
    packet = CompactApiPacket.model_validate(
        {
            **unsigned,
            "packet_checksum": hashlib.sha256(_canonical(unsigned).encode()).hexdigest(),
        }
    )
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(packet.model_dump_json())
    return candidate_path, report_path, packet_path


def _vision_pair(tmp_path, candidate_path, *, human_review=False):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (20, 20), "white").save(crop)
    crop_sha = hashlib.sha256(crop.read_bytes()).hexdigest()
    text = VisionTextEvidence(evidence_id="E-1", text="Table S2.", source_ids=["S-1"])
    unsigned = {
        "task_version": "selective-vision-task-1.0.0",
        "paper_id": "GP-MERGE",
        "experiment_id": None,
        "candidate_id": None,
        "finding": _finding().model_dump(mode="json"),
        "trigger": "unresolved_table",
        "trigger_reason": "Exact value is only in the table.",
        "source_pdf": str(tmp_path / "paper.pdf"),
        "source_pdf_sha256": "a" * 64,
        "page_number": 2,
        "figure_or_table": "Table S2",
        "crop_box": None,
        "crop_path": str(crop),
        "crop_sha256": crop_sha,
        "crop_evidence_id": f"V-{crop_sha[:16]}",
        "caption": text.model_dump(mode="json"),
        "referring_results_passages": [text.model_dump(mode="json")],
        "methods_context": [],
        "expected_schema_fragment": {},
    }
    checksum = hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
    task = SelectiveVisionTask.model_validate({**unsigned, "task_checksum": checksum})
    task_path = tmp_path / "vision_task.json"
    task_path.write_text(task.model_dump_json())
    if human_review:
        result = SelectiveVisionResponse(
            finding_id="VF-MERGE",
            disposition="human_review",
            field_name="outcome_value",
            corrected_fragment=None,
            value_status="visually_estimated",
            supporting_evidence_ids=[task.crop_evidence_id],
            figure_or_table="Table S2",
            panel_or_table_cell="LSEC row, total insertion frequency",
            visible_support="The value appears near 1%.",
            derivation=None,
            confidence="low",
            requires_human_review=True,
        )
    else:
        result = SelectiveVisionResponse(
            finding_id="VF-MERGE",
            disposition="resolved",
            field_name="outcome_value",
            corrected_fragment={
                "outcome_value": _field(1.01, task.crop_evidence_id)
            },
            value_status="exact_reported",
            supporting_evidence_ids=[task.crop_evidence_id],
            figure_or_table="Table S2",
            panel_or_table_cell="LSEC row, total insertion frequency",
            visible_support="The cell reads 1.01 ± 0.38%.",
            derivation=None,
            confidence="high",
            requires_human_review=False,
        )
    result_path = tmp_path / "vision_result.json"
    result_path.write_text(result.model_dump_json())
    return task_path, result_path


def test_exact_vision_result_merges_and_revalidates(tmp_path):
    candidate, report, packet = _write_inputs(tmp_path)
    pair = _vision_pair(tmp_path, candidate)
    merged = merge_results(
        candidate_path=candidate,
        validation_report_path=report,
        packet_path=packet,
        vision_pairs=[pair],
        output_root=tmp_path / "merged",
    )
    assert merged.status == "merged_valid"
    final = json.loads(Path(merged.final_result_path).read_text())
    assert final["outcomes"][0]["outcome_value"]["value"] == 1.01
    assert final["outcomes"][0]["outcome_value"]["evidence_ids"][0].startswith("V-")


def test_human_review_result_is_not_merged(tmp_path):
    candidate, report, packet = _write_inputs(tmp_path)
    pair = _vision_pair(tmp_path, candidate, human_review=True)
    merged = merge_results(
        candidate_path=candidate,
        validation_report_path=report,
        packet_path=packet,
        vision_pairs=[pair],
        output_root=tmp_path / "merged",
    )
    assert merged.status == "unresolved"
    assert merged.unresolved_finding_ids == ["VF-MERGE"]
    assert merged.final_result_path is None


def test_complex_unmatched_outcome_coverage_blocks_merge(tmp_path):
    candidate, report, packet_path = _write_inputs(tmp_path)
    packet = json.loads(packet_path.read_text())
    for number in range(8):
        packet["evidence"].append(
            {
                "evidence_id": f"E-EXTRA-{number}",
                "text": (
                    f"After LNP treatment, over {70 + number}% of liver "
                    f"macrophages expressed GFP endpoint {number}."
                ),
                "retrieval_field_tags": ["outcomes"],
                "experiment_candidate_ids": [],
                "source_ids": ["S-1"],
            }
        )
    parsed_packet = CompactApiPacket.model_validate(packet)
    unsigned = parsed_packet.model_dump(
        mode="json", exclude={"packet_checksum"}, exclude_none=True
    )
    packet = unsigned.copy()
    packet["packet_checksum"] = hashlib.sha256(
        _canonical(unsigned).encode()
    ).hexdigest()
    packet_path.write_text(json.dumps(packet))
    pair = _vision_pair(tmp_path, candidate)
    merged = merge_results(
        candidate_path=candidate,
        validation_report_path=report,
        packet_path=packet_path,
        vision_pairs=[pair],
        output_root=tmp_path / "merged",
    )
    assert merged.status == "unresolved"
    assert merged.outcome_coverage_status == "review_unmatched_groups"
    assert merged.unresolved_outcome_candidate_ids
    assert merged.final_result_path is None


def test_repair_task_from_different_candidate_is_rejected(tmp_path):
    candidate, report, packet = _write_inputs(tmp_path)
    evidence = RepairEvidence(evidence_id="E-1", text="Value 1.01.", source_ids=["S-1"])
    unsigned = {
        "task_version": "narrow-repair-task-1.0.0",
        "paper_id": "GP-MERGE",
        "finding": _finding().model_dump(mode="json"),
        "invalid_record": _candidate()["outcomes"][0],
        "relevant_cited_evidence": [evidence.model_dump(mode="json")],
        "additional_targeted_passages": [],
        "expected_schema_fragment": {},
        "source_candidate_sha256": "0" * 64,
    }
    checksum = hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
    task = RepairTask.model_validate({**unsigned, "task_checksum": checksum})
    task_path = tmp_path / "repair_task.json"
    task_path.write_text(task.model_dump_json())
    result = RepairResponse(
        finding_id="VF-MERGE",
        disposition="corrected",
        corrected_fragment={"outcome_value": _field(1.01)},
        evidence_ids=["E-1"],
        explanation="Corrected.",
    )
    result_path = tmp_path / "repair_result.json"
    result_path.write_text(result.model_dump_json())
    with pytest.raises(ValueError, match="different candidate"):
        merge_results(
            candidate_path=candidate,
            validation_report_path=report,
            packet_path=packet,
            repair_pairs=[(task_path, result_path)],
            output_root=tmp_path / "merged",
        )
