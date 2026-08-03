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


def test_prepare_builds_six_source_supported_experiments_and_binds_all_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collapsing the two Figure 4 doses would attach outcomes to the wrong arm."""
    original_read_text = Path.read_text

    def reject_gold(self: Path, *args: object, **kwargs: object) -> str:
        if "benchmarks/full_paper" in self.as_posix() or self.name == "NP-002.json":
            raise AssertionError("experiment inventory must not read the answer key")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_gold)
    manifest = selective.prepare(tmp_path, model="test-vision-model")
    tasks = [_read(row["task_path"]) for row in manifest["requests"]]

    expected = {
        ("MC3", "QUANT DNA", 0.3),
        ("cKK-E12", "QUANT DNA", 0.3),
        ("MC3", "Cre mRNA", 0.3),
        ("cKK-E12", "Cre mRNA", 0.3),
        ("MC3", "Cre mRNA", 1.0),
        ("cKK-E12", "Cre mRNA", 1.0),
    }
    inventory = manifest["experiment_inventory"]
    assert {
        (arm["formulation"], arm["payload"], arm["dose"]["value"])
        for arm in inventory.values()
    } == expected
    slots = [slot for task in tasks for slot in task["slots"]]
    assert len(slots) == 18
    assert len({slot["experiment_id"] for slot in slots}) == 6
    for slot in slots:
        arm = inventory[slot["experiment_id"]]
        assert slot["formulation"] == arm["formulation"]
        assert slot["payload"] == arm["payload"]
        assert slot["dose"] == arm["dose"]["value"]
    assert {
        inventory[slot["experiment_id"]]["dose"]["value"]
        for slot in slots
        if slot["payload"] == "Cre mRNA"
    } == {0.3, 1.0}


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
        assert "experiment_id" in outcome_item["required"]


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
                "experiment_id": "EXP::NP002::QUANT::MC3::0.3",
                "formulation": "MC3",
                "payload": "QUANT DNA",
                "dose": 0.3,
                "recipient_cell": "Kupffer cells",
                "assay": "cellular DNA accumulation",
                "endpoint": "QUANT DNA accumulation",
            }
        ],
    }


def _valid_response() -> dict:
    slot = {
        "slot_id": "fig2-mc3-kupffer",
        "experiment_id": "EXP::NP002::QUANT::MC3::0.3",
        "formulation": "MC3",
        "payload": "QUANT DNA",
        "dose": 0.3,
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


def test_validate_visual_response_rejects_swapped_experiment_identity(
    figure_2_task: dict,
) -> None:
    """A model cannot move a valid candidate onto a different experiment."""
    response = _valid_response()
    response["outcomes"][0]["experiment_id"] = "EXP::NP002::QUANT::cKKE12::0.3"

    with pytest.raises(ValueError, match="experiment identity"):
        selective.validate_visual_response(response, figure_2_task)


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


class _UnserializableProviderResponse:
    def __init__(self) -> None:
        self.usage = _FakeUsage()
        self.output_text = "{}"


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


def test_run_approved_rejects_resigned_task_that_widens_evidence_authorization(
    tmp_path: Path,
) -> None:
    """A response cannot cite an ID that was absent from the approved evidence packet."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    first = manifest["requests"][0]
    task_path = Path(first["task_path"])
    task = _read(str(task_path))
    task["allowed_evidence_ids"].append("FABRICATED-EVIDENCE-ID")
    _resign_task(task_path, task)
    first["task_sha256"] = task["task_sha256"]
    _resign_manifest(manifest_path, manifest)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    client = _FakeClient(_approved_responses(manifest))

    with pytest.raises(ValueError, match="allowed evidence"):
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


