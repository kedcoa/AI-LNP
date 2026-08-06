from __future__ import annotations

from pathlib import Path


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
        "Only show nearly eligible arms",
        "DOI / publisher",
        "PubMed",
        "PMC",
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
        "Review history",
        "Reviewer",
        "Reviewer note",
        "Accept extracted value",
        "Correct value",
        "Mark not reported",
        "Reject evidence",
        "Evidence belongs to another arm",
        "Leave unresolved",
        "Eligibility after save",
        "Submit review decision",
    ):
        assert label in source
    assert "disabled=not can_submit" in source
