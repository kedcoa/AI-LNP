from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from src.extraction.evaluate_full_paper_benchmark import evaluate
from src.extraction import run_np002_selective_outcomes as selective


def _read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_prepare_creates_two_source_derived_immutable_figure_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing figure task or wrong source cross-product must fail preflight."""
    class ProviderMustNotRun:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("preflight must not construct a provider client")

    monkeypatch.setattr(selective, "OpenAI", ProviderMustNotRun, raising=False)

    manifest = selective.prepare(tmp_path, model="test-vision-model")

    assert manifest["provider_calls"] == 0
    assert len(manifest["requests"]) == 2
    tasks = {_read(row["task_path"])["figure"]: _read(row["task_path"]) for row in manifest["requests"]}
    assert set(tasks) == {"Figure 2", "Figure 4"}
    assert len({row["slot_id"] for row in tasks["Figure 2"]["slots"]}) == 6
    assert len({row["slot_id"] for row in tasks["Figure 4"]["slots"]}) == 12
    assert {row["dose"] for row in tasks["Figure 4"]["slots"]} == {0.3, 1.0}
    assert all(row["payload"] == "Cre mRNA" for row in tasks["Figure 4"]["slots"])
    assert all(Path(row["crop_path"]).is_file() for row in manifest["requests"])
    assert all(row["crop_sha256"] for row in manifest["requests"])
    assert [row["max_output_tokens"] for row in manifest["requests"]] == [4000, 6000]
    assert {
        row["source_id"] for row in tasks["Figure 4"]["evidence"]
    } >= {"Fig4", "Par14", "Par15", "Par23"}


def test_prepare_persists_deterministic_request_hashes_without_gold_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing canonical request bytes or reading an answer key must be caught."""
    original_read_text = Path.read_text

    def reject_gold(self: Path, *args: object, **kwargs: object) -> str:
        if "benchmarks/full_paper" in self.as_posix() or self.name == "NP-002.json":
            raise AssertionError("preflight must not read the hidden answer key")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_gold)
    manifest = selective.prepare(tmp_path, model="test-vision-model")

    for row in manifest["requests"]:
        request_bytes = Path(row["request_path"]).read_bytes()
        assert row["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()
        assert row["request_bytes"] == len(request_bytes)
        request = json.loads(request_bytes)
        prompt = request["input"][0]["content"]
        assert "visually estimated" in prompt
        assert "qualitative" in prompt


def test_prepare_embeds_strict_dynamic_schema_for_exact_slot_accounting(
    tmp_path: Path,
) -> None:
    """A permissive API schema could admit invented or unaccounted visual rows."""
    manifest = selective.prepare(tmp_path, model="test-vision-model")

    for row in manifest["requests"]:
        request = _read(row["request_path"])
        schema = request["text"]["format"]["schema"]
        accounting = schema["properties"]["slot_accounting"]
        task = _read(row["task_path"])
        slot_ids = [slot["slot_id"] for slot in task["slots"]]
        assert accounting["additionalProperties"] is False
        assert accounting["required"] == slot_ids
        outcome_item = schema["properties"]["outcomes"]["items"]
        assert outcome_item["additionalProperties"] is False
        assert "exact_printed_support" in outcome_item["required"]


@pytest.fixture
def figure_2_task() -> dict:
    return {
        "figure": "Figure 2",
        "allowed_evidence_ids": ["FIG2-CROP", "FIG2-CAPTION", "FIG2-RESULTS", "FIG2-METHODS"],
        "allowed_exact_numeric_outcomes": [],
        "evidence": [
            {
                "evidence_id": "FIG2-CROP",
                "source_id": "Figure 2 crop",
                "text": "The Figure 2 bars are unlabeled.",
            },
            {
                "evidence_id": "FIG2-CAPTION",
                "source_id": "Figure 2 caption",
                "text": "DNA delivery is shown for major liver cell types.",
            },
        ],
        "slots": [
            {
                "slot_id": "fig2-mc3-kupffer",
                "formulation": "MC3",
                "payload": "QUANT DNA",
                "dose": None,
                "recipient_cell": "Kupffer cells",
                "assay": "cellular DNA accumulation",
                "endpoint": "QUANT DNA accumulation",
            }
        ],
    }


def _valid_response() -> dict:
    slot = {
        "slot_id": "fig2-mc3-kupffer",
        "formulation": "MC3",
        "payload": "QUANT DNA",
        "dose": None,
        "recipient_cell": "Kupffer cells",
        "assay": "cellular DNA accumulation",
        "endpoint": "QUANT DNA accumulation",
    }
    return {
        "figure": "Figure 2",
        "outcomes": [
            {
                **slot,
                "qualitative_outcome": "higher accumulation than cKK-E12",
                "comparison_target": "cKK-E12",
                "significance_wording": None,
                "numeric_value": None,
                "numeric_unit": None,
                "exact_printed_support": None,
                "figure_panel": "2A",
                "evidence_ids": ["FIG2-CROP", "FIG2-CAPTION"],
                "confidence": "high",
            }
        ],
        "slot_accounting": {
            "fig2-mc3-kupffer": {
                "disposition": "extracted",
                "outcome_slot_id": "fig2-mc3-kupffer",
                "explanation": "The panel reports the comparison.",
                "evidence_ids": ["FIG2-CROP"],
            }
        },
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda response: response["slot_accounting"].clear(), "accounting"),
        (
            lambda response: response["slot_accounting"].update(
                {"invented-slot": response["slot_accounting"]["fig2-mc3-kupffer"]}
            ),
            "accounting",
        ),
        (
            lambda response: response["outcomes"].append(response["outcomes"][0].copy()),
            "exactly once",
        ),
        (
            lambda response: response["outcomes"][0].update({"formulation": "cKK-E12"}),
            "identity",
        ),
        (
            lambda response: response["outcomes"][0].update({"evidence_ids": ["unknown"]}),
            "evidence",
        ),
        (
            lambda response: response["outcomes"][0].update(
                {"numeric_value": 1.2, "numeric_unit": "a.u."}
            ),
            "exact_printed_support",
        ),
        (
            lambda response: response["slot_accounting"]["fig2-mc3-kupffer"].update(
                {"disposition": "not_explicit", "outcome_slot_id": "fig2-mc3-kupffer"}
            ),
            "not_explicit",
        ),
    ],
)
def test_validate_visual_response_rejects_adversarial_slot_contract_violations(
    figure_2_task: dict,
    mutation,
    message: str,
) -> None:
    """Any lossy, invented, relinked, or estimated result must be rejected."""
    response = _valid_response()
    mutation(response)

    with pytest.raises(ValueError, match=message):
        selective.validate_visual_response(response, figure_2_task)


