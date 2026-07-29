from src.extraction.benchmark_v12_gemma_visual import (
    audit_decision,
    compact_docling_context,
)
from src.extraction.v12_visual_contracts import (
    DoclingVisualObjectV12,
    GemmaVisualDecisionV12,
)


def parsed_table():
    return DoclingVisualObjectV12.model_validate({
        "object_id": "O1",
        "paper_id": "GP-X",
        "source_file": "supp.pdf",
        "original_page": 2,
        "figure_or_table": "Table S2",
        "inventory_object_type": "table",
        "caption": "Insertion frequency",
        "source_crop": "crop.png",
        "source_crop_sha256": "abc",
        "parser_version": "test",
        "parser_config": {},
        "parse_seconds": 0.1,
        "parse_status": "parsed",
        "text_items": [],
        "tables": [{
            "table_index": 0,
            "rows": 2,
            "columns": 2,
            "grid": [
                ["", "total insertion frequency"],
                ["LSEC", "1.01 ± 0.38 %"],
            ],
            "cells": [],
        }],
        "picture_count": 0,
        "warnings": [],
    })


def test_compact_context_keeps_table_relationship():
    context = compact_docling_context(
        parsed_table(), "total insertion frequency for LSEC"
    )
    assert context["docling_tables"][0]["grid"][1][1] == "1.01 ± 0.38 %"


def test_audit_rejects_wrong_numeric_value():
    decision = GemmaVisualDecisionV12.model_validate({
        "object_id": "O1",
        "query_id": "Q1",
        "status": "extract",
        "claims": [{
            "claim_id": "C1",
            "subject": "LSEC",
            "predicate": "had",
            "endpoint": "total insertion frequency",
            "result_type": "exact_numeric",
            "value": "9.99",
            "unit": "%",
            "intervention_context": "LNP",
            "panel_or_cell": "LSEC × total insertion frequency",
            "visible_support": [
                "LSEC | total insertion frequency | 9.99 %"
            ],
            "evidence_kinds": ["docling_table_cell"],
            "confidence": "high",
        }],
        "abstention_reason": None,
        "missing_requirements": [],
    })
    case = {
        "query_id": "Q1",
        "query": "total insertion frequency for LSEC",
        "expected_status": "extract",
        "required_claim_terms": [],
        "forbidden_claim_terms": [],
    }
    assert "C1: exact value absent from Docling evidence" in audit_decision(
        case, parsed_table(), decision
    )
