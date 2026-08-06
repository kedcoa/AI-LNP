import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.database.corpus_manifest import (
    CandidateArtifactRecord,
    CorpusEntry,
    MetadataProvenanceRecord,
    PipelineLineageRecord,
    PublicationMetadata,
    SourceAccessRecord,
    load_lane,
    scan_artifact_candidates,
    validate_corpus,
)


FIXTURE = Path(__file__).parent / "fixtures/database/corpus_manifest/valid_lane.json"
ROOT = Path(__file__).resolve().parents[1]
LANE_PATHS = [
    ROOT / "data/manifests/current_corpus_lanes/gp_v1.json",
    ROOT / "data/manifests/current_corpus_lanes/np_v1.json",
    ROOT / "data/manifests/current_corpus_lanes/pilot_v1.json",
]


def _entry(**overrides: object) -> CorpusEntry:
    values: dict[str, object] = {
        "paper_id": "GP-001",
        "title": None,
        "doi": None,
        "pmid": None,
        "pmcid": None,
        "publication_metadata": {
            "citation": None,
            "journal": None,
            "publication_year": None,
            "publication_date": None,
        },
        "source_access_records": [
            {
                "path": "metadata/GP-001.json",
                "source_kind": "metadata_manifest",
                "access_status": "unresolved",
                "sha256": None,
                "notes": None,
            }
        ],
        "candidate_artifacts": [],
        "pipeline_lineage": [],
        "metadata_provenance": [
            {
                "fields": ["title", "doi", "pmid", "pmcid"],
                "source": None,
                "method": "unresolved",
            }
        ],
        "last_checked": "2026-08-06",
        "strongest_artifact_rationale": "No supported artifact is selected.",
        "import_status": "needs_review",
        "rerun_status": "none",
        "rerun_reason": None,
        "import_artifact": None,
    }
    values.update(overrides)
    if values["import_artifact"] is not None and "candidate_artifacts" not in overrides:
        values["candidate_artifacts"] = [
            {
                "path": values["import_artifact"],
                "artifact_kind": "test_candidate",
                "access_status": "available",
                "selection_status": "selected",
                "sha256": "a" * 64,
                "pipeline_name": "test_pipeline",
                "pipeline_version": None,
                "validation_status": "test_fixture",
                "notes": None,
            }
        ]
    return CorpusEntry.model_validate(values)


def _complete_entry_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "paper_id": "GP-002",
        "title": None,
        "doi": "10.1000/example",
        "pmid": None,
        "pmcid": "PMC123",
        "publication_metadata": {
            "citation": None,
            "journal": None,
            "publication_year": None,
            "publication_date": None,
        },
        "source_access_records": [
            {
                "path": "data/staging/rag/compact_packets_v1/GP-002.json",
                "source_kind": "compact_packet",
                "access_status": "available",
                "sha256": None,
                "notes": None,
            }
        ],
        "candidate_artifacts": [],
        "pipeline_lineage": [],
        "metadata_provenance": [
            {
                "fields": ["doi", "pmcid"],
                "source": "data/manifests/gold_source_manifest_v1.json",
                "method": "local_artifact",
            },
            {
                "fields": ["title", "publication_metadata"],
                "source": None,
                "method": "unresolved",
            },
        ],
        "last_checked": "2026-08-06",
        "strongest_artifact_rationale": "No candidate has been selected yet.",
        "import_status": "needs_review",
        "rerun_status": "none",
        "rerun_reason": None,
        "import_artifact": None,
    }
    values.update(overrides)
    return values


def test_complete_entry_round_trips_all_inventory_structures() -> None:
    entry = CorpusEntry.model_validate(_complete_entry_values())

    restored = CorpusEntry.model_validate_json(entry.model_dump_json())

    assert restored == entry
    assert isinstance(restored.publication_metadata, PublicationMetadata)
    assert isinstance(restored.source_access_records[0], SourceAccessRecord)
    assert isinstance(restored.metadata_provenance[0], MetadataProvenanceRecord)
    assert restored.pmcid == "PMC123"
    assert restored.last_checked.isoformat() == "2026-08-06"


def test_selected_artifact_requires_matching_candidate_and_rationale() -> None:
    selected = {
        "path": "data/staging/extraction/run/GP-002/result.json",
        "artifact_kind": "accepted_graph",
        "access_status": "available",
        "selection_status": "selected",
        "sha256": "a" * 64,
        "pipeline_name": "fulltext_rag",
        "pipeline_version": None,
        "validation_status": "accepted",
        "notes": None,
    }
    lineage = {
        "pipeline_name": "fulltext_rag",
        "pipeline_version": None,
        "artifact_path": selected["path"],
        "status": "selected",
        "validation_path": None,
        "notes": None,
    }
    values = _complete_entry_values(
        import_artifact=selected["path"],
        candidate_artifacts=[selected],
        pipeline_lineage=[lineage],
        strongest_artifact_rationale="Validated merged evidence-linked graph.",
    )

    entry = CorpusEntry.model_validate(values)

    assert isinstance(entry.candidate_artifacts[0], CandidateArtifactRecord)
    assert isinstance(entry.pipeline_lineage[0], PipelineLineageRecord)
    values["strongest_artifact_rationale"] = ""
    with pytest.raises(ValidationError, match="rationale"):
        CorpusEntry.model_validate(values)


