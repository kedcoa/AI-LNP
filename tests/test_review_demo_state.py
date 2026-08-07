from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.ui.review_demo_state import (
    apply_decision,
    demo_papers,
    queue_items,
    simulate_eligibility,
)


def test_demo_queue_contains_only_fictional_review_scenarios() -> None:
    papers = demo_papers()

    assert len(papers) == 3
    assert {arm.primary_reason for paper in papers for arm in paper.arms} == {
        "Target cell needs confirmation",
        "Dose missing",
        "Outcome link conflict",
    }
    assert all(paper.is_fictional for paper in papers)
    assert all("example" in paper.doi_url for paper in papers)


def test_queue_filters_by_paper_reason_and_near_eligibility() -> None:
    papers = demo_papers()

    filtered = queue_items(
        papers,
        paper_ids=("DEMO-002",),
        reasons=("Dose missing",),
        near_eligibility=True,
    )

    assert [arm.arm_id for arm in filtered] == ["DEMO-002-A1"]


def test_review_decisions_return_new_mock_state_and_update_eligibility() -> None:
    original = demo_papers()[1].arms[0]
    before = simulate_eligibility(original)

    corrected = apply_decision(
        original,
        "dose",
        "correct",
        corrected_value="0.75",
    )
    corrected = apply_decision(corrected, "dose_unit", "accept")
    after = simulate_eligibility(corrected)

    assert original.fields["dose"].value == "Not extracted"
    assert corrected.fields["dose"].value == "0.75"
    assert corrected.fields["dose"].status == "verified"
    assert "dose" in before.nearest_neighbor_reasons
    assert "dose" not in after.nearest_neighbor_reasons
    assert corrected is not original


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [("accept", "verified"), ("not_reported", "not_reported"), ("unresolved", "needs_confirmation")],
)
def test_supported_review_actions_are_session_state_compatible(
    action: str, expected_status: str
) -> None:
    arm = demo_papers()[0].arms[0]

    changed = apply_decision(arm, "target_cell", action)

    assert changed.fields["target_cell"].status == expected_status
    with pytest.raises(FrozenInstanceError):
        changed.arm_id = "changed"  # type: ignore[misc]


def test_demo_state_has_no_database_or_network_dependency() -> None:
    source = (
        Path(__file__).parents[1] / "src/ui/review_demo_state.py"
    ).read_text(encoding="utf-8")

    assert "sqlite" not in source.lower()
    assert "data/curated" not in source
    assert "requests" not in source
    assert "urllib" not in source
