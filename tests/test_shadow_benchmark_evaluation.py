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
    evidence_statuses: dict[str, str] | None = None,
    automated_statuses: dict[str, bool] | None = None,
) -> dict:
    requirement_ids = [f"REQ-{number:03d}" for number in range(1, 63)]
    if evidence_statuses is None:
        evidence_statuses = {
            requirement_id: (
                "full"
                if index < evidence_full
                else "partial"
                if index < evidence_full + evidence_partial
                else "absent"
            )
            for index, requirement_id in enumerate(requirement_ids)
        }
    if automated_statuses is None:
        automated_statuses = {
            requirement_id: index < automated_full
            for index, requirement_id in enumerate(requirement_ids)
        }
    return {
        "automated_full": automated_full,
        "evidence_full": evidence_full,
        "evidence_partial": evidence_partial,
        "evidence_absent": evidence_absent,
        "recovered_partial_or_absent": recovered_partial_or_absent,
        "recovered_absent": recovered_absent,
        "deterministic_undercounts_recovered": deterministic_undercounts_recovered,
        "evidence_statuses": evidence_statuses,
        "automated_statuses": automated_statuses,
    }


def test_classify_result_requires_every_success_threshold():
    before = _result(automated_full=40)
    after = _result(
        automated_full=45,
        recovered_partial_or_absent=2,
        deterministic_undercounts_recovered=5,
    )
    after["evidence_statuses"]["REQ-058"] = "full"
    after["evidence_statuses"]["REQ-059"] = "full"
    after["evidence_full"] = 59
    after["evidence_partial"] = 1

    assert classify_result(before, after, {}) == "works"


def test_classify_result_treats_partial_to_full_as_an_evidence_level_improvement():
    after = _result(
        automated_full=45,
        evidence_full=59,
        evidence_partial=1,
        recovered_partial_or_absent=2,
        deterministic_undercounts_recovered=5,
    )
    after["evidence_statuses"]["REQ-058"] = "full"
    after["evidence_statuses"]["REQ-059"] = "full"

    assert classify_result(_result(automated_full=40), after, {}) == "works"


@pytest.mark.parametrize(
    "after",
    [
        _result(automated_full=44, deterministic_undercounts_recovered=4),
        _result(automated_full=45, deterministic_undercounts_recovered=5),
        _result(automated_full=45, evidence_full=56, evidence_absent=3, deterministic_undercounts_recovered=5),
    ],
)
def test_classify_result_marks_safe_improvements_below_success_as_promising(after):
    assert classify_result(_result(automated_full=40), after, {}) == "promising_but_inconclusive"


def test_classify_result_accepts_absence_plus_five_deterministic_undercount_recovery():
    after = _result(
        automated_full=45,
        recovered_partial_or_absent=1,
        recovered_absent=1,
        deterministic_undercounts_recovered=5,
    )
    after["evidence_statuses"]["REQ-061"] = "full"
    after["evidence_full"] = 58
    after["evidence_absent"] = 1
    for requirement_id in [f"REQ-{number:03d}" for number in range(41, 46)]:
        after["automated_statuses"][requirement_id] = True

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


def test_classify_result_rejects_claimed_recovery_when_item_statuses_are_unchanged():
    after = _result(automated_full=45, recovered_partial_or_absent=2)
    for requirement_id in [f"REQ-{number:03d}" for number in range(41, 46)]:
        after["automated_statuses"][requirement_id] = True

    assert classify_result(_result(automated_full=40), after, {}) == "does_not_work"


def test_classify_result_rejects_claimed_absence_recovery_while_absence_remains():
    after = _result(
        automated_full=45,
        recovered_absent=1,
        deterministic_undercounts_recovered=5,
    )
    for requirement_id in [f"REQ-{number:03d}" for number in range(41, 46)]:
        after["automated_statuses"][requirement_id] = True

    assert classify_result(_result(automated_full=40), after, {}) == "does_not_work"


def test_classify_result_does_not_hide_full_to_partial_with_equal_aggregate_counts():
    after = _result(automated_full=45, recovered_partial_or_absent=2)
    after["evidence_statuses"]["REQ-001"] = "partial"
    after["evidence_statuses"]["REQ-058"] = "full"
    after["evidence_full"] = 57
    after["evidence_partial"] = 3
    for requirement_id in [f"REQ-{number:03d}" for number in range(41, 46)]:
        after["automated_statuses"][requirement_id] = True

    assert classify_result(_result(automated_full=40), after, {}) != "works"


@pytest.mark.parametrize(
    "before",
    [
        _result(automated_full=39),
        {key: value for key, value in _result(automated_full=40).items() if key != "evidence_statuses"},
        _result(automated_full=40, evidence_full=56, evidence_partial=4),
    ],
)
def test_classify_result_fails_closed_for_noncanonical_or_incomplete_baseline(before):
    after = _result(automated_full=45, recovered_partial_or_absent=2)
    after["evidence_statuses"]["REQ-058"] = "full"
    after["evidence_statuses"]["REQ-059"] = "full"
    after["evidence_full"] = 59
    after["evidence_partial"] = 1

    assert classify_result(before, after, {}) == "does_not_work"