def test_validate_visual_response_accepts_exact_source_grounded_accounting(
    figure_2_task: dict,
) -> None:
    """The validator must accept one fully accounted qualitative visual outcome."""
    selective.validate_visual_response(_valid_response(), figure_2_task)


def _allow_exact_numeric_outcome(figure_2_task: dict) -> None:
    figure_2_task["evidence"].append(
        {
            "evidence_id": "FIG2-PRINTED",
            "source_id": "Figure 2 data label",
            "text": "The printed outcome label is 1.20 copies/cell.",
        }
    )
    figure_2_task["allowed_evidence_ids"].append("FIG2-PRINTED")
    figure_2_task["allowed_exact_numeric_outcomes"] = [
        {
            "numeric_value": 1.2,
            "numeric_unit": "copies/cell",
            "evidence_id": "FIG2-PRINTED",
            "printed_support": "1.20 copies/cell",
        }
    ]


def _set_numeric_outcome(
    response: dict,
    value: float,
    support: str,
    evidence_ids: list[str],
) -> None:
    response["outcomes"][0].update(
        {
            "numeric_value": value,
            "numeric_unit": "copies/cell",
            "exact_printed_support": support,
            "evidence_ids": evidence_ids,
        }
    )


def test_validate_visual_response_rejects_model_fabricated_numeric_support(
    figure_2_task: dict,
) -> None:
    """Model prose cannot turn an unlabeled bar into an exact printed outcome."""
    response = _valid_response()
    _set_numeric_outcome(
        response,
        123.0,
        "123.0 is printed beside the bar.",
        ["FIG2-CROP"],
    )

    with pytest.raises(ValueError, match="allowlist"):
        selective.validate_visual_response(response, figure_2_task)


