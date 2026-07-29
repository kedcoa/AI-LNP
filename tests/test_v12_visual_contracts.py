import pytest
from pydantic import ValidationError

from src.extraction.benchmark_v12_gemma_visual import audit_decision
from src.extraction.v12_visual_contracts import (
    DoclingVisualObjectV12,
    GemmaVisualDecisionV12,
)


def test_abstention_cannot_smuggle_claims():
    with pytest.raises(ValidationError):
        GemmaVisualDecisionV12.model_validate({
            "object_id": "O1",
            "query_id": "Q1",
            "status": "abstain",
            "claims": [{
                "claim_id": "C1",
                "subject": "LSEC",
                "predicate": "measured",
                "endpoint": "insertion",
                "result_type": "exact_numeric",
                "value": "1.01",
                "unit": "%",
                "intervention_context": "LNP",
                "panel_or_cell": "Table S2",
                "visible_support": ["LSEC | total | 1.01"],
                "evidence_kinds": ["docling_table_cell"],
                "confidence": "high",
            }],
            "abstention_reason": "target_not_visible",
            "missing_requirements": [],
        })


def test_extract_requires_a_claim():
    with pytest.raises(ValidationError):
        GemmaVisualDecisionV12.model_validate({
            "object_id": "O1",
            "query_id": "Q1",
            "status": "extract",
            "claims": [],
            "abstention_reason": None,
            "missing_requirements": [],
        })


def test_visual_audit_rejects_reversed_go018_relationship():
    parsed = DoclingVisualObjectV12.model_validate({
        "object_id": "O1",
        "paper_id": "GP-008",
        "source_file": "figure.pdf",
        "original_page": 19,
        "figure_or_table": "Appendix Figure 5",
        "inventory_object_type": "figure",
        "caption": "ZsGreen marker comparison",
        "source_crop": "figure.png",
        "source_crop_sha256": "abc",
        "parser_version": "test",
        "parser_config": {},
        "parse_seconds": 0,
        "parse_status": "parsed",
        "text_items": [],
        "tables": [],
        "picture_count": 1,
        "warnings": [],
    })
    decision = GemmaVisualDecisionV12.model_validate({
        "object_id": "O1",
        "query_id": "GO-018-positive",
        "status": "extract",
        "claims": [{
            "claim_id": "C1",
            "subject": "ZsGreen",
            "predicate": "localized to",
            "endpoint": "recipient-cell localization",
            "result_type": "qualitative",
            "value": "Desmin-positive HSCs rather than F4/80-positive macrophages",
            "unit": None,
            "intervention_context": "LNP",
            "panel_or_cell": "K-L",
            "visible_support": ["ZsGreen, Desmin, F4/80 macrophage"],
            "evidence_kinds": ["image"],
            "confidence": "high",
        }],
        "abstention_reason": None,
        "missing_requirements": [],
    })
    case = {
        "query_id": "GO-018-positive",
        "expected_status": "extract",
        "query": (
            "Determine ZsGreen localization to macrophages rather than "
            "Desmin-positive HSCs."
        ),
        "required_claim_terms": ["ZsGreen", "macrophage", "Desmin"],
        "required_value_patterns": [
            (
                "(?:macrophage|F4/80).{0,80}"
                "(?:rather than|over|preferential|predominant|enrich|higher)"
                ".{0,80}(?:Desmin|HSC)"
            )
        ],
        "forbidden_claim_terms": [],
    }
    assert any(
        issue.startswith("required claim-value relationship missing:")
        for issue in audit_decision(case, parsed, decision)
    )


def test_qualitative_claim_cannot_include_estimated_bar_value():
    with pytest.raises(ValidationError, match="numeric estimates"):
        GemmaVisualDecisionV12.model_validate({
            "object_id": "O1",
            "query_id": "Q1",
            "status": "extract",
            "claims": [{
                "claim_id": "C1",
                "subject": "ZsGreen",
                "predicate": "higher in",
                "endpoint": "recipient-cell localization",
                "result_type": "qualitative",
                "value": "higher in macrophages",
                "unit": None,
                "intervention_context": "LNP",
                "panel_or_cell": "K-L",
                "visible_support": ["F4/80 bar is approximately 50%"],
                "evidence_kinds": ["image"],
                "confidence": "high",
            }],
            "abstention_reason": None,
            "missing_requirements": [],
        })
