from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from tests.test_evidence_browser_service import evidence_browser_database


APP = Path(__file__).parents[1] / "src/ui/evidence_browser_app.py"


def test_comet_gap_page_remains_read_only_without_correction_form(
    monkeypatch: pytest.MonkeyPatch,
    evidence_browser_database: Path,
) -> None:
    from src.ui import evidence_browser_service
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(
        evidence_browser_service, "browser_database_path",
        lambda: evidence_browser_database,
    )
    with sqlite3.connect(evidence_browser_database) as connection:
        connection.execute(
            "UPDATE eligibility_result SET eligible=0,reasons_json=?,rules_version=? "
            "WHERE experiment_id=1 AND profile='comet'",
            ('["lnp_molar_ratio"]', 'working-evidence-v3'),
        )
        connection.commit()
    app = AppTest.from_file(str(APP)).run(timeout=15)

    assert not app.exception
    assert not any(item.label == "Missing field" for item in app.selectbox)
    assert not any(item.label == "Updated value" for item in app.text_input)
    assert not any(item.label == "Evidence excerpt" for item in app.text_area)
    assert not any(item.label == "Evidence location" for item in app.text_input)
    assert not any(item.label == "Save correction" for item in app.button)