def test_run_approved_recovers_qualitative_quote_misplaced_as_numeric_support(
    tmp_path: Path,
) -> None:
    """A quote on an otherwise qualitative row must not turn into a numeric claim."""
    manifest, manifest_path = _prepared_manifest(tmp_path)
    figure_2 = _response_for_task(_read(manifest["requests"][0]["task_path"]), extracted_slot_index=0)
    figure_2["outcomes"][0]["exact_printed_support"] = "the Results state that cKK-E12 was lower than MC3"
    figure_4 = _response_for_task(_read(manifest["requests"][1]["task_path"]), extracted_slot_index=0)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}

    selective.run_approved(
        manifest_path,
        approvals,
        tmp_path / "run",
        _FakeClient([_FakeProviderResponse(figure_2), _FakeProviderResponse(figure_4)]),
    )

    validated = _read(str(tmp_path / "run" / "NP-002" / "figure_2" / "validated_response.json"))
    raw_trial = _read(str(tmp_path / "run" / "NP-002" / "figure_2" / "trial_response.json"))
    assert raw_trial["outcomes"][0]["exact_printed_support"] == "the Results state that cKK-E12 was lower than MC3"
    assert validated["outcomes"][0]["numeric_value"] is None
    assert validated["outcomes"][0]["numeric_unit"] is None
    assert validated["outcomes"][0]["exact_printed_support"] is None


def _failed_figure_2_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, Path, dict[str, str], dict, str]:
    manifest, manifest_path = _prepared_manifest(tmp_path)
    approvals = {row["figure"]: row["request_sha256"] for row in manifest["requests"]}
    figure_2_entry = manifest["requests"][0]
    figure_2_task = _read(figure_2_entry["task_path"])
    trial = _response_for_task(figure_2_task, extracted_slot_index=0)
    trial["outcomes"][0]["exact_printed_support"] = "qualitative Figure 2 Results quote"

    def leave_qualitative_support_unnormalized(response: dict) -> dict:
        return json.loads(json.dumps(response))

    with monkeypatch.context() as patch:
        patch.setattr(
            selective,
            "_normalize_qualitative_response",
            leave_qualitative_support_unnormalized,
        )
        with pytest.raises(ValueError, match="exact_printed_support"):
            selective.run_approved(
                manifest_path,
                approvals,
                tmp_path / "run",
                _FakeClient([_FakeProviderResponse(trial)]),
            )

    raw_path = tmp_path / "run" / "NP-002" / "figure_2" / "response.json"
    raw_sha256 = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    return manifest, manifest_path, approvals, trial, raw_sha256


def test_resume_failed_figure_2_validates_saved_artifacts_then_dispatches_only_figure_4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-call failed run can resume only after proving its saved Figure 2 provenance."""
    manifest, manifest_path, approvals, _, raw_sha256 = _failed_figure_2_run(
        tmp_path, monkeypatch
    )
    figure_4 = _response_for_task(_read(manifest["requests"][1]["task_path"]), extracted_slot_index=0)
    client = _FakeClient([_FakeProviderResponse(figure_4)])

    result = selective.resume_failed_figure_2(
        manifest_path,
        approvals,
        tmp_path / "run",
        figure_2_raw_response_sha256=raw_sha256,
        client=client,
    )

    assert result["paid_api_requests"] == 2
    assert len(client.responses.calls) == 1
    assert json.loads(client.responses.calls[0]["input"][1]["content"][0]["text"])["figure"] == "Figure 4"
    validated = _read(str(tmp_path / "run" / "NP-002" / "figure_2" / "validated_response.json"))
    assert validated["outcomes"][0]["exact_printed_support"] is None
    provenance = _read(str(tmp_path / "run" / "NP-002" / "figure_2" / "recovery_provenance.json"))
    assert provenance["raw_response_sha256"]
    assert provenance["trial_response_sha256"]
    assert [row["figure"] for row in result["requests"]] == ["Figure 2", "Figure 4"]


def test_resume_failed_figure_2_ignores_replaceable_trial_and_parses_authenticated_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutable trial file cannot override output parsed from the approved raw response."""
    manifest, manifest_path, approvals, trial, raw_sha256 = _failed_figure_2_run(
        tmp_path, monkeypatch
    )
    trial["outcomes"][0]["qualitative_outcome"] = "tampered after provider response"
    trial_path = tmp_path / "run" / "NP-002" / "figure_2" / "trial_response.json"
    trial_path.write_text(json.dumps(trial), encoding="utf-8")
    figure_4 = _response_for_task(
        _read(manifest["requests"][1]["task_path"]), extracted_slot_index=0
    )

    result = selective.resume_failed_figure_2(
        manifest_path,
        approvals,
        tmp_path / "run",
        figure_2_raw_response_sha256=raw_sha256,
        client=_FakeClient([_FakeProviderResponse(figure_4)]),
    )

    assert result["requests"][0]["raw_response_sha256"] == raw_sha256
    recovered_trial = _read(str(trial_path))
    assert recovered_trial["outcomes"][0]["qualitative_outcome"] == "higher than the matched comparator"


