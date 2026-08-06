from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_review_service import review_database


APP = Path(__file__).parents[1] / "src/ui/review_app.py"


def _source() -> str:
    return APP.read_text(encoding="utf-8")


def test_review_app_uses_only_the_review_service_boundary() -> None:
    source = _source()
    lowered = source.lower()

    assert "from src.ui.review_service import" in source
    assert "sqlite3" not in lowered
    assert ".execute(" not in source


def test_review_app_renders_the_real_dashboard_queue_and_paper_contract() -> None:
    source = _source()

    for symbol in ("load_dashboard", "list_paper_summaries", "list_review_arms"):
        assert symbol in source
    for label in (
        "Nearest-neighbor ready",
        "COMET ready",
        "Automatically validated facts",
        "Manually verified facts",
        "Usable field facts",
        "Paper inventory",
        "Formulations",
        "Chemical components",
        "Experimental arms",
        "Evidence excerpts",
        "Review queue",
        "Paper",
        "Review status",
        "Review reason",
        "Target cell",
        "Species",
        "Payload",
        "Eligibility proximity",
        "Near nearest-neighbor eligibility",
        "Near COMET eligibility",
        "DOI / publisher",
        "PubMed",
        "PMC",
        "Local full text",
        "Institutional library",
        "Source record",
    ):
        assert label in source


def test_review_app_includes_workspace_review_controls_and_post_save_eligibility() -> None:
    source = _source()

    for symbol in ("load_arm_workspace", "prepare_writes", "apply_review_decision"):
        assert symbol in source
    for label in (
        "Experimental arm",
        "Evidence inspector",
        "Review history for selected field",
        "Reviewer",
        "Reviewer note",
        "Accept extracted value",
        "Correct value",
        "Mark not reported",
        "Reject evidence",
        "Evidence belongs to another arm",
        "Leave unresolved",
        "Eligibility after save",
        "Nearest-neighbor blockers",
        "Submit review decision",
    ):
        assert label in source
    assert "disabled=not can_submit" in source
    assert "shown_evidence = matching_evidence +" in source
    assert "excerpt.outcome_id" in source
    assert "excerpt.experiment_id" in source


def test_review_app_renders_fixture_workspace_and_requires_verified_readiness(
    monkeypatch: pytest.MonkeyPatch, review_database: Path, tmp_path: Path
) -> None:
    from src.ui import review_service
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(review_service, "authoritative_database_path", lambda: review_database)
    monkeypatch.setenv("AI_LNP_REVIEW_BACKUP_DIR", str(tmp_path / "external-review-backups"))

    app = AppTest.from_file(str(APP)).run(timeout=15)

    assert not app.exception
    assert any(item.label == "Submit review decision" and item.disabled for item in app.button)
    prepare = next(item for item in app.button if item.label == "Prepare writing session")
    prepare.click().run(timeout=15)
    assert not app.exception
    assert any("Writes ready:" in item.value for item in app.success)
    assert any(item.label == "Submit review decision" and item.disabled for item in app.button)
