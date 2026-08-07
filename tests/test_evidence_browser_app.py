from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_evidence_browser_service import evidence_browser_database


APP = Path(__file__).parents[1] / "src/ui/evidence_browser_app.py"


def _source() -> str:
    return APP.read_text(encoding="utf-8")


def test_evidence_browser_app_keeps_sql_behind_service_boundaries() -> None:
    source = _source()
    lowered = source.lower()

    assert "from src.ui.evidence_browser_service import" in source
    assert "sqlite3" not in lowered
    assert ".execute(" not in source
    assert "Submit review decision" not in source
    assert "Needs human verification" not in source
    assert "review_service.apply_review_decision" in source


def test_evidence_browser_app_preserves_approved_columns_and_sections() -> None:
    source = _source()
    labels = (
        "lnp_name", "chemical_formulation_total", "lnp_molar_ratio",
        "ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid", "others",
    )
    positions = [source.index(f'"{label}"') for label in labels]
    assert positions == sorted(positions)
    for label in (
        "Paper", "Paper access", "LNP formulations", "Formulation evidence",
        "Experimental arms", "Outcomes", "Automatic-resolution issues",
        "Nearest neighbor", "COMET", "NA",
    ):
        assert label in source


def test_evidence_browser_app_renders_fixture_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    evidence_browser_database: Path,
) -> None:
    from src.ui import evidence_browser_service
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(
        evidence_browser_service,
        "browser_database_path",
        lambda: evidence_browser_database,
    )
    before = hashlib.sha256(evidence_browser_database.read_bytes()).hexdigest()
    app = AppTest.from_file(str(APP)).run(timeout=15)
    after = hashlib.sha256(evidence_browser_database.read_bytes()).hexdigest()

    assert not app.exception
    assert any(item.value == "LNP formulations" for item in app.subheader)
    assert any(item.label == "Paper" for item in app.selectbox)
    assert next(item for item in app.selectbox if item.label == "Paper").value == 1
    assert app.dataframe
    assert any(item.label == "Save correction" for item in app.button)
    assert before == after


def test_local_service_import_bootstraps_repository_package() -> None:
    ui_directory = APP.parent
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(ui_directory)!r}); "
                "import evidence_browser_service"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