def test_validate_visual_response_rejects_numeric_value_missing_from_allowlist(
    figure_2_task: dict,
) -> None:
    """A different value than the source-derived printed label must be rejected."""
    _allow_exact_numeric_outcome(figure_2_task)
    response = _valid_response()
    _set_numeric_outcome(
        response, 1.3, "1.30 copies/cell", ["FIG2-CROP", "FIG2-PRINTED"]
    )

    with pytest.raises(ValueError, match="allowlist"):
        selective.validate_visual_response(response, figure_2_task)


def test_validate_visual_response_accepts_allowlisted_cited_printed_numeric_value(
    figure_2_task: dict,
) -> None:
    """A future explicit data label is accepted only through the local allowlist."""
    _allow_exact_numeric_outcome(figure_2_task)
    response = _valid_response()
    _set_numeric_outcome(
        response, 1.2, "1.20 copies/cell", ["FIG2-CROP", "FIG2-PRINTED"]
    )

    selective.validate_visual_response(response, figure_2_task)


def _response_for_task(task: dict, *, extracted_slot_index: int | None = None) -> dict:
    """Make a complete source-envelope response without a provider call."""
    outcomes = []
    accounting = {}
    for index, slot in enumerate(task["slots"]):
        slot_id = slot["slot_id"]
        if index == extracted_slot_index:
            outcomes.append(
                {
                    **slot,
                    "qualitative_outcome": "higher than the matched comparator",
                    "comparison_target": "matched comparator",
                    "significance_wording": "significant",
                    "numeric_value": None,
                    "numeric_unit": None,
                    "exact_printed_support": None,
                    "figure_panel": "A",
                    "evidence_ids": [task["crop_evidence_id"]],
                    "confidence": "high",
                }
            )
            accounting[slot_id] = {
                "disposition": "extracted",
                "outcome_slot_id": slot_id,
                "explanation": "The crop explicitly shows this comparison.",
                "evidence_ids": [task["crop_evidence_id"]],
            }
        else:
            accounting[slot_id] = {
                "disposition": "not_explicit",
                "outcome_slot_id": None,
                "explanation": "No source-supported qualitative comparison is visible.",
                "evidence_ids": [task["crop_evidence_id"]],
            }
    return {"figure": task["figure"], "outcomes": outcomes, "slot_accounting": accounting}


class _FakeUsage:
    def model_dump(self, *, mode: str) -> dict[str, int]:
        assert mode == "json"
        return {"input_tokens": 17, "output_tokens": 11, "total_tokens": 28}


class _FakeProviderResponse:
    def __init__(self, payload: dict) -> None:
        self.id = "fake-response"
        self.model = "fake-vision-model"
        self.usage = _FakeUsage()
        self.output_text = json.dumps(payload)

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {"id": self.id, "model": self.model, "output_text": self.output_text}


class _FakeResponses:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def create(self, **request: Any) -> object:
        self.calls.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = _FakeResponses(responses)


def _prepared_manifest(tmp_path: Path) -> tuple[dict, Path]:
    manifest = selective.prepare(tmp_path / "preflight", model="fake-vision-model")
    return manifest, tmp_path / "preflight" / "NP-002" / "manifest.json"


def _approved_responses(manifest: dict) -> list[_FakeProviderResponse]:
    return [
        _FakeProviderResponse(
            _response_for_task(_read(row["task_path"]), extracted_slot_index=0)
        )
        for row in manifest["requests"]
    ]


def test_run_approved_requires_the_exact_hash_for_each_immutable_request(
    tmp_path: Path,
) -> None:
    """A stale or substituted approval must stop before any paid dispatch."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    client = _FakeClient(_approved_responses(manifest))
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    approvals["Figure 4"] = "0" * 64

    with pytest.raises(ValueError, match="approval"):
        selective.run_approved(manifest_path, approvals, tmp_path / "run", client)

    assert client.responses.calls == []


def test_run_approved_dispatches_and_validates_figure_2_before_figure_4(
    tmp_path: Path,
) -> None:
    """A later figure cannot be sent until the prior response is locally valid."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    client = _FakeClient(_approved_responses(manifest))
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}

    result = selective.run_approved(manifest_path, approvals, tmp_path / "run", client)

    assert result["paid_api_requests"] == 2
    assert [
        json.loads(call["input"][1]["content"][0]["text"])["figure"]
        for call in client.responses.calls
    ] == ["Figure 2", "Figure 4"]
    for row in manifest["requests"]:
        run_dir = tmp_path / "run" / "NP-002" / _read(row["task_path"])["slug"]
        assert (run_dir / "invocation_started.json").is_file()
        assert (run_dir / "response.json").is_file()
        assert (run_dir / "usage.json").is_file()
        assert (run_dir / "validated_response.json").is_file()