def test_real_lanes_round_trip_complete_inventory_records() -> None:
    entries = [entry for path in LANE_PATHS for entry in load_lane(path)]

    assert len(entries) == 14
    assert all(entry.last_checked.isoformat() == "2026-08-06" for entry in entries)
    assert all(entry.metadata_provenance for entry in entries)
    assert all(entry.strongest_artifact_rationale.strip() for entry in entries)
    assert all(entry.publication_metadata is not None for entry in entries)
    assert all(entry.source_access_records for entry in entries)
    assert all(
        CorpusEntry.model_validate_json(entry.model_dump_json()) == entry
        for entry in entries
    )
    for entry in entries:
        selected = [
            candidate
            for candidate in entry.candidate_artifacts
            if candidate.selection_status == "selected"
        ]
        assert [candidate.path for candidate in selected] == (
            [entry.import_artifact] if entry.import_artifact else []
        )


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
    entries = [
        _entry(
            import_artifact="data/staging/extraction/GP-001/missing.json"
        )
    ]

    with pytest.raises(ValueError, match="selected import artifact does not exist"):
        validate_corpus(entries, tmp_path)


@pytest.mark.parametrize("rerun_status", ["selective", "blocked_pending_access"])
def test_non_none_rerun_status_requires_a_reason(rerun_status: str) -> None:
    with pytest.raises(ValidationError, match="rerun reason"):
        _entry(rerun_status=rerun_status, rerun_reason=None)


def test_scanner_returns_sorted_candidates_with_local_provenance(tmp_path: Path) -> None:
    artifact_root = tmp_path / "data/staging/extraction/GP-001"
    first = artifact_root / "result-v12-validation.json"
    second = artifact_root / "source.xml"
    ignored = artifact_root / "raw" / "GP-001-provider-response.json"
    for path, text in ((first, "{}\n"), (second, "<article/>\n"), (ignored, "secret")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    candidates = scan_artifact_candidates(tmp_path, ["GP-001"])

    assert [candidate.path for candidate in candidates] == [
        "data/staging/extraction/GP-001/result-v12-validation.json",
        "data/staging/extraction/GP-001/source.xml",
    ]
    assert candidates[0].paper_id == "GP-001"
    assert candidates[0].sha256 == hashlib.sha256(b"{}\n").hexdigest()
    assert candidates[0].artifact_kind == "json"
    assert candidates[0].pipeline_clue == "v12"
    assert candidates[0].validation_clue == "validation"
    assert candidates[0].modified_at.endswith("+00:00")


def test_scanner_excludes_provider_and_licensed_paths(tmp_path: Path) -> None:
    for path in (
        tmp_path
        / "data/staging/extraction/provider-responses"
        / "GP-001.json",
        tmp_path / "data/staging/extraction/licensed-sources" / "GP-001.json",
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
    artifact = tmp_path / "data/staging/extraction/GP-001" / filename
    artifact.parent.mkdir(parents=True)
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
    artifact = tmp_path / "data/staging/extraction/GP-001" / filename
    artifact.parent.mkdir(parents=True)
    artifact.write_text("must not be hashed", encoding="utf-8")

    assert scan_artifact_candidates(tmp_path, ["GP-001"]) == []


@pytest.mark.parametrize(
    "artifact_path",
    [
        "data/staging/extraction/GP-001/GP-001_credentials.json",
        "data/staging/extraction/GP-001/GP-001-raw-provider-output.json",
        "data/staging/extraction/licensed-sources/GP-001.json",
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
        "data/staging/extraction/GP-001/GP-001_access-token.json",
        "data/staging/extraction/GP-001/GP-001.private_key.pem",
        "data/staging/extraction/GP-001/GP-001-password.txt",
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


def test_scanner_only_reads_allowlisted_derived_artifact_roots(
    tmp_path: Path,
) -> None:
    allowed = (
        tmp_path
        / "data/staging/extraction/GP-001"
        / "GP-001-accepted.json"
    )
    outside = tmp_path / "misc/GP-001-result.json"
    for path in (allowed, outside):
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")

    candidates = scan_artifact_candidates(tmp_path, ["GP-001"])

    assert [candidate.path for candidate in candidates] == [
        "data/staging/extraction/GP-001/GP-001-accepted.json"
    ]


@pytest.mark.parametrize(
    "filename",
    [
        "GP-001-token.json",
        "GP-001_token.json",
        "GP-001.token.json",
        ".envrc",
        "id_rsa",
    ],
)
def test_scanner_excludes_additional_credential_names(
    tmp_path: Path,
    filename: str,
) -> None:
    artifact = tmp_path / "data/staging/extraction/GP-001" / filename
    artifact.parent.mkdir(parents=True)
    artifact.write_text("must not be read", encoding="utf-8")

    assert scan_artifact_candidates(tmp_path, ["GP-001"]) == []


@pytest.mark.parametrize("suffix", [".pdf", ".sqlite", ".bin"])
def test_scanner_excludes_non_allowlisted_artifact_types(
    tmp_path: Path,
    suffix: str,
) -> None:
    artifact = (
        tmp_path
        / "data/staging/extraction/GP-001"
        / f"GP-001-result{suffix}"
    )
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"not a derived structured artifact")

    assert scan_artifact_candidates(tmp_path, ["GP-001"]) == []


@pytest.mark.parametrize(
    "artifact_path",
    [
        "misc/GP-001-result.json",
        "data/staging/extraction/GP-001/result.pdf",
    ],
)
def test_validate_corpus_rejects_selected_artifact_outside_allowlist(
    tmp_path: Path,
    artifact_path: str,
) -> None:
    selected = tmp_path / artifact_path
    selected.parent.mkdir(parents=True)
    selected.write_text("not allowed", encoding="utf-8")

    with pytest.raises(ValueError, match="selected import artifact is excluded"):
        validate_corpus([_entry(import_artifact=artifact_path)], tmp_path)
