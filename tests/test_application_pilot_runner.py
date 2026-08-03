from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import src.extraction.prepare_application_pilot as pilot_preparation
import src.extraction.run_application_pilot as pilot_runner
from src.extraction.full_paper_inventory import FullPaperEvidenceInventory
from src.extraction.prepare_application_pilot import (
    PilotPaper,
    prepare_downstream_gate,
    prepare_map_gate,
)
from src.extraction.run_application_pilot import run_approved_manifest
from tests.test_full_paper_tasks import _inventory as full_inventory
from tests.test_full_paper_tasks import _paper_map
from tests.test_day4_afternoon_selective_vision import _build_task


def _inventory(path: Path, paper_id: str) -> Path:
    inventory = FullPaperEvidenceInventory(
        paper_id=paper_id,
        source_pdf=f"{paper_id}.pdf",
        evidence_blocks=[],
        coverage_diagnostics=[],
        missing_categories=[],
    )
    path.write_text(inventory.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _papers(tmp_path: Path) -> list[PilotPaper]:
    return [
        PilotPaper(
            paper_id=f"P-{index}",
            inventory_path=_inventory(tmp_path / f"inventory-{index}.json", f"P-{index}"),
            model="fake-model",
            token_budget=10_000,
            max_output_tokens=500,
        )
        for index in range(1, 4)
    ]


class _FakeResponses:
    def __init__(self, fail_index: int | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_index = fail_index

    def create(self, **request: object) -> dict[str, object]:
        self.calls.append(request)
        if len(self.calls) == self.fail_index:
            raise RuntimeError("provider unavailable")
        return {"id": f"response-{len(self.calls)}", "output_text": "{}"}


class _FakeProvider:
    def __init__(self, fail_index: int | None = None) -> None:
        self.responses = _FakeResponses(fail_index)


def _empty_paper_map(paper_id: str) -> dict[str, object]:
    return {
        "paper_map_version": "full-paper-map-1.0.0",
        "paper_id": paper_id,
        "formulations": [],
        "payloads": [],
        "common_routes": [],
        "common_species": [],
        "common_models": [],
        "recipient_contexts": [],
        "provisional_experiment_contexts": [],
        "anchor_accounting": {},
        "unresolved_items": [],
    }


def _rewrite_approved_manifest(path: Path, **updates: object) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(updates)
    unsigned = {key: value for key, value in raw.items() if key != "approval_hash"}
    raw["approval_hash"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return raw["approval_hash"]


class _ResponseLike:
    def __init__(self, paper_id: str) -> None:
        self.output_text = json.dumps(_empty_paper_map(paper_id))

    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {"id": "resp-real-shape", "output": []}


class _ResponseLikeProvider:
    def __init__(self, paper_ids: list[str]) -> None:
        self.paper_ids = iter(paper_ids)
        self.calls: list[dict[str, object]] = []
        self.responses = self

    def create(self, **request: object) -> _ResponseLike:
        self.calls.append(request)
        return _ResponseLike(next(self.paper_ids))


def test_map_preparation_makes_zero_provider_calls_and_freezes_three_requests(
    tmp_path: Path,
) -> None:
    provider = _FakeProvider()

    manifest = prepare_map_gate(_papers(tmp_path), tmp_path / "gate-a")

    assert provider.responses.calls == []
    assert manifest.call_count == 3
    assert [row.request_kind for row in manifest.requests] == [
        "paper_map",
        "paper_map",
        "paper_map",
    ]
    assert manifest.total_estimated_tokens == sum(
        row.estimated_input_tokens + row.max_output_tokens
        for row in manifest.requests
    )


def test_runner_continues_after_one_failed_call_without_retry(tmp_path: Path) -> None:
    manifest = prepare_map_gate(_papers(tmp_path), tmp_path / "gate-a")
    provider = _FakeProvider(fail_index=2)

    summary = run_approved_manifest(
        manifest.manifest_path,
        manifest.approval_hash,
        client=provider,
    )

    expected_ids = [row.request_id for row in manifest.requests]
    assert summary.attempted_request_ids == expected_ids
    assert summary.succeeded_request_ids == [expected_ids[0], expected_ids[2]]
    assert summary.failed_request_ids == [expected_ids[1]]
    assert summary.retry_count == 0
    assert summary.repair_count == 0
    assert len(provider.responses.calls) == 3


@pytest.mark.parametrize("mutation", ["wrong_approval", "request", "extra_request"])
def test_runner_rejects_approval_or_request_set_changes_before_first_call(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = prepare_map_gate(_papers(tmp_path), tmp_path / "gate-a")
    approval_hash = manifest.approval_hash
    if mutation == "wrong_approval":
        approval_hash = "0" * 64
    elif mutation == "request":
        manifest.requests[0].request_path.write_text("{}\n", encoding="utf-8")
    else:
        (manifest.request_root / "unapproved.json").write_text("{}\n", encoding="utf-8")
    provider = _FakeProvider()

    with pytest.raises((PermissionError, ValueError), match="approval|request"):
        run_approved_manifest(manifest.manifest_path, approval_hash, client=provider)

    assert provider.responses.calls == []


def test_runner_rejects_missing_exact_token_estimate_before_first_call(
    tmp_path: Path,
) -> None:
    manifest = prepare_map_gate(_papers(tmp_path), tmp_path / "gate-a")
    raw = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    del raw["requests"][1]["estimated_input_tokens"]
    unsigned = {key: value for key, value in raw.items() if key != "approval_hash"}
    raw["approval_hash"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest.manifest_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    provider = _FakeProvider()

    with pytest.raises(ValueError, match="manifest"):
        run_approved_manifest(
            manifest.manifest_path,
            raw["approval_hash"],
            client=provider,
        )

    assert provider.responses.calls == []


def test_map_gate_requires_exactly_three_distinct_papers(tmp_path: Path) -> None:
    papers = _papers(tmp_path)

    with pytest.raises(ValueError, match="exactly three"):
        prepare_map_gate(papers[:2], tmp_path / "too-small")
    with pytest.raises(ValueError, match="distinct"):
        prepare_map_gate([papers[0], papers[0], papers[2]], tmp_path / "duplicate")


def test_downstream_gate_freezes_contexts_and_binds_map_artifact_bytes(
    tmp_path: Path,
) -> None:
    map_artifact = tmp_path / "validated-map.json"
    map_artifact.write_text(
        json.dumps(
            {
                "paper_map": _paper_map(),
                "inventory": full_inventory().model_dump(mode="json"),
                "model": "fake-model",
                "token_budget": 100_000,
                "max_output_tokens": 600,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    expected_source_hash = hashlib.sha256(map_artifact.read_bytes()).hexdigest()

    manifest = prepare_downstream_gate([map_artifact], tmp_path / "gate-b")

    assert manifest.call_count > 0
    assert {row.request_kind for row in manifest.requests} == {"context"}
    assert {row.paper_id for row in manifest.requests} == {"SYNTH-77"}
    assert {
        row.source_artifact_sha256 for row in manifest.requests
    } == {expected_source_hash}

    map_artifact.write_text("{}\n", encoding="utf-8")
    provider = _FakeProvider()
    with pytest.raises(ValueError, match="source artifact changed"):
        run_approved_manifest(
            manifest.manifest_path, manifest.approval_hash, client=provider
        )
    assert provider.responses.calls == []


def test_downstream_gate_rejects_map_bytes_changed_during_task_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    map_artifact = tmp_path / "validated-map.json"
    map_artifact.write_text(
        json.dumps(
            {
                "paper_map": _paper_map(),
                "inventory": full_inventory().model_dump(mode="json"),
                "model": "fake-model",
                "token_budget": 100_000,
                "max_output_tokens": 600,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    real_builder = pilot_preparation.build_context_tasks

    def mutating_builder(*args: object, **kwargs: object) -> object:
        tasks = real_builder(*args, **kwargs)
        map_artifact.write_text("{}\n", encoding="utf-8")
        return tasks

    monkeypatch.setattr(
        pilot_preparation, "build_context_tasks", mutating_builder
    )

    with pytest.raises(ValueError, match="map artifact bytes changed"):
        prepare_downstream_gate([map_artifact], tmp_path / "gate-b")


def test_real_response_shape_persists_computed_output_text_for_gate_b(
    tmp_path: Path,
) -> None:
    papers = _papers(tmp_path)
    gate_a = prepare_map_gate(papers, tmp_path / "gate-a")
    provider = _ResponseLikeProvider([row.paper_id for row in papers])
    summary = run_approved_manifest(
        gate_a.manifest_path, gate_a.approval_hash, client=provider
    )

    gate_b = prepare_downstream_gate(
        list(summary.response_artifact_paths.values()), tmp_path / "gate-b"
    )

    assert gate_b.call_count == 0
    assert len(gate_b.source_bindings) == 6


def test_gate_b_rejects_inventory_changed_after_gate_a_run(tmp_path: Path) -> None:
    papers = _papers(tmp_path)
    gate_a = prepare_map_gate(papers, tmp_path / "gate-a")
    provider = _ResponseLikeProvider([row.paper_id for row in papers])
    summary = run_approved_manifest(
        gate_a.manifest_path, gate_a.approval_hash, client=provider
    )
    inventory = FullPaperEvidenceInventory.model_validate_json(
        papers[0].inventory_path.read_text(encoding="utf-8")
    )
    papers[0].inventory_path.write_text(
        inventory.model_copy(update={"source_pdf": "changed.pdf"}).model_dump_json()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inventory.*hash|source artifact"):
        prepare_downstream_gate(
            list(summary.response_artifact_paths.values()), tmp_path / "gate-b"
        )


def test_map_gate_rejects_inventory_changed_during_request_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    papers = _papers(tmp_path)
    real_builder = pilot_preparation.build_paper_map_request
    changed = False

    def mutating_builder(*args: object, **kwargs: object) -> object:
        nonlocal changed
        prepared = real_builder(*args, **kwargs)
        if not changed:
            changed = True
            papers[0].inventory_path.write_text("{}\n", encoding="utf-8")
        return prepared

    monkeypatch.setattr(
        pilot_preparation, "build_paper_map_request", mutating_builder
    )

    with pytest.raises(ValueError, match="inventory bytes changed"):
        prepare_map_gate(papers, tmp_path / "gate-a")


@pytest.mark.parametrize("root_name", ["request_root", "run_root"])
def test_runner_rejects_roots_escaped_from_manifest_directory(
    tmp_path: Path, root_name: str
) -> None:
    manifest = prepare_map_gate(_papers(tmp_path), tmp_path / "gate-a")
    approval = _rewrite_approved_manifest(
        manifest.manifest_path, **{root_name: str(tmp_path / "escaped")}
    )
    provider = _FakeProvider()

    with pytest.raises(ValueError, match="root"):
        run_approved_manifest(manifest.manifest_path, approval, client=provider)
    assert provider.responses.calls == []


def test_runner_rejects_symlink_request_root_before_provider(
    tmp_path: Path,
) -> None:
    manifest = prepare_map_gate(_papers(tmp_path), tmp_path / "gate-a")
    real_root = tmp_path / "real-requests"
    manifest.request_root.rename(real_root)
    manifest.request_root.symlink_to(real_root, target_is_directory=True)
    provider = _FakeProvider()

    with pytest.raises(ValueError, match="symlink"):
        run_approved_manifest(
            manifest.manifest_path, manifest.approval_hash, client=provider
        )
    assert provider.responses.calls == []


def test_runner_rejects_extra_symlink_request_alias_before_provider(
    tmp_path: Path,
) -> None:
    manifest = prepare_map_gate(_papers(tmp_path), tmp_path / "gate-a")
    (manifest.request_root / "alias.json").symlink_to(
        manifest.requests[0].request_path
    )
    provider = _FakeProvider()

    with pytest.raises(ValueError, match="symlink"):
        run_approved_manifest(
            manifest.manifest_path, manifest.approval_hash, client=provider
        )
    assert provider.responses.calls == []


def test_concurrent_runner_loses_run_marker_before_any_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = prepare_map_gate(_papers(tmp_path), tmp_path / "gate-a")
    clients = [_FakeProvider(), _FakeProvider()]
    barrier = threading.Barrier(2)
    real_loader = pilot_runner._load_and_verify_manifest

    def synchronized_loader(*args: object, **kwargs: object) -> object:
        loaded = real_loader(*args, **kwargs)
        barrier.wait(timeout=5)
        return loaded

    monkeypatch.setattr(
        pilot_runner, "_load_and_verify_manifest", synchronized_loader
    )

    def invoke(client: _FakeProvider) -> object:
        try:
            return run_approved_manifest(
                manifest.manifest_path,
                manifest.approval_hash,
                client=client,
            )
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(invoke, clients))

    assert sum(len(client.responses.calls) for client in clients) == 3
    assert sum(isinstance(result, FileExistsError) for result in results) == 1
    assert sorted(len(client.responses.calls) for client in clients) == [0, 3]


def test_vision_only_gate_b_keeps_map_and_inventory_manifest_bindings(
    tmp_path: Path,
) -> None:
    task = _build_task(tmp_path)
    inventory_path = _inventory(tmp_path / "inventory.json", "GP-TEST")
    map_artifact = tmp_path / "map.json"
    map_artifact.write_text(
        json.dumps(
            {
                "paper_map": _empty_paper_map("GP-TEST"),
                "inventory_path": str(inventory_path),
                "model": "fake-model",
                "selective_vision_task_paths": [
                    str(tmp_path / "tasks" / "GP-TEST" / "VF-VISION" / "task.json")
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = prepare_downstream_gate([map_artifact], tmp_path / "gate-b")

    assert [row.request_kind for row in manifest.requests] == ["selective_vision"]
    assert {row.binding_kind for row in manifest.source_bindings} >= {
        "map_artifact",
        "inventory",
    }
    assert task.paper_id == "GP-TEST"


def test_gate_b_rejects_cross_paper_selective_vision_task(tmp_path: Path) -> None:
    _build_task(tmp_path)
    inventory_path = _inventory(tmp_path / "inventory.json", "OTHER-PAPER")
    map_artifact = tmp_path / "map.json"
    map_artifact.write_text(
        json.dumps(
            {
                "paper_map": _empty_paper_map("OTHER-PAPER"),
                "inventory_path": str(inventory_path),
                "model": "fake-model",
                "selective_vision_task_paths": [
                    str(tmp_path / "tasks" / "GP-TEST" / "VF-VISION" / "task.json")
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="vision.*paper"):
        prepare_downstream_gate([map_artifact], tmp_path / "gate-b")
