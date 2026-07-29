from src.extraction.check_v12_visual_regressions import evaluate
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


def go006_candidate():
    return AtomicOutcomeCandidateV12.model_validate({
        "candidate_id": "AOC-VIS-test",
        "paper_id": "GP-006",
        "claim_ids": ["ACL-VIS-test"],
        "provisional_experiment_id": "PEX-GP-006-test",
        "subject_text": "LSEC",
        "predicate": "reached",
        "endpoint_text": "total insertion frequency",
        "numeric_value": 1.01,
        "value_text": "1.01 ± 0.38 %",
        "unit": "%",
        "polarity": "neutral",
        "evidence_ids": ["VIS-test"],
        "source_ids": ["O1:r2:c6"],
        "route_hint": "vision",
        "confidence": "high",
        "review_reasons": [],
        "structural_signature": "test",
    })


def fixture():
    return {
        "cases": [
            {"query_id": "GO-006-positive", "expected_status": "extract"},
            {"query_id": "GO-018-positive", "expected_status": "extract"},
            {
                "query_id": "GO-006-adversarial-abstain",
                "expected_status": "abstain",
            },
            {
                "query_id": "GO-018-adversarial-abstain",
                "expected_status": "abstain",
            },
        ]
    }


def test_gate_requires_positive_and_abstention_cases():
    report = {"runs": [
        {"query_id": "GO-018-positive", "passed": True, "audit_issues": []},
        {
            "query_id": "GO-006-adversarial-abstain",
            "passed": True,
            "audit_issues": [],
        },
        {
            "query_id": "GO-018-adversarial-abstain",
            "passed": False,
            "audit_issues": ["did not abstain"],
        },
    ]}
    result = evaluate(fixture(), [go006_candidate()], report)
    assert result["passed"] is False
    assert result["checks"][0]["passed"] is True
    assert result["checks"][-1]["passed"] is False
