import hashlib
import json
from pathlib import Path
import subprocess
from dataclasses import replace

import pytest

from src.database.adapters.pilot_results import build_blocked_pilot_bundle
from src.database.import_contracts import ImportBundle
from src.database.recover_pilot_artifacts import (
    PilotArtifactExpectation,
    _read_regular_file_descriptor_relative,
    prepare_pilot_bundles,
    recover_pilot_sources,
)


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _registered_worktree(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    old = tmp_path / "old-worktree"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True
    )
    _write(repo / "seed", b"seed")
    subprocess.run(["git", "-C", str(repo), "add", "seed"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "old", str(old)],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(old), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, old, commit


def test_recovery_finds_hash_verified_source_and_inventory(tmp_path: Path) -> None:
    repo, root, commit = _registered_worktree(tmp_path)
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
        repo,
        (root,),
    )

    assert result.status == "recovered"
    assert result.source_sha256 == source_hash
    assert result.inventory_sha256 == hashlib.sha256(inventory.read_bytes()).hexdigest()
    assert result.source_logical_path == "data/staging/new_papers/PILOT-001/PMC1.html"
    assert result.inventory_logical_path.endswith("PILOT-001/inventory.json")
    assert result.source_verification == "manifest_sha256_match"
    assert result.inventory_verification == "observed_sha256_unverified"
    assert result.recovery_worktree_root == str(root.resolve())
    assert result.recovery_commit == commit


def test_recovery_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    repo, root, _ = _registered_worktree(tmp_path)
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
        repo,
        (root,),
    )

    assert result.status == "blocked"
    assert result.reason == "source hash mismatch"
    assert result.source_path is None


def test_recovery_rejects_wrong_inventory_paper(tmp_path: Path) -> None:
    repo, root, _ = _registered_worktree(tmp_path)
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
        repo,
        (root,),
    )

    assert result.status == "blocked"
    assert result.reason == "inventory paper mismatch"


@pytest.mark.parametrize(
    "source_path,inventory_path",
    [
        ("data/BENCHMARKS/application_pilot/PILOT-001.html", "x/inventory.json"),
        ("data/staging/new_papers/PILOT-001/PMC1.html", "x/Answer-Key.json"),
        ("data/staging/new_papers/PILOT-001/PMC1.html", "raw_PROVIDER/Inventory.json"),
        ("data/staging/new_papers/PILOT-001/PMC1.html", "run/Responses/inventory.json"),
    ],
)
def test_recovery_refuses_forbidden_artifact_path_variants(
    source_path: str, inventory_path: str
) -> None:
    with pytest.raises(ValueError, match="forbidden|expected PILOT"):
        PilotArtifactExpectation(
            paper_id="PILOT-001",
            source_relative_path=Path(source_path),
            source_sha256="0" * 64,
            inventory_relative_path=Path(inventory_path),
        )


def test_recovery_rejects_arbitrary_unregistered_root(tmp_path: Path) -> None:
    repo, _, _ = _registered_worktree(tmp_path)
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()
    with pytest.raises(ValueError, match="registered git worktree"):
        recover_pilot_sources(
            PilotArtifactExpectation(
                paper_id="PILOT-001",
                source_relative_path=Path(
                    "data/staging/new_papers/PILOT-001/PMC1.html"
                ),
                source_sha256="0" * 64,
                inventory_relative_path=Path(
                    "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
                ),
            ),
            repo,
            (arbitrary,),
        )


def test_recovery_rejects_inventory_symlink_to_outside_content(
    tmp_path: Path,
) -> None:
    repo, root, _ = _registered_worktree(tmp_path)
    source_rel = Path("data/staging/new_papers/PILOT-001/PMC1.html")
    inventory_rel = Path(
        "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
    )
    source_hash = _write(root / source_rel, b"source")
    outside = tmp_path / "Answer-Key.json"
    _write(
        outside,
        json.dumps(
            {
                "inventory_version": "full-paper-evidence-1.0.0",
                "paper_id": "PILOT-001",
                "source_pdf": "PMC1.html",
                "evidence_blocks": [],
            }
        ).encode(),
    )
    inventory = root / inventory_rel
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.symlink_to(outside)

    result = recover_pilot_sources(
        PilotArtifactExpectation(
            paper_id="PILOT-001",
            source_relative_path=source_rel,
            source_sha256=source_hash,
            inventory_relative_path=inventory_rel,
        ),
        repo,
        (root,),
    )

    assert result.status == "blocked"
    assert "artifact path rejected" in result.reason


