import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from pydantic import ValidationError

from src.extraction.build_selective_vision_tasks import build_task
from src.extraction.compact_validation import ValidationFinding, ValidationReport
from src.extraction.identify_selective_vision_referrals import identify
from src.extraction.run_selective_vision import _image_data, response_schema, run_vision
from src.extraction.selective_vision_contracts import (
    CropBox,
    SelectiveVisionResponse,
    SelectiveVisionTask,
    VisionReferral,
    VisionTextEvidence,
)
from src.rag.compact_api_packet import ApiEvidence, ApiSource, CompactApiPacket


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _finding():
    return ValidationFinding(
        finding_id="VF-VISION",
        code="unresolved_visual_value",
        message="The exact outcome is unresolved in Figure 3.",
        location=["outcomes", 0, "outcome_value"],
        record_collection="outcomes",
        record_index=0,
        field_name="outcome_value",
        cited_evidence_ids=["E-RESULT"],
        repairable=True,
    )


def _report():
    return ValidationReport(
        paper_id="GP-TEST", status="invalid", findings=[_finding()]
    )


def _packet():
    sources = [
        ApiSource(
            source_id="S-FIG",
            chunk_id="C-FIG",
            source_path="paper.pdf",
            source_kind="pdf",
            block_type="figure_caption",
            section="Results",
            page_number=4,
            figure_number="Figure 3",
        ),
        ApiSource(
            source_id="S-RESULT",
            chunk_id="C-RESULT",
            source_path="paper.pdf",
            source_kind="pdf",
            block_type="paragraph",
            section="Results",
            page_number=4,
            figure_number="Figure 3",
        ),
        ApiSource(
            source_id="S-METHOD",
            chunk_id="C-METHOD",
            source_path="paper.pdf",
            source_kind="pdf",
            block_type="paragraph",
            section="Methods",
            page_number=2,
        ),
    ]
    evidence = [
        ApiEvidence(
            evidence_id="E-CAPTION",
            text="Figure 3. Editing efficiency in LSECs.",
            retrieval_field_tags=["outcome_value"],
            source_ids=["S-FIG"],
        ),
        ApiEvidence(
            evidence_id="E-RESULT",
            text="Editing efficiency is shown in Figure 3.",
            retrieval_field_tags=["outcome_value"],
            source_ids=["S-RESULT"],
        ),
        ApiEvidence(
            evidence_id="E-METHOD",
            text="Editing was quantified seven days after dosing.",
            retrieval_field_tags=["assay", "timepoint"],
            source_ids=["S-METHOD"],
        ),
        ApiEvidence(
            evidence_id="E-UNRELATED",
            text="Unrelated discussion.",
            retrieval_field_tags=["disease_model"],
            source_ids=["S-RESULT"],
        ),
    ]
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": "GP-TEST",
        "blocked_fields": [],
        "sources": [row.model_dump(mode="json", exclude_none=True) for row in sources],
        "evidence": [row.model_dump(mode="json", exclude_none=True) for row in evidence],
    }
    checksum = hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
    return CompactApiPacket.model_validate(
        {**unsigned, "packet_checksum": checksum}
    )


def _referral():
    return VisionReferral(
        referral_version="selective-vision-referral-1.0.0",
        paper_id="GP-TEST",
        finding_id="VF-VISION",
        trigger="unresolved_figure",
        reason="The result passage points to Figure 3 but contains no number.",
        source_id="S-FIG",
        page_number=4,
        figure_or_table="Figure 3",
        crop_box=CropBox(x0=10, y0=20, x1=300, y1=400),
        caption_evidence_id="E-CAPTION",
        referring_results_evidence_ids=["E-RESULT"],
        methods_evidence_ids=["E-METHOD"],
    )


def _fake_renderer(pdf_path, page_number, crop_box, output_path):
    assert page_number == 4
    assert crop_box is not None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(output_path)


