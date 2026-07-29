from src.extraction.select_atomic_candidates_v12 import (
    relevance_score,
    select_candidates,
)
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


def candidate(identifier: str, **changes):
    values = {
        "candidate_id": identifier,
        "paper_id": "GP-X",
        "claim_ids": ["ACL-1"],
        "provisional_experiment_id": "PEX-1",
        "subject_text": "LSECs",
        "predicate": "expressed",
        "object_text": "GFP",
        "endpoint_text": "GFP expression",
        "qualitative_result": "reported",
        "numeric_value": None,
        "value_text": None,
        "unit": None,
        "polarity": "positive",
        "evidence_ids": ["E1"],
        "source_ids": ["S1"],
        "route_hint": "text",
        "confidence": "high",
        "review_reasons": [],
        "structural_signature": identifier,
    }
    values.update(changes)
    return AtomicOutcomeCandidateV12(**values)


def test_complete_cell_relationship_outranks_generic_fragment():
    complete = candidate("AOC-COMPLETE")
    generic = candidate(
        "AOC-GENERIC",
        subject_text="reported outcome",
        endpoint_text=None,
        qualitative_result=None,
        provisional_experiment_id=None,
        confidence="medium",
    )
    assert relevance_score(complete)[0] > relevance_score(generic)[0]


def test_selection_is_bounded_and_auditable():
    rows = [candidate(f"AOC-{index}") for index in range(30)]
    selected, audit = select_candidates(rows, maximum=24)
    assert len(selected) == 24
    assert len(audit) == 30
    assert sum(row["selected"] for row in audit) == 24


def test_selection_reserves_a_distinct_elimination_predicate():
    rows = [candidate(f"AOC-EXP-{index}") for index in range(30)]
    rows.append(
        candidate(
            "AOC-ELIM",
            predicate="eliminated",
            endpoint_text=None,
            qualitative_result=None,
            subject_text="FAPCAR macrophages",
            object_text="activated HSCs",
        )
    )
    selected, _ = select_candidates(rows, maximum=24)
    assert "AOC-ELIM" in {row.candidate_id for row in selected}
