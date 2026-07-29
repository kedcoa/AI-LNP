from src.extraction.evaluate_v12_combined_recall import match_go006
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


def candidate(value=1.01, endpoint="total insertion frequency"):
    return AtomicOutcomeCandidateV12.model_validate({
        "candidate_id": "AOC-VIS-test",
        "paper_id": "GP-006",
        "claim_ids": ["ACL-VIS-test"],
        "provisional_experiment_id": "PEX-GP-006-test",
        "subject_text": "LSEC",
        "predicate": "reached",
        "endpoint_text": endpoint,
        "numeric_value": value,
        "value_text": f"{value} ± 0.38 %",
        "unit": "%",
        "polarity": "neutral",
        "evidence_ids": ["VIS-test"],
        "source_ids": ["O1:r2:c6"],
        "route_hint": "vision",
        "confidence": "high",
        "review_reasons": [],
        "structural_signature": "test",
    })


def test_go006_match_requires_subject_endpoint_value_and_uncertainty():
    assert match_go006([candidate()]) is not None
    assert match_go006([candidate(value=1.02)]) is None
    assert match_go006([candidate(endpoint="total deletion frequency")]) is None