def _build_task(
    tmp_path,
    *,
    experiment_id: str | None = None,
    candidate_id: str | None = None,
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-FAKE-FOR-UNIT-TEST")
    return build_task(
        referral=_referral(),
        report=_report(),
        packet=_packet(),
        pdf_path=pdf_path,
        output_root=tmp_path / "tasks",
        renderer=_fake_renderer,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
    )


def test_experiment_bound_task_requires_response_to_echo_issued_ids(tmp_path):
    task = _build_task(
        tmp_path,
        experiment_id="EXP-ISSUED",
        candidate_id="CTX-ISSUED",
    )

    schema = response_schema(task)

    assert schema["properties"]["experiment_id"] == {
        "type": "string",
        "const": "EXP-ISSUED",
    }
    assert schema["properties"]["candidate_id"] == {
        "type": "string",
        "const": "CTX-ISSUED",
    }
    assert "experiment_id" in schema["required"]
    assert "candidate_id" in schema["required"]
    Draft202012Validator.check_schema(schema)


def test_image_data_uses_verified_jpeg_mime_type(tmp_path):
    image_path = tmp_path / "figure.jpg"
    Image.new("RGB", (12, 10), "white").save(image_path, format="JPEG")

    data_url = _image_data(image_path)

    assert data_url.startswith("data:image/jpeg;base64,")


def test_image_data_rejects_extension_magic_mismatch(tmp_path):
    image_path = tmp_path / "figure.jpg"
    Image.new("RGB", (12, 10), "white").save(image_path, format="PNG")

    with pytest.raises(ValueError, match="extension.*content|content.*extension"):
        _image_data(image_path)


def test_builder_requires_explicit_visual_source_and_creates_one_crop(tmp_path):
    task = _build_task(tmp_path)
    assert Path(task.crop_path).exists()
    assert task.crop_evidence_id.startswith("V-")
    assert task.page_number == 4
    assert task.figure_or_table == "Figure 3"
    assert task.caption.evidence_id == "E-CAPTION"
    assert [row.evidence_id for row in task.referring_results_passages] == [
        "E-RESULT"
    ]
    assert [row.evidence_id for row in task.methods_context] == ["E-METHOD"]
    assert "E-UNRELATED" not in json.dumps(task.text_payload())
    assert "source_pdf" not in task.text_payload()


def test_detector_requires_explicit_unresolved_visual_signal():
    referrals, skipped = identify(_report(), _packet())
    assert len(referrals) == 1
    assert referrals[0].trigger == "unresolved_figure"
    assert referrals[0].figure_or_table == "Figure 3"
    assert referrals[0].caption_evidence_id == "E-CAPTION"
    assert referrals[0].referring_results_evidence_ids == ["E-RESULT"]
    assert skipped == []

    ordinary = _report().model_copy(
        update={
            "findings": [
                _finding().model_copy(
                    update={
                        "code": "unknown_evidence_id",
                        "message": "Unknown evidence identifier.",
                    }
                )
            ]
        }
    )
    referrals, skipped = identify(ordinary, _packet())
    assert referrals == []
    assert skipped[0]["reason"] == "no_explicit_unresolved_visual_signal"


def test_builder_rejects_figure_referral_pointing_to_table_source(tmp_path):
    referral = _referral().model_copy(
        update={"trigger": "unresolved_table"}
    )
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-FAKE")
    with pytest.raises(ValueError, match="does not match"):
        build_task(
            referral=referral,
            report=_report(),
            packet=_packet(),
            pdf_path=pdf_path,
            output_root=tmp_path / "tasks",
            renderer=_fake_renderer,
        )


class FakeResponse:
    id = "resp_vision_test"
    model = "gpt-5.6-terra-test"
    output_text = SelectiveVisionResponse(
        finding_id="VF-VISION",
        disposition="resolved",
        field_name="outcome_value",
        corrected_fragment={
            "outcome_value": {
                "value": 16.5,
                "status": "reported",
                "evidence_ids": ["V-PLACEHOLDER"],
                "missing_reason": None,
            }
        },
        value_status="exact_reported",
        supporting_evidence_ids=["V-PLACEHOLDER"],
        figure_or_table="Figure 3",
        panel_or_table_cell="panel B, printed label above the LSEC bar",
        visible_support="16.50% is printed above the LSEC bar.",
        derivation=None,
        confidence="high",
        requires_human_review=False,
    ).model_dump_json()
    usage = SimpleNamespace(
        model_dump=lambda mode="json": {
            "input_tokens": 500,
            "output_tokens": 100,
            "total_tokens": 600,
        }
    )

    def model_dump(self, mode="json"):
        return {"id": self.id, "model": self.model}


class FakeResponses:
    def __init__(self, task):
        self.calls = []
        response = SelectiveVisionResponse.model_validate_json(
            FakeResponse.output_text
        ).model_copy(
            update={
                "corrected_fragment": {
                    "outcome_value": {
                        "value": 16.5,
                        "status": "reported",
                        "evidence_ids": [task.crop_evidence_id],
                        "missing_reason": None,
                    }
                },
                "supporting_evidence_ids": [task.crop_evidence_id],
            }
        )
        self.output_text = response.model_dump_json()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = FakeResponse()
        response.output_text = self.output_text
        return response


def test_vision_sends_one_png_not_pdf_and_identical_rerun_is_cached(tmp_path):
    task = _build_task(tmp_path)
    responses = FakeResponses(task)
    client = SimpleNamespace(responses=responses)
    output_root = tmp_path / "results"
    first = run_vision(
        task,
        model="gpt-5.6-terra",
        client=client,
        output_root=output_root,
    )
    second = run_vision(
        task,
        model="gpt-5.6-terra",
        client=client,
        output_root=output_root,
    )
    assert len(responses.calls) == 1
    content = responses.calls[0]["input"][1]["content"]
    images = [row for row in content if row["type"] == "input_image"]
    assert len(images) == 1
    assert images[0]["image_url"].startswith("data:image/png;base64,")
    assert not any(row["type"] == "input_file" for row in content)
    assert first["full_pdf_sent"] is False
    assert first["source_images_sent"] == 1
    assert second["cache_hit"] is True
    assert second["paid_api_requests_this_run"] == 0


def test_visual_estimate_is_forced_to_human_review():
    with pytest.raises(ValidationError, match="visually estimated"):
        SelectiveVisionResponse(
            finding_id="VF-VISION",
            disposition="resolved",
            field_name="outcome_value",
            corrected_fragment={
                "outcome_value": {
                    "value": 15.0,
                    "status": "reported",
                    "evidence_ids": ["E-RESULT"],
                    "missing_reason": None,
                }
            },
            value_status="visually_estimated",
            supporting_evidence_ids=["E-RESULT"],
            figure_or_table="Figure 3",
            panel_or_table_cell="panel B, estimated from bar height",
            visible_support="Bar appears near 15%.",
            derivation=None,
            confidence="low",
            requires_human_review=False,
        )


def test_resolved_value_requires_panel_or_table_cell():
    with pytest.raises(ValidationError, match="panel_or_table_cell"):
        SelectiveVisionResponse(
            finding_id="VF-VISION",
            disposition="resolved",
            field_name="outcome_value",
            corrected_fragment={
                "outcome_value": {
                    "value": 16.5,
                    "status": "reported",
                    "evidence_ids": ["E-RESULT"],
                    "missing_reason": None,
                }
            },
            value_status="exact_reported",
            supporting_evidence_ids=["E-RESULT"],
            figure_or_table="Figure 3",
            panel_or_table_cell=None,
            visible_support="16.50% is printed.",
            derivation=None,
            confidence="high",
            requires_human_review=False,
        )