def test_run_approved_refuses_duplicate_markers_and_stops_after_figure_2_failure(
    tmp_path: Path,
) -> None:
    """A provider failure is one terminal invocation, never an automatic retry."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    client = _FakeClient([RuntimeError("provider unavailable")])

    with pytest.raises(RuntimeError, match="provider unavailable"):
        selective.run_approved(manifest_path, approvals, tmp_path / "run", client)
    with pytest.raises(FileExistsError, match="already started"):
        selective.run_approved(manifest_path, approvals, tmp_path / "run", client)

    assert len(client.responses.calls) == 1
    assert not (tmp_path / "run" / "NP-002" / "figure_4").exists()


def test_run_approved_rejects_changed_crop_before_dispatch(
    tmp_path: Path,
) -> None:
    """A request cannot run when the task's committed visual evidence changed."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    crop_path = Path(manifest["requests"][0]["crop_path"])
    crop_path.write_bytes(crop_path.read_bytes() + b"changed")
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    client = _FakeClient(_approved_responses(manifest))

    with pytest.raises(ValueError, match="crop"):
        selective.run_approved(manifest_path, approvals, tmp_path / "run", client)

    assert client.responses.calls == []


def test_merge_validated_attaches_qualitative_rows_to_exact_arms_without_gold_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Visual outcomes retain arm identity while shared map facts stay paper-level."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    selective.run_approved(
        manifest_path,
        approvals,
        tmp_path / "run",
        _FakeClient(_approved_responses(manifest)),
    )
    original_read_text = Path.read_text

    def reject_hidden_key(self: Path, *args: object, **kwargs: object) -> str:
        if "benchmarks/full_paper" in self.as_posix() or self.name == "NP-002.json":
            raise AssertionError("merger must not read the hidden answer key")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_hidden_key)
    output_path = tmp_path / "merged" / "merged_extraction.json"
    artifact = selective.merge_validated(manifest_path, tmp_path / "run", output_path)

    assert output_path.is_file()
    assert artifact["paper_id"] == "NP-002"
    assert len(artifact["outcomes"]) == 2
    for outcome in artifact["outcomes"]:
        assert outcome["outcome_value"]["value"] is None
        assert outcome["outcome_unit"]["value"] is None
        assert outcome["qualitative_outcome"]["value"] == "higher than the matched comparator"
        assert outcome["evidence_ids"]
        experiment = next(
            row for row in artifact["experiments"] if row["experiment_id"] == outcome["experiment_id"]
        )
        assert experiment["formulation_id"] in {"FORM::MC3_LNP", "FORM::cKK-E12_LNP"}
        assert experiment["payload_name"]["value"] in {"QUANT DNA", "Cre mRNA"}
        assert experiment["delivery_recipient_cell"]["value"] in {
            "Kupffer cells",
            "liver endothelial cells",
            "hepatocytes",
        }
        assert experiment["dose"]["value"] in {0.3, 1.0}
    assert all("ratios" not in experiment for experiment in artifact["experiments"])
    assert artifact["paper_map"]["formulations"][0]["ratios"]
    synthetic_key = tmp_path / "synthetic-answer-key.json"
    synthetic_key.write_text(
        json.dumps({"paper_id": "NP-002", "shared_facts": [], "experiment_facts": []}),
        encoding="utf-8",
    )
    assert evaluate(output_path.parent, synthetic_key).total_gold_fact_count == 0


def _resign_manifest(manifest_path: Path, manifest: dict) -> None:
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _resign_task(task_path: Path, task: dict) -> None:
    unsigned = dict(task)
    unsigned.pop("task_sha256", None)
    task["task_sha256"] = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")