def test_resume_failed_figure_2_requires_explicit_raw_response_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request approvals alone cannot authorize recovery from a mutable provider artifact."""
    manifest, manifest_path, approvals, _, _ = _failed_figure_2_run(
        tmp_path, monkeypatch
    )
    figure_4 = _response_for_task(
        _read(manifest["requests"][1]["task_path"]), extracted_slot_index=0
    )
    client = _FakeClient([_FakeProviderResponse(figure_4)])

    with pytest.raises(TypeError, match="figure_2_raw_response_sha256"):
        selective.resume_failed_figure_2(
            manifest_path, approvals, tmp_path / "run", client=client
        )

    assert client.responses.calls == []


def test_resume_failed_figure_2_rejects_joint_raw_and_trial_replacement_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching replacement files cannot satisfy the separately approved raw-response hash."""
    _, manifest_path, approvals, trial, raw_sha256 = _failed_figure_2_run(
        tmp_path, monkeypatch
    )
    trial["outcomes"][0]["qualitative_outcome"] = "schema-valid joint replacement"
    trial["outcomes"][0]["exact_printed_support"] = None
    figure_dir = tmp_path / "run" / "NP-002" / "figure_2"
    replacement_raw = {"id": "replacement", "output_text": json.dumps(trial)}
    (figure_dir / "response.json").write_text(json.dumps(replacement_raw), encoding="utf-8")
    (figure_dir / "trial_response.json").write_text(json.dumps(trial), encoding="utf-8")
    client = _FakeClient([])

    with pytest.raises(ValueError, match="approved Figure 2 raw response"):
        selective.resume_failed_figure_2(
            manifest_path,
            approvals,
            tmp_path / "run",
            figure_2_raw_response_sha256=raw_sha256,
            client=client,
        )

    assert client.responses.calls == []
    assert not (tmp_path / "run" / "NP-002" / "figure_4").exists()


