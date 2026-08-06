import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.database.corpus_manifest import (
    CorpusEntry,
    load_lane,
    scan_artifact_candidates,
    validate_corpus,
)


FIXTURE = Path(__file__).parent / "fixtures/database/corpus_manifest/valid_lane.json"


def _entry(**overrides: object) -> CorpusEntry:
    values: dict[str, object] = {
        "paper_id": "GP-001",
        "title": None,
        "doi": None,
        "pmid": None,
        "import_status": "needs_review",
        "rerun_status": "none",
        "rerun_reason": None,
        "import_artifact": None,
    }
    values.update(overrides)
    return CorpusEntry.model_validate(values)


def test_load_lane_preserves_explicit_unresolved_bibliography() -> None:
    entries = load_lane(FIXTURE)

    assert [entry.paper_id for entry in entries] == ["GP-001", "GP-002"]
    assert entries[0].title is None
    assert entries[0].doi is None
    assert entries[0].pmid is None


def test_validate_corpus_rejects_duplicate_paper_ids(tmp_path: Path) -> None:
    entries = [_entry(), _entry()]

    with pytest.raises(ValueError, match="duplicate paper_id.*GP-001"):
        validate_corpus(entries, tmp_path)


def test_screening_only_entry_cannot_select_an_import_artifact() -> None:
    with pytest.raises(ValidationError, match="screening_only.*import artifact"):
        _entry(import_status="screening_only", import_artifact="GP-001/result.json")


def test_validate_corpus_requires_selected_artifact_to_exist(tmp_path: Path) -> None:
    entries = [_entry(import_artifact="GP-001/missing.json")]

    with pytest.raises(ValueError, match="selected import artifact does not exist"):
        validate_corpus(entries, tmp_path)


@pytest.mark.parametrize("rerun_status", ["selective", "blocked_pending_access"])
def test_non_none_rerun_status_requires_a_reason(rerun_status: str) -> None:
    with pytest.raises(ValidationError, match="rerun reason"):
        _entry(rerun_status=rerun_status, rerun_reason=None)


def test_scanner_returns_sorted_candidates_with_local_provenance(tmp_path: Path) -> None:
    first = tmp_path / "GP-001" / "result-v12-validation.json"
    second = tmp_path / "GP-001" / "source.xml"
    ignored = tmp_path / "raw" / "GP-001-provider-response.json"
    for path, text in ((first, "{}\n"), (second, "<article/>\n"), (ignored, "secret")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    candidates = scan_artifact_candidates(tmp_path, ["GP-001"])

    assert [candidate.path for candidate in candidates] == [
        "GP-001/result-v12-validation.json",
        "GP-001/source.xml",
    ]
    assert candidates[0].paper_id == "GP-001"
    assert candidates[0].sha256 == hashlib.sha256(b"{}\n").hexdigest()
    assert candidates[0].artifact_kind == "json"
    assert candidates[0].pipeline_clue == "v12"
    assert candidates[0].validation_clue == "validation"
    assert candidates[0].modified_at.endswith("+00:00")


def test_scanner_excludes_provider_and_licensed_paths(tmp_path: Path) -> None:
    for path in (
        tmp_path / "provider-responses" / "GP-001.json",
        tmp_path / "licensed-sources" / "GP-001.pdf",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not an inventory artifact", encoding="utf-8")

    assert scan_artifact_candidates(tmp_path, ["GP-001"]) == []


@pytest.mark.parametrize(
    "filename",
    [
        "GP-001_credentials.json",
        "GP-001_secret.txt",
        "GP-001_api_key.json",
        "GP-001-raw-provider-output.json",
        "GP-001.provider-response.json",
    ],
)
def test_scanner_excludes_sensitive_filename_variants(
    tmp_path: Path, filename: str
) -> None:
    artifact = tmp_path / "GP-001" / filename
    artifact.parent.mkdir()
    artifact.write_text("must not be hashed", encoding="utf-8")

    assert scan_artifact_candidates(tmp_path, ["GP-001"]) == []


@pytest.mark.parametrize(
    "filename",
    [
        "GP-001_access-token.json",
        "GP-001.access_token.json",
        "GP-001-private-key.pem",
        "GP-001.private_key.pem",
        "GP-001-password.txt",
        "GP-001.password.txt",
    ],
)
def test_scanner_excludes_access_secrets_with_separator_variants(
    tmp_path: Path, filename: str
) -> None:
    artifact = tmp_path / "GP-001" / filename
    artifact.parent.mkdir()
    artifact.write_text("must not be hashed", encoding="utf-8")

    assert scan_artifact_candidates(tmp_path, ["GP-001"]) == []


@pytest.mark.parametrize(
    "artifact_path",
    [
        "GP-001/GP-001_credentials.json",
        "GP-001/GP-001-raw-provider-output.json",
        "licensed-sources/GP-001.json",
    ],
)
def test_validate_corpus_rejects_selected_sensitive_artifacts(
    tmp_path: Path, artifact_path: str
) -> None:
    selected = tmp_path / artifact_path
    selected.parent.mkdir(parents=True)
    selected.write_text("must not be selected", encoding="utf-8")

    with pytest.raises(ValueError, match="selected import artifact is excluded"):
        validate_corpus([_entry(import_artifact=artifact_path)], tmp_path)


@pytest.mark.parametrize(
    "artifact_path",
    [
        "GP-001/GP-001_access-token.json",
        "GP-001/GP-001.private_key.pem",
        "GP-001/GP-001-password.txt",
    ],
)
def test_validate_corpus_rejects_selected_access_secrets(
    tmp_path: Path, artifact_path: str
) -> None:
    selected = tmp_path / artifact_path
    selected.parent.mkdir(parents=True)
    selected.write_text("must not be selected", encoding="utf-8")

    with pytest.raises(ValueError, match="selected import artifact is excluded"):
        validate_corpus([_entry(import_artifact=artifact_path)], tmp_path)


def test_load_lane_rejects_non_list_entries(tmp_path: Path) -> None:
    lane = tmp_path / "malformed.json"
    lane.write_text(json.dumps({"entries": {"paper_id": "GP-001"}}), encoding="utf-8")

    with pytest.raises(ValueError, match="entries.*list"):
        load_lane(lane)
