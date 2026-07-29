from src.extraction.check_atomic_coverage_v12 import (
    _bounded_actionable,
    match_score,
)
from src.extraction.select_atomic_candidates_v12 import relevance_score
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


def candidate(**changes):
    values = {
        "candidate_id": "AOC-1",
        "paper_id": "GP-X",
        "claim_ids": ["ACL-1"],
        "provisional_experiment_id": "PEX-1",
        "subject_text": "F4/80-positive Kupffer cells",
        "predicate": "expressed",
        "object_text": "eGFP",
        "endpoint_text": "eGFP expression",
        "qualitative_result": "few",
        "numeric_value": None,
        "value_text": None,
        "unit": None,
        "polarity": "positive",
        "evidence_ids": ["E1"],
        "source_ids": ["S1"],
        "route_hint": "text",
        "confidence": "high",
        "review_reasons": [],
        "structural_signature": "x",
    }
    values.update(changes)
    return AtomicOutcomeCandidateV12(**values)


def outcome(value=None, qualitative=None):
    return {
        "outcome_id": "O1",
        "endpoint": {"value": "eGFP expression", "evidence_ids": ["E1"]},
        "qualitative_outcome": {
            "value": qualitative,
            "evidence_ids": ["E1"],
        },
        "outcome_value": {"value": value, "evidence_ids": ["E1"]},
    }


def test_shared_evidence_needs_compatible_relationship():
    score, reasons = match_score(
        candidate(),
        outcome(
            qualitative=(
                "Few F4/80-positive Kupffer cells expressed eGFP."
            )
        ),
    )
    assert score >= 7
    assert "shared_evidence" in reasons


def test_different_numeric_value_is_penalized():
    row = candidate(numeric_value=41.5)
    correct, _ = match_score(row, outcome(value=41.5))
    wrong, reasons = match_score(row, outcome(value=16.5))
    assert correct > wrong
    assert "different_numeric_value" in reasons


def test_hsc_candidate_does_not_match_unspecified_fap_cells():
    row = candidate(
        predicate="eliminated",
        subject_text="FAPCAR macrophages",
        object_text="FAP-positive activated HSCs",
        endpoint_text="activated HSC elimination",
        qualitative_result="eliminated",
        evidence_ids=["E2"],
    )
    vague = {
        "outcome_id": "O1",
        "endpoint": {"value": "FAP+ cells", "evidence_ids": ["E1"]},
        "qualitative_outcome": {
            "value": "Targeted elimination of FAP+ cells.",
            "evidence_ids": ["E1"],
        },
        "outcome_value": {"value": None, "evidence_ids": []},
    }
    score, reasons = match_score(row, vague)
    assert score < 7
    assert "missing_cell_target" in reasons


def test_bounded_actionable_reserves_distinct_predicates():
    rows = []
    for index in range(10):
        row = candidate(
            candidate_id=f"AOC-EXP-{index}",
            predicate="expressed",
            structural_signature=f"exp-{index}",
        )
        rows.append((index, row, relevance_score(row)))
    eliminated = candidate(
        candidate_id="AOC-ELIM",
        predicate="eliminated",
        object_text="activated HSCs",
        structural_signature="elim",
    )
    rows.append((10, eliminated, relevance_score(eliminated)))
    rows.sort(key=lambda row: row[2][0], reverse=True)
    selected = _bounded_actionable(rows, maximum=8)
    assert "AOC-ELIM" in {row[1].candidate_id for row in selected}
