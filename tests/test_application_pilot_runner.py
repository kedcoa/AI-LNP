from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import src.extraction.prepare_application_pilot as pilot_preparation
from src.extraction.full_paper_inventory import FullPaperEvidenceInventory
from src.extraction.prepare_application_pilot import (
    PilotPaper,
    prepare_downstream_gate,
    prepare_map_gate,
)
from src.extraction.run_application_pilot import run_approved_manifest
from tests.test_full_paper_tasks import _inventory as full_inventory
from tests.test_full_paper_tasks import _paper_map


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