def test_run_approved_failure_manifest_hashes_persisted_figure_2_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local failure after Figure 2 persistence must bind every available artifact."""
    _, _, approvals, _, _ = _failed_figure_2_run(tmp_path, monkeypatch)
    run_dir = tmp_path / "run" / "NP-002"
    failed = _read(str(run_dir / "manifest.json"))
    artifacts = failed["failed_request"]

    assert artifacts["figure"] == "Figure 2"
    assert artifacts["request_sha256"] == approvals["Figure 2"]
    for field, filename in (
        ("raw_response_sha256", "response.json"),
        ("trial_response_sha256", "trial_response.json"),
        ("usage_sha256", "usage.json"),
    ):
        assert artifacts[field] == hashlib.sha256(
            (run_dir / "figure_2" / filename).read_bytes()
        ).hexdigest()


@pytest.mark.parametrize(
    "failure_stage",
    [
        "serialization",
        "usage_serialization",
        "output",
        "parse",
        "normalization",
        "validation",
    ],
)
def test_resume_records_every_postdispatch_figure_4_failure_as_two_paid_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    """Every local failure after resumed dispatch must durably record the second paid call."""
    manifest, manifest_path, approvals, _, raw_sha256 = _failed_figure_2_run(
        tmp_path, monkeypatch
    )
    figure_4_task = _read(manifest["requests"][1]["task_path"])
    valid_payload = _response_for_task(figure_4_task, extracted_slot_index=0)
    response: object
    if failure_stage == "serialization":
        response = _UnserializableProviderResponse()
    elif failure_stage == "usage_serialization":
        response = _FakeProviderResponse(valid_payload)
        response.usage = object()
    elif failure_stage == "output":
        response = _FakeProviderResponse(valid_payload)
        response.output_text = ""
    elif failure_stage == "parse":
        response = _FakeProviderResponse(valid_payload)
        response.output_text = "{not-json"
    elif failure_stage == "validation":
        invalid_payload = json.loads(json.dumps(valid_payload))
        invalid_payload["slot_accounting"].pop(next(iter(invalid_payload["slot_accounting"])))
        response = _FakeProviderResponse(invalid_payload)
    else:
        response = _FakeProviderResponse(valid_payload)
        original_normalize = selective._normalize_qualitative_response

        def fail_figure_4_normalization(payload: dict) -> dict:
            if payload.get("figure") == "Figure 4":
                raise RuntimeError("normalization failed")
            return original_normalize(payload)

        monkeypatch.setattr(
            selective,
            "_normalize_qualitative_response",
            fail_figure_4_normalization,
        )

    client = _FakeClient([response])
    with pytest.raises((TypeError, ValueError, RuntimeError)):
        selective.resume_failed_figure_2(
            manifest_path,
            approvals,
            tmp_path / "run",
            figure_2_raw_response_sha256=raw_sha256,
            client=client,
        )

    assert len(client.responses.calls) == 1
    run_dir = tmp_path / "run" / "NP-002"
    failed = _read(str(run_dir / "manifest.json"))
    assert failed["status"] == "failed"
    assert failed["paid_api_requests"] == 2
    assert failed["completed_figures"] == ["Figure 2"]
    assert failed["failed_request"]["figure"] == "Figure 4"
    assert (run_dir / "figure_4" / "invocation_started.json").is_file()
    if failure_stage != "serialization":
        assert failed["failed_request"]["raw_response_sha256"] == hashlib.sha256(
            (run_dir / "figure_4" / "response.json").read_bytes()
        ).hexdigest()
    if failure_stage not in {"serialization", "usage_serialization"}:
        assert failed["failed_request"]["usage_sha256"] == hashlib.sha256(
            (run_dir / "figure_4" / "usage.json").read_bytes()
        ).hexdigest()
    if failure_stage in {"normalization", "validation"}:
        assert failed["failed_request"]["trial_response_sha256"] == hashlib.sha256(
            (run_dir / "figure_4" / "trial_response.json").read_bytes()
        ).hexdigest()

    repeat_client = _FakeClient([])
    with pytest.raises(
        (FileExistsError, ValueError),
        match="Figure 4 invocation already started|one-call failed Figure 2 run",
    ):
        selective.resume_failed_figure_2(
            manifest_path,
            approvals,
            tmp_path / "run",
            figure_2_raw_response_sha256=raw_sha256,
            client=repeat_client,
        )
    assert repeat_client.responses.calls == []


def test_resume_keeps_one_paid_call_when_figure_4_marker_blocks_predispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A marker conflict before provider dispatch must not increment durable accounting."""
    _, manifest_path, approvals, _, raw_sha256 = _failed_figure_2_run(
        tmp_path, monkeypatch
    )
    figure_4_marker = (
        tmp_path / "run" / "NP-002" / "figure_4" / "invocation_started.json"
    )
    figure_4_marker.parent.mkdir(parents=True)
    figure_4_marker.write_text("{}\n", encoding="utf-8")
    client = _FakeClient([])

    with pytest.raises(FileExistsError, match="Figure 4 invocation already started"):
        selective.resume_failed_figure_2(
            manifest_path,
            approvals,
            tmp_path / "run",
            figure_2_raw_response_sha256=raw_sha256,
            client=client,
        )

    assert client.responses.calls == []
    failed = _read(str(tmp_path / "run" / "NP-002" / "manifest.json"))
    assert failed["paid_api_requests"] == 1
