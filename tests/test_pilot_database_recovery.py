import hashlib
import json
from pathlib import Path

import pytest

from src.database.adapters.pilot_results import build_blocked_pilot_bundle
from src.database.import_contracts import ImportBundle
from src.database.recover_pilot_artifacts import (
    PilotArtifactExpectation,
    prepare_pilot_bundles,
    recover_pilot_sources,
)


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_recovery_finds_hash_verified_source_and_inventory(tmp_path: Path) -> None:
    root = tmp_path / "old-worktree"
    source = root / "data/staging/new_papers/PILOT-001/PMC1.html"
    source_hash = _write(source, b"<html>source</html>")
    inventory = root / "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
    _write(
        inventory,
        json.dumps(
            {
                "inventory_version": "full-paper-evidence-1.0.0",
                "paper_id": "PILOT-001",
                "source_pdf": "PMC1.html",
                "evidence_blocks": [],
            }
        ).encode(),
    )

    result = recover_pilot_sources(
        PilotArtifactExpectation(
            paper_id="PILOT-001",
            source_relative_path=Path("data/staging/new_papers/PILOT-001/PMC1.html"),
            source_sha256=source_hash,
            inventory_relative_path=Path(
                "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
            ),
        ),
        (root,),
    )

    assert result.status == "recovered"
    assert result.source_sha256 == source_hash
    assert result.inventory_sha256 == hashlib.sha256(inventory.read_bytes()).hexdigest()
    assert result.source_logical_path == "data/staging/new_papers/PILOT-001/PMC1.html"
    assert result.inventory_logical_path.endswith("PILOT-001/inventory.json")


def test_recovery_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "old-worktree"
    _write(
        root / "data/staging/new_papers/PILOT-001/PMC1.html",
        b"changed source",
    )
    _write(
        root / "data/staging/extraction/application_pilot/PILOT-001/inventory.json",
        json.dumps(
            {
                "inventory_version": "full-paper-evidence-1.0.0",
                "paper_id": "PILOT-001",
                "source_pdf": "PMC1.html",
                "evidence_blocks": [],
            }
        ).encode(),
    )

    result = recover_pilot_sources(
        PilotArtifactExpectation(
            paper_id="PILOT-001",
            source_relative_path=Path("data/staging/new_papers/PILOT-001/PMC1.html"),
            source_sha256="0" * 64,
            inventory_relative_path=Path(
                "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
            ),
        ),
        (root,),
    )

    assert result.status == "blocked"
    assert result.reason == "source hash mismatch"
    assert result.source_path is None


def test_recovery_rejects_wrong_inventory_paper(tmp_path: Path) -> None:
    root = tmp_path / "old-worktree"
    source_hash = _write(
        root / "data/staging/new_papers/PILOT-001/PMC1.html", b"source"
    )
    _write(
        root / "data/staging/extraction/application_pilot/PILOT-001/inventory.json",
        json.dumps(
            {
                "inventory_version": "full-paper-evidence-1.0.0",
                "paper_id": "PILOT-999",
                "source_pdf": "PMC1.html",
                "evidence_blocks": [],
            }
        ).encode(),
    )

    result = recover_pilot_sources(
        PilotArtifactExpectation(
            paper_id="PILOT-001",
            source_relative_path=Path("data/staging/new_papers/PILOT-001/PMC1.html"),
            source_sha256=source_hash,
            inventory_relative_path=Path(
                "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
            ),
        ),
        (root,),
    )

    assert result.status == "blocked"
    assert result.reason == "inventory paper mismatch"


def test_recovery_refuses_forbidden_artifact_paths() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        PilotArtifactExpectation(
            paper_id="PILOT-001",
            source_relative_path=Path("data/benchmarks/application_pilot/PILOT-001.json"),
            source_sha256="0" * 64,
            inventory_relative_path=Path("response.json"),
        )


def test_adapter_preserves_source_evidence_without_unsupported_experimental_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "old-worktree"
    source_rel = Path("data/staging/new_papers/PILOT-001/PMC1.html")
    inventory_rel = Path(
        "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
    )
    source_hash = _write(root / source_rel, b"source")
    _write(
        root / inventory_rel,
        json.dumps(
            {
                "inventory_version": "full-paper-evidence-1.0.0",
                "paper_id": "PILOT-001",
                "source_pdf": "PMC1.html",
                "evidence_blocks": [{"evidence_id": "FPE-1", "text": "not imported"}],
            }
        ).encode(),
    )
    recovery = recover_pilot_sources(
        PilotArtifactExpectation(
            paper_id="PILOT-001",
            source_relative_path=source_rel,
            source_sha256=source_hash,
            inventory_relative_path=inventory_rel,
        ),
        (root,),
    )

    bundle = build_blocked_pilot_bundle(
        recovery,
        {
            "paper_id": "PILOT-001",
            "title": "A paper",
            "doi": "10.1/example",
            "pmid": "1",
            "pmcid": "PMC1",
            "publication_metadata": {"publication_year": 2020, "journal": "J"},
        },
    )
    round_trip = ImportBundle.from_dict(bundle.to_dict())

    assert round_trip.paper.import_status == "needs_review"
    assert not round_trip.formulations
    assert not round_trip.arms
    assert len(round_trip.evidence) == 1
    assert round_trip.evidence[0].record_id == "FPE-1"
    assert round_trip.evidence[0].evidence_text == "not imported"
    assert round_trip.evidence[0].verification_status == "unreviewed"
    assert round_trip.reviews[0].status == "blocked"
    assert round_trip.reviews[0].reason_code == "validated_extraction_unavailable"
    assert {artifact.source_kind for artifact in round_trip.artifacts} == {
        "html",
        "source_inventory",
    }


def test_prepare_writes_deterministic_bundle_and_recovery_manifest(tmp_path: Path) -> None:
    old = tmp_path / "old"
    source_rel = Path("data/staging/new_papers/PILOT-001/PMC1.html")
    inventory_rel = Path(
        "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
    )
    source_hash = _write(old / source_rel, b"source")
    _write(
        old / inventory_rel,
        json.dumps(
            {
                "inventory_version": "full-paper-evidence-1.0.0",
                "paper_id": "PILOT-001",
                "source_pdf": "PMC1.html",
                "evidence_blocks": [],
            }
        ).encode(),
    )
    manifest_path = tmp_path / "pilot.json"
    manifest_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "paper_id": "PILOT-001",
                        "title": "A paper",
                        "doi": "10.1/example",
                        "pmid": "1",
                        "pmcid": "PMC1",
                        "last_checked": "2026-08-06",
                        "publication_metadata": {"publication_year": 2020},
                        "source_access_records": [
                            {
                                "path": source_rel.as_posix(),
                                "sha256": source_hash,
                                "source_kind": "full_text_html",
                            }
                        ],
                        "candidate_artifacts": [
                            {
                                "path": inventory_rel.as_posix(),
                                "artifact_kind": "source_inventory",
                            }
                        ],
                    }
                ]
            }
        )
    )
    output = tmp_path / "bundles"

    summary = prepare_pilot_bundles(manifest_path, (old,), output)
    first = (output / "PILOT-001.json").read_bytes()
    prepare_pilot_bundles(manifest_path, (old,), output)

    assert summary["paid_calls"] == 0
    assert summary["papers"][0]["status"] == "blocked_review"
    assert summary["papers"][0]["evidence_records"] == 0
    assert summary["papers"][0]["experimental_rows"] == 0
    assert first == (output / "PILOT-001.json").read_bytes()
    assert (output / "recovery_manifest.json").is_file()
    assert str(old).encode() not in (output / "recovery_manifest.json").read_bytes()
