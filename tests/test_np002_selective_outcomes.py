from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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