def test_run_approved_rejects_resigned_task_that_differs_from_approved_request(
    tmp_path: Path,
) -> None:
    """Re-signing local task metadata cannot change the approved validation envelope."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    first = manifest["requests"][0]
    task_path = Path(first["task_path"])
    task = _read(str(task_path))
    task["slots"][0]["endpoint"] = "tampered endpoint"
    _resign_task(task_path, task)
    first["task_sha256"] = task["task_sha256"]
    _resign_manifest(manifest_path, manifest)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    client = _FakeClient(_approved_responses(manifest))

    with pytest.raises(ValueError, match="approved request.*task envelope"):
        selective.run_approved(manifest_path, approvals, tmp_path / "run", client)

    assert client.responses.calls == []


def test_run_approved_rejects_resigned_crop_that_differs_from_approved_image(
    tmp_path: Path,
) -> None:
    """Re-signing a replacement crop cannot detach local validation from the prompt image."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    first = manifest["requests"][0]
    task_path = Path(first["task_path"])
    task = _read(str(task_path))
    crop_path = Path(first["crop_path"])
    crop_path.write_bytes(crop_path.read_bytes() + b"replacement")
    crop_sha = hashlib.sha256(crop_path.read_bytes()).hexdigest()
    task["crop_sha256"] = crop_sha
    _resign_task(task_path, task)
    first["crop_sha256"] = crop_sha
    first["task_sha256"] = task["task_sha256"]
    _resign_manifest(manifest_path, manifest)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    client = _FakeClient(_approved_responses(manifest))

    with pytest.raises(ValueError, match="approved request.*crop"):
        selective.run_approved(manifest_path, approvals, tmp_path / "run", client)

    assert client.responses.calls == []


def test_merge_validated_rejects_response_changed_after_run_validation(
    tmp_path: Path,
) -> None:
    """Schema-valid post-run edits cannot replace the response that was validated."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    selective.run_approved(
        manifest_path,
        approvals,
        tmp_path / "run",
        _FakeClient(_approved_responses(manifest)),
    )
    response_path = tmp_path / "run" / "NP-002" / "figure_2" / "validated_response.json"
    response = _read(str(response_path))
    response["outcomes"][0]["qualitative_outcome"] = "post-validation invention"
    response_path.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="response checksum"):
        selective.merge_validated(
            manifest_path,
            tmp_path / "run",
            tmp_path / "merged" / "merged_extraction.json",
        )


def test_merge_validated_requires_completed_ordered_run_manifest_bound_to_preflight(
    tmp_path: Path,
) -> None:
    """A merger accepts only the recorded Figure 2 then Figure 4 completion."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    selective.run_approved(
        manifest_path,
        approvals,
        tmp_path / "run",
        _FakeClient(_approved_responses(manifest)),
    )
    run_manifest_path = tmp_path / "run" / "NP-002" / "manifest.json"
    run_manifest = _read(str(run_manifest_path))
    run_manifest["requests"] = list(reversed(run_manifest["requests"]))
    run_manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Figure 2 then Figure 4"):
        selective.merge_validated(
            manifest_path,
            tmp_path / "run",
            tmp_path / "merged" / "merged_extraction.json",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest.update({"status": "failed"}), "validated selective-vision"),
        (
            lambda manifest: manifest["requests"][0].update({"request_sha256": "0" * 64}),
            "request hashes",
        ),
    ],
)
def test_merge_validated_rejects_untrusted_run_manifest(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    """Completion state and both request hashes are provenance, not optional metadata."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    selective.run_approved(
        manifest_path,
        approvals,
        tmp_path / "run",
        _FakeClient(_approved_responses(manifest)),
    )
    run_manifest_path = tmp_path / "run" / "NP-002" / "manifest.json"
    run_manifest = _read(str(run_manifest_path))
    mutation(run_manifest)
    run_manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        selective.merge_validated(
            manifest_path,
            tmp_path / "run",
            tmp_path / "merged" / "merged_extraction.json",
        )


def test_run_approved_records_zero_paid_calls_for_predispatch_marker_failure(
    tmp_path: Path,
) -> None:
    """A local exclusive-marker conflict occurs before the paid dispatch boundary."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    marker = tmp_path / "run" / "NP-002" / "figure_2" / "invocation_started.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("already started\n", encoding="utf-8")
    client = _FakeClient(_approved_responses(manifest))

    with pytest.raises(FileExistsError, match="already started"):
        selective.run_approved(manifest_path, approvals, tmp_path / "run", client)

    assert client.responses.calls == []
    assert _read(str(tmp_path / "run" / "NP-002" / "manifest.json"))["paid_api_requests"] == 0
