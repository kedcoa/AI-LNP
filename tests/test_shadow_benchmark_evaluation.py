from __future__ import annotations

import pytest

from src.extraction.evaluate_shadow_benchmark import classify_result


def _result(
    *,
    automated_full: int,
    evidence_full: int = 57,
    evidence_partial: int = 3,
    evidence_absent: int = 2,
    recovered_partial_or_absent: int = 0,
    recovered_absent: int = 0,
    deterministic_undercounts_recovered: int = 0,
) -> dict:
    return {
        "automated_full": automated_full,
        "evidence_full": evidence_full,
        "evidence_partial": evidence_partial,
        "evidence_absent": evidence_absent,
        "recovered_partial_or_absent": recovered_partial_or_absent,
        "recovered_absent": recovered_absent,
        "deterministic_undercounts_recovered": deterministic_undercounts_recovered,
    }


def test_classify_result_requires_every_success_threshold():
    before = _result(automated_full=40)
    after = _result(automated_full=45, recovered_partial_or_absent=2)

    assert classify_result(before, after, {}) == "works"


def test_classify_result_treats_partial_to_full_as_an_evidence_level_improvement():
    after = _result(
        automated_full=45,
        evidence_full=58,
        evidence_partial=2,
        recovered_partial_or_absent=2,
    )

    assert classify_result(_result(automated_full=40), after, {}) == "works"


@pytest.mark.parametrize(
    "after",
    [
        _result(automated_full=44, recovered_partial_or_absent=2),
        _result(automated_full=45, recovered_partial_or_absent=1),
        _result(automated_full=45, evidence_full=56, recovered_partial_or_absent=2),
    ],
)
def test_classify_result_marks_safe_improvements_below_success_as_promising(after):
    assert classify_result(_result(automated_full=40), after, {}) == "promising_but_inconclusive"


def test_classify_result_accepts_absence_plus_five_deterministic_undercount_recovery():
    after = _result(
        automated_full=45,
        recovered_absent=1,
        deterministic_undercounts_recovered=5,
    )

    assert classify_result(_result(automated_full=40), after, {}) == "works"


@pytest.mark.parametrize(
    "safety",
    [
        {"gold_leakage": 1},
        {"accepted_unsupported_or_invented_fact": True},
        {"accepted_wrong_relationship": 1},
        {"three_consecutive_systemic_failures": 3},
    ],
)
def test_classify_result_rejects_hard_safety_failures(safety):
    after = _result(automated_full=45, recovered_partial_or_absent=2)

    assert classify_result(_result(automated_full=40), after, safety) == "does_not_work"


def test_classify_result_rejects_no_supported_improvement():
    assert classify_result(_result(automated_full=40), _result(automated_full=40), {}) == "does_not_work"