def test_recovery_rejects_source_symlink_to_outside_content(tmp_path: Path) -> None:
    repo, root, _ = _registered_worktree(tmp_path)
    source_rel = Path("data/staging/new_papers/PILOT-001/PMC1.html")
    inventory_rel = Path(
        "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
    )
    outside = tmp_path / "outside.html"
    expected_hash = _write(outside, b"source")
    source = root / source_rel
    source.parent.mkdir(parents=True, exist_ok=True)
    source.symlink_to(outside)
    _write(
        root / inventory_rel,
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
            source_relative_path=source_rel,
            source_sha256=expected_hash,
            inventory_relative_path=inventory_rel,
        ),
        repo,
        (root,),
    )

    assert result.status == "blocked"
    assert "artifact path rejected" in result.reason


def test_adapter_uses_recovery_bound_inventory_bytes_after_disk_mutation(
    tmp_path: Path,
) -> None:
    repo, root, _ = _registered_worktree(tmp_path)
    source_rel = Path("data/staging/new_papers/PILOT-001/PMC1.html")
    inventory_rel = Path(
        "data/staging/extraction/application_pilot/PILOT-001/inventory.json"
    )
    source_hash = _write(root / source_rel, b"source")
    inventory_path = root / inventory_rel
    _write(
        inventory_path,
        json.dumps(
            {
                "inventory_version": "full-paper-evidence-1.0.0",
                "paper_id": "PILOT-001",
                "source_pdf": "PMC1.html",
                "evidence_blocks": [{"evidence_id": "FPE-1", "text": "original"}],
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
        repo,
        (root,),
    )
    _write(
        inventory_path,
        json.dumps(
            {
                "inventory_version": "full-paper-evidence-1.0.0",
                "paper_id": "PILOT-001",
                "source_pdf": "PMC1.html",
                "evidence_blocks": [{"evidence_id": "FPE-1", "text": "mutated"}],
            }
        ).encode(),
    )
    entry = {
        "paper_id": "PILOT-001",
        "title": "A paper",
        "publication_metadata": {"publication_year": 2020},
    }

    bundle = build_blocked_pilot_bundle(recovery, entry)

    assert bundle.evidence[0].evidence_text == "original"
    with pytest.raises(ValueError, match="does not match recorded SHA-256"):
        build_blocked_pilot_bundle(
            replace(recovery, inventory_bytes=b"tampered"), entry
        )


def test_descriptor_relative_read_survives_intermediate_directory_swap(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    _write(root / "safe/file.txt", b"inside")
    _write(outside / "file.txt", b"outside")
    swapped = False

    def swap_after_safe_directory_open(component_index: int) -> None:
        nonlocal swapped
        if component_index != 1 or swapped:
            return
        (root / "safe").rename(root / "held-safe")
        (root / "safe").symlink_to(outside, target_is_directory=True)
        swapped = True

    content = _read_regular_file_descriptor_relative(
        root,
        Path("safe/file.txt"),
        before_component_open=swap_after_safe_directory_open,
    )

    assert swapped
    assert content == b"inside"


def test_descriptor_relative_read_fails_closed_without_openat_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "file.txt", b"content")
    monkeypatch.setattr("os.supports_dir_fd", set())

    with pytest.raises(ValueError, match="unsupported"):
        _read_regular_file_descriptor_relative(tmp_path, Path("file.txt"))


def test_adapter_preserves_source_evidence_without_unsupported_experimental_rows(
    tmp_path: Path,
) -> None:
    repo, root, _ = _registered_worktree(tmp_path)
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
        repo,
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
    assert round_trip.evidence[0].extraction_confidence == "unverified_recovery"
    assert round_trip.reviews[0].status == "blocked"
    assert round_trip.reviews[0].reason_code == "recovered_inventory_unverified"
    assert {artifact.source_kind for artifact in round_trip.artifacts} == {
        "html",
        "source_inventory",
    }


def test_prepare_writes_deterministic_bundle_and_recovery_manifest(tmp_path: Path) -> None:
    repo, old, _ = _registered_worktree(tmp_path)
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

    summary = prepare_pilot_bundles(manifest_path, repo, (old,), output)
    first = (output / "PILOT-001.json").read_bytes()
    prepare_pilot_bundles(manifest_path, repo, (old,), output)

    assert summary["paid_calls"] == 0
    assert summary["papers"][0]["status"] == "blocked_review"
    assert summary["papers"][0]["evidence_records"] == 0
    assert summary["papers"][0]["experimental_rows"] == 0
    assert first == (output / "PILOT-001.json").read_bytes()
    assert (output / "recovery_manifest.json").is_file()
    recovery_manifest = (output / "recovery_manifest.json").read_text()
    assert str(old.resolve()) in recovery_manifest
    assert "observed_sha256_unverified" in recovery_manifest
