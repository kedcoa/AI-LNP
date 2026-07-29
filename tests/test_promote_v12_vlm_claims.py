import json

import pytest

from src.extraction.promote_v12_vlm_claims import promote


def decision(query_id, result_type="qualitative"):
    claim = {
        "claim_id": "C1",
        "subject": "ZsGreen",
        "predicate": "localized to",
        "endpoint": "recipient-cell localization",
        "result_type": result_type,
        "value": (
            "macrophages rather than Desmin-positive HSCs"
            if result_type == "qualitative"
            else "1.01"
        ),
        "unit": "%" if result_type == "exact_numeric" else None,
        "intervention_context": "LNP",
        "panel_or_cell": "K-L",
        "visible_support": ["ZsGreen | F4/80 | Desmin"],
        "evidence_kinds": (
            ["image"]
            if result_type == "qualitative"
            else ["docling_table_cell"]
        ),
        "confidence": "high",
    }
    return {
        "contract_version": "1.0.0",
        "object_id": "OBJ-1",
        "query_id": query_id,
        "status": "extract",
        "claims": [claim],
        "abstention_reason": None,
        "missing_requirements": [],
    }


def test_promote_requires_full_benchmark_gate(tmp_path):
    report = tmp_path / "evaluation.json"
    report.write_text(json.dumps({
        "model": "qwen3-vl:8b",
        "integration_gate_passed": False,
    }))
    with pytest.raises(ValueError, match="gate failed"):
        promote(
            "qwen3-vl:8b",
            report_path=report,
            benchmark_output=tmp_path / "runs",
            registry_root=tmp_path / "registry",
        )


def test_promote_strips_query_ids_and_skips_numeric_table_claims(tmp_path):
    runs = tmp_path / "runs"
    for query_id, result_type in (
        ("positive-figure", "qualitative"),
        ("positive-table", "exact_numeric"),
    ):
        case = runs / query_id
        case.mkdir(parents=True)
        (case / "repeat-01.decision.json").write_text(
            json.dumps(decision(query_id, result_type))
        )
    report = tmp_path / "evaluation.json"
    report.write_text(json.dumps({
        "model": "qwen3-vl:8b",
        "model_digest": "abc",
        "integration_gate_passed": True,
        "integration_gate_requirements": {
            "full_fixture_coverage": True,
            "minimum_repeats_met": True,
            "every_run_passed": True,
        },
        "runs": [
            {
                "query_id": "positive-figure",
                "repeat": 1,
                "passed": True,
                "expected_status": "extract",
                "image_path": "figure.png",
            },
            {
                "query_id": "positive-table",
                "repeat": 1,
                "passed": True,
                "expected_status": "extract",
                "image_path": "table.png",
            },
        ],
    }))
    registry = promote(
        "qwen3-vl:8b",
        report_path=report,
        benchmark_output=runs,
        registry_root=tmp_path / "registry",
    )
    assert len(registry["claims"]) == 1
    assert registry["claims"][0]["claim"]["result_type"] == "qualitative"
    assert all("query_id" not in row for row in registry["claims"])
    serialized = json.dumps(registry["claims"])
    assert "gold_outcome_id" not in serialized
    assert "GO-" not in serialized
    assert registry["claims"][0]["claim"]["claim_id"].startswith("VCL-")
