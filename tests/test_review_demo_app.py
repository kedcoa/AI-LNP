from __future__ import annotations

from pathlib import Path


APP = Path(__file__).parents[1] / "src/ui/review_demo_app.py"


def test_demo_app_contains_complete_review_workspace_contract() -> None:
    source = APP.read_text(encoding="utf-8")

    required_copy = (
        "DEMO DATA ONLY",
        "Review queue",
        "Paper access",
        "Experimental arm",
        "Evidence inspector",
        "Review decision",
        "Eligibility preview",
        "Reset demo",
    )
    for text in required_copy:
        assert text in source


def test_demo_app_is_isolated_from_database_and_external_clients() -> None:
    source = APP.read_text(encoding="utf-8").lower()

    assert "sqlite" not in source
    assert "data/curated" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "openai" not in source


def test_demo_app_renders_with_streamlit_testing() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(APP)).run(timeout=15)

    assert not app.exception
    assert any("DEMO DATA ONLY" in item.value for item in app.markdown)
    assert len(app.selectbox) >= 1
    assert len(app.multiselect) == 2
    assert any(button.label == "Reset demo" for button in app.button)
