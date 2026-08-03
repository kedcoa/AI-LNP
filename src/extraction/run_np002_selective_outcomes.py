"""Prepare immutable, source-grounded qualitative vision requests for NP-002."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

try:  # Kept optional so zero-call preflight remains locally usable.
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised only in a missing SDK environment
    OpenAI = None  # type: ignore[assignment,misc]


ROOT = Path(__file__).resolve().parents[2]
PAPER_ID = "NP-002"
PDF_PATH = ROOT / "data/staging/new_papers/NP-002/PMC6816632.pdf"
HTML_PATH = ROOT / "data/staging/new_papers/NP-002/PMC6816632.html"
PAPER_MAP_PATH = (
    ROOT
    / "data/staging/extraction/full_paper_np002_paper_map_run/NP-002/paper_map.json"
)
PREFLIGHT_VERSION = "np002-selective-outcomes-preflight-1.0.0"
TASK_VERSION = "np002-selective-outcomes-task-1.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Slot(StrictModel):
    slot_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    formulation: str = Field(min_length=1)
    payload: str = Field(min_length=1)
    dose: float | None
    recipient_cell: str = Field(min_length=1)
    assay: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)


class OutcomeRow(StrictModel):
    slot_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    formulation: str = Field(min_length=1)
    payload: str = Field(min_length=1)
    dose: float | None
    recipient_cell: str = Field(min_length=1)
    assay: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    qualitative_outcome: str = Field(min_length=1)
    comparison_target: str | None = None
    significance_wording: str | None = None
    numeric_value: float | None = None
    numeric_unit: str | None = None
    exact_printed_support: str | None = None
    figure_panel: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def numeric_values_require_visible_support(self) -> "OutcomeRow":
        has_number = self.numeric_value is not None or self.numeric_unit is not None
        if has_number and (self.numeric_value is None or self.numeric_unit is None):
            raise ValueError("numeric outcomes require both numeric_value and numeric_unit")
        if has_number and not self.exact_printed_support:
            raise ValueError("numeric values require exact_printed_support")
        if self.exact_printed_support and self.numeric_value is None:
            raise ValueError("exact_printed_support requires a numeric_value")
        return self


class AccountingEntry(StrictModel):
    disposition: Literal["extracted", "not_explicit"]
    outcome_slot_id: str | None = None
    explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class FigureResponse(StrictModel):
    figure: str = Field(min_length=1)
    outcomes: list[OutcomeRow]
    slot_accounting: dict[str, AccountingEntry]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _artifact_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return _sha256(path.read_bytes())


def _failed_request_artifacts(
    figure: str,
    slug: str,
    figure_dir: Path,
    request_sha256: str,
) -> dict[str, Any]:
    artifacts: dict[str, Any] = {
        "figure": figure,
        "slug": slug,
        "request_sha256": request_sha256,
    }
    for key, filename in (
        ("raw_response_sha256", "response.json"),
        ("trial_response_sha256", "trial_response.json"),
        ("usage_sha256", "usage.json"),
    ):
        digest = _artifact_sha256(figure_dir / filename)
        if digest is not None:
            artifacts[key] = digest
    return artifacts


def _plain_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def _html_element_text(source: str, element_id: str) -> str:
    match = re.search(
        rf'<(?:p|figure)[^>]*\bid="{re.escape(element_id)}"[^>]*>(.*?)</(?:p|figure)>',
        source,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError(f"Committed NP-002 HTML lacks source element {element_id}")
    return _plain_text(match.group(1))


def _figure_caption(source: str, figure_id: str) -> str:
    match = re.search(
        rf'<figure[^>]*\bid="{re.escape(figure_id)}"[^>]*>(.*?)</figure>',
        source,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError(f"Committed NP-002 HTML lacks {figure_id}")
    caption = re.search(r"<figcaption>(.*?)</figcaption>", match.group(1), flags=re.DOTALL)
    if not caption:
        raise ValueError(f"Committed NP-002 HTML lacks {figure_id} caption")
    return _plain_text(caption.group(1))


def _render_crop(pdf_path: Path, page_number: int, crop_box: tuple[float, float, float, float], output_path: Path) -> None:
    """Render a verified PDF region with PyMuPDF, without any provider access."""
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("NP-002 selective vision preflight requires PyMuPDF") from exc
    document = fitz.open(pdf_path)
    try:
        if page_number > document.page_count:
            raise ValueError(f"Page {page_number} exceeds PDF page count")
        page = document[page_number - 1]
        clip = fitz.Rect(*crop_box)
        if not page.rect.contains(clip):
            raise ValueError("NP-002 figure crop lies outside its PDF page")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False).save(output_path)
    finally:
        document.close()


def _slot_id(figure: str, formulation: str, dose: float | None, recipient: str) -> str:
    parts = [figure.lower().replace(" ", "-"), formulation.lower()]
    if dose is not None:
        parts.append(str(dose).replace(".", "p") + "mgkg")
    parts.append(recipient.lower().replace(" ", "-").replace("endothelial-", ""))
    return "-".join(parts)


def _experiment_id(formulation: str, payload: str, dose: float | None) -> str:
    if dose is None:
        raise ValueError("experiment identity requires a dose")
    formulation_keys = {"MC3": "MC3", "cKK-E12": "cKKE12"}
    payload_keys = {"QUANT DNA": "QUANT", "Cre mRNA": "CRE"}
    try:
        formulation_key = formulation_keys[formulation]
        payload_key = payload_keys[payload]
    except KeyError as exc:
        raise ValueError("unknown experiment identity value") from exc
    return f"EXP::NP002::{payload_key}::{formulation_key}::{float(dose):.1f}"


def _slots(
    *, figure: str, payload: str, doses: list[float | None], assay: str, endpoint: str
) -> list[dict[str, Any]]:
    return [
        Slot(
            slot_id=_slot_id(figure, formulation, dose, recipient),
            experiment_id=_experiment_id(formulation, payload, dose),
            formulation=formulation,
            payload=payload,
            dose=dose,
            recipient_cell=recipient,
            assay=assay,
            endpoint=endpoint,
        ).model_dump(mode="json")
        for formulation in ("MC3", "cKK-E12")
        for dose in doses
        for recipient in ("Kupffer cells", "liver endothelial cells", "hepatocytes")
    ]


def _experiment_inventory(paper_map: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    contexts = paper_map.get("provisional_experiment_contexts")
    if not isinstance(contexts, list):
        raise ValueError("paper map lacks provisional experiment contexts")
    by_identity: dict[tuple[str, str], Mapping[str, Any]] = {}
    for context in contexts:
        if not isinstance(context, Mapping):
            raise ValueError("paper-map experiment context must be an object")
        formulation_id = context.get("formulation_id")
        payload_id = context.get("payload_id")
        if isinstance(formulation_id, str) and isinstance(payload_id, str):
            by_identity[(formulation_id, payload_id)] = context

    definitions = (
        ("MC3", "FORM::MC3_LNP", "QUANT DNA", "PAYLOAD::QUANT_DNA", 0.3),
        ("cKK-E12", "FORM::cKK-E12_LNP", "QUANT DNA", "PAYLOAD::QUANT_DNA", 0.3),
        ("MC3", "FORM::MC3_LNP", "Cre mRNA", "PAYLOAD::Cre_mRNA", 0.3),
        ("cKK-E12", "FORM::cKK-E12_LNP", "Cre mRNA", "PAYLOAD::Cre_mRNA", 0.3),
        ("MC3", "FORM::MC3_LNP", "Cre mRNA", "PAYLOAD::Cre_mRNA", 1.0),
        ("cKK-E12", "FORM::cKK-E12_LNP", "Cre mRNA", "PAYLOAD::Cre_mRNA", 1.0),
    )
    inventory: dict[str, dict[str, Any]] = {}
    for formulation, formulation_id, payload, payload_id, dose in definitions:
        context = by_identity.get((formulation_id, payload_id))
        if context is None:
            raise ValueError("paper map lacks a required source-supported experiment context")
        source_dose = context.get("dose")
        if not isinstance(source_dose, Mapping) or not source_dose.get("evidence_ids"):
            raise ValueError("paper-map experiment dose lacks source evidence")
        experiment_id = _experiment_id(formulation, payload, dose)
        inventory[experiment_id] = {
            "experiment_id": experiment_id,
            "provisional_context_id": context.get("provisional_context_id"),
            "formulation": formulation,
            "formulation_id": formulation_id,
            "payload": payload,
            "payload_id": payload_id,
            "dose": {**dict(source_dose), "value": dose},
            "dose_unit": dict(context["dose_unit"]),
            "route": dict(context["route"]),
            "species": dict(context["species"]),
            "experimental_model": dict(context["experimental_model"]),
            "organ": dict(context["organ"]),
            "timepoint": dict(context["timepoint"]),
            "timepoint_unit": dict(context["timepoint_unit"]),
            "joint_evidence_ids": list(context.get("joint_evidence_ids", [])),
        }
    return inventory


def _task_specs(html_source: str) -> list[dict[str, Any]]:
    return [
        {
            "figure": "Figure 2",
            "slug": "figure_2",
            "pdf_page": 7,
            "crop_box": (40.0, 70.0, 575.0, 565.0),
            "max_output_tokens": 4_000,
            "allowed_exact_numeric_outcomes": [],
            "slots": _slots(
                figure="Figure 2",
                payload="QUANT DNA",
                doses=[0.3],
                assay="cellular DNA accumulation",
                endpoint="QUANT DNA accumulation",
            ),
            "evidence": [
                {"evidence_id": "NP002-FIG2-CAPTION", "source_id": "Fig2", "text": _figure_caption(html_source, "Fig2")},
                {"evidence_id": "NP002-FIG2-RESULTS", "source_id": "Par11", "text": _html_element_text(html_source, "Par11")},
                {"evidence_id": "NP002-FIG2-METHODS", "source_id": "Par18", "text": _html_element_text(html_source, "Par18")},
            ],
        },
        {
            "figure": "Figure 4",
            "slug": "figure_4",
            "pdf_page": 11,
            "crop_box": (40.0, 70.0, 575.0, 470.0),
            "max_output_tokens": 6_000,
            "allowed_exact_numeric_outcomes": [],
            "slots": _slots(
                figure="Figure 4",
                payload="Cre mRNA",
                doses=[0.3, 1.0],
                assay="Ai14 tdTomato reporter flow cytometry",
                endpoint="percent tdTomato-positive cells",
            ),
            "evidence": [
                {"evidence_id": "NP002-FIG4-CAPTION", "source_id": "Fig4", "text": _figure_caption(html_source, "Fig4")},
                {"evidence_id": "NP002-FIG4-RESULTS-SETUP", "source_id": "Par14", "text": _html_element_text(html_source, "Par14")},
                {"evidence_id": "NP002-FIG4-RESULTS-COMPARISON", "source_id": "Par15", "text": _html_element_text(html_source, "Par15")},
                {"evidence_id": "NP002-FIG4-METHODS", "source_id": "Par23", "text": _html_element_text(html_source, "Par23")},
            ],
        },
    ]


def _response_schema(slots: list[dict[str, Any]]) -> dict[str, Any]:
    slot_ids = [slot["slot_id"] for slot in slots]
    slot_fields = {
        key: {"type": "object", "additionalProperties": False, "required": ["disposition", "outcome_slot_id", "explanation", "evidence_ids"], "properties": {
            "disposition": {"type": "string", "enum": ["extracted", "not_explicit"]},
            "outcome_slot_id": {"type": ["string", "null"]},
            "explanation": {"type": "string", "minLength": 1},
            "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        }}
        for key in slot_ids
    }
    outcome_fields = {
        "slot_id": {"type": "string", "minLength": 1},
        "experiment_id": {"type": "string", "minLength": 1},
        "formulation": {"type": "string", "minLength": 1},
        "payload": {"type": "string", "minLength": 1},
        "dose": {"type": ["number", "null"]},
        "recipient_cell": {"type": "string", "minLength": 1},
        "assay": {"type": "string", "minLength": 1},
        "endpoint": {"type": "string", "minLength": 1},
        "qualitative_outcome": {"type": "string", "minLength": 1},
        "comparison_target": {"type": ["string", "null"]},
        "significance_wording": {"type": ["string", "null"]},
        "numeric_value": {"type": ["number", "null"]},
        "numeric_unit": {"type": ["string", "null"]},
        "exact_printed_support": {"type": ["string", "null"]},
        "figure_panel": {"type": "string", "minLength": 1},
        "evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["figure", "outcomes", "slot_accounting"],
        "properties": {
            "figure": {"type": "string"},
            "outcomes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(outcome_fields),
                    "properties": outcome_fields,
                },
            },
            "slot_accounting": {
                "type": "object",
                "additionalProperties": False,
                "required": slot_ids,
                "properties": slot_fields,
            },
        },
    }


_INSTRUCTIONS = (
    "Extract only source-supported qualitative outcomes for the specified slots. "
    "Every slot must be accounted for exactly once as extracted or not_explicit. "
    "Use only supplied crop and text evidence IDs. Qualitative comparisons and "
    "printed significance wording are useful. Do not infer, calculate, or report "
    "a number from an axis, a bar height, or any visual estimate: visually "
    "estimated numbers are forbidden. A numeric_value is allowed only when its "
    "value and unit exactly match an allowed_exact_numeric_outcomes entry and "
    "its cited evidence contains the printed support."
)


def _estimate_image_tokens(crop_path: Path) -> int:
    try:
        import fitz
        from PIL import Image
    except ImportError:  # pragma: no cover - normal environment contains both
        return 0
    with Image.open(crop_path) as image:
        tiles = ((image.width + 511) // 512) * ((image.height + 511) // 512)
    return 85 + 170 * tiles


def _build_request(task: dict[str, Any], model: str) -> dict[str, Any]:
    crop_bytes = Path(task["crop_path"]).read_bytes()
    crop_url = "data:image/png;base64," + base64.b64encode(crop_bytes).decode("ascii")
    payload = _task_validation_envelope(task)
    return {
        "model": model,
        "store": False,
        "max_output_tokens": task["max_output_tokens"],
        "input": [
            {"role": "system", "content": _INSTRUCTIONS},
            {"role": "user", "content": [
                {"type": "input_text", "text": _canonical_json(payload)},
                {"type": "input_image", "image_url": crop_url, "detail": "high"},
            ]},
        ],
        "text": {"format": {"type": "json_schema", "name": f"NP002{task['slug'].title().replace('_', '')}Response", "strict": True, "schema": _response_schema(task["slots"]) }},
    }


def _task_validation_envelope(task: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "paper_id",
        "figure",
        "slots",
        "experiment_inventory",
        "evidence",
        "allowed_evidence_ids",
        "crop_evidence_id",
        "allowed_exact_numeric_outcomes",
    )
    try:
        return {key: task[key] for key in keys}
    except KeyError as exc:
        raise ValueError("immutable task lacks validation envelope fields") from exc


def prepare(output_root: Path, model: str) -> dict[str, Any]:
    """Persist exactly two local immutable requests; this function has no client."""
    if not model:
        raise ValueError("model is required")
    if not PDF_PATH.is_file() or not HTML_PATH.is_file():
        raise FileNotFoundError("Committed NP-002 PDF and HTML are required")
    root = (output_root / PAPER_ID).resolve()
    root.mkdir(parents=True, exist_ok=True)
    html_source = HTML_PATH.read_text(encoding="utf-8")
    paper_map = _read_json(PAPER_MAP_PATH, label="committed v5.2 paper map")
    experiment_inventory = _experiment_inventory(paper_map)
    requests: list[dict[str, Any]] = []
    for spec in _task_specs(html_source):
        task_dir = root / spec["slug"]
        crop_path = task_dir / "crop.png"
        _render_crop(PDF_PATH, spec["pdf_page"], spec["crop_box"], crop_path)
        crop_sha256 = _sha256(crop_path.read_bytes())
        crop_evidence_id = f"NP002-{spec['slug'].upper()}-CROP-{crop_sha256[:16]}"
        task = {
            "task_version": TASK_VERSION,
            "paper_id": PAPER_ID,
            "figure": spec["figure"],
            "source_pdf": str(PDF_PATH.resolve()),
            "source_pdf_sha256": _sha256(PDF_PATH.read_bytes()),
            "pdf_page": spec["pdf_page"],
            "crop_box": {"x0": spec["crop_box"][0], "y0": spec["crop_box"][1], "x1": spec["crop_box"][2], "y1": spec["crop_box"][3]},
            "crop_path": str(crop_path.resolve()),
            "crop_sha256": crop_sha256,
            "crop_evidence_id": crop_evidence_id,
            "slots": spec["slots"],
            "experiment_inventory": {
                experiment_id: experiment_inventory[experiment_id]
                for experiment_id in sorted(
                    {slot["experiment_id"] for slot in spec["slots"]}
                )
            },
            "evidence": [{"evidence_id": crop_evidence_id, "source_id": "PDF crop", "text": f"Rendered {spec['figure']} crop."}, *spec["evidence"]],
            "allowed_evidence_ids": [crop_evidence_id, *[row["evidence_id"] for row in spec["evidence"]]],
            # Neither requested panel prints a measured outcome value: their bars
            # are intentionally qualitative-only. This source-derived allowlist
            # therefore remains empty rather than trusting model-authored prose.
            "allowed_exact_numeric_outcomes": spec["allowed_exact_numeric_outcomes"],
            "max_output_tokens": spec["max_output_tokens"],
            "slug": spec["slug"],
        }
        task["task_sha256"] = _sha256(_canonical_json(task))
        task_dir.mkdir(parents=True, exist_ok=True)
        task_path = task_dir / "task.json"
        _write_json(task_path, task)
        request = _build_request(task, model)
        request_path = task_dir / "request.json"
        request_bytes = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        request_path.write_bytes(request_bytes)
        text_tokens = sum(len(row["text"].split()) for row in task["evidence"]) // 3 + len(_INSTRUCTIONS.split()) // 3
        image_tokens = _estimate_image_tokens(crop_path)
        requests.append({
            "figure": spec["figure"],
            "task_path": str(task_path.resolve()),
            "task_sha256": task["task_sha256"],
            "crop_path": str(crop_path.resolve()),
            "crop_sha256": crop_sha256,
            "request_path": str(request_path.resolve()),
            "request_sha256": _sha256(request_bytes),
            "request_bytes": len(request_bytes),
            "estimated_text_input_tokens": text_tokens,
            "estimated_image_input_tokens": image_tokens,
            "estimated_input_tokens": text_tokens + image_tokens,
            "max_output_tokens": spec["max_output_tokens"],
        })
    unsigned = {
        "preflight_version": PREFLIGHT_VERSION,
        "paper_id": PAPER_ID,
        "model": model,
        "provider_calls": 0,
        "human_approval_required": True,
        "experiment_inventory": experiment_inventory,
        "requests": requests,
    }
    manifest = {**unsigned, "manifest_sha256": _sha256(_canonical_json(unsigned))}
    _write_json(root / "manifest.json", manifest)
    return manifest


def _allowed_ids(task: Mapping[str, Any]) -> set[str]:
    values = task.get("allowed_evidence_ids")
    if isinstance(values, list):
        return {value for value in values if isinstance(value, str)}
    evidence = task.get("evidence", [])
    return {row["evidence_id"] for row in evidence if isinstance(row, Mapping) and isinstance(row.get("evidence_id"), str)}


def _evidence_text_by_id(task: Mapping[str, Any]) -> dict[str, str]:
    evidence = task.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("task evidence must be a list")
    result: dict[str, str] = {}
    for row in evidence:
        if not isinstance(row, Mapping):
            raise ValueError("task evidence entries must be objects")
        evidence_id = row.get("evidence_id")
        text = row.get("text")
        if not isinstance(evidence_id, str) or not isinstance(text, str):
            raise ValueError("task evidence requires ID and text")
        result[evidence_id] = text
    return result


def _normalized_numeric_key(value: float, unit: str) -> tuple[str, str]:
    try:
        normalized_value = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("numeric outcome value is invalid") from exc
    if not normalized_value.is_finite():
        raise ValueError("numeric outcome value must be finite")
    normalized_unit = re.sub(r"\s+", "", unit).casefold().replace("μ", "µ")
    if not normalized_unit:
        raise ValueError("numeric outcome unit is invalid")
    return format(normalized_value, "f"), normalized_unit


def _printed_support_matches(
    support: str,
    value: float,
    unit: str,
) -> bool:
    wanted_value, wanted_unit = _normalized_numeric_key(value, unit)
    support_unit = re.sub(r"\s+", "", support).casefold().replace("μ", "µ")
    if wanted_unit not in support_unit:
        return False
    for token in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", support):
        try:
            if _normalized_numeric_key(float(token), unit)[0] == wanted_value:
                return True
        except ValueError:
            continue
    return False


def _allowed_numeric_keys(
    task: Mapping[str, Any],
    evidence_text: Mapping[str, str],
    allowed_evidence: set[str],
) -> dict[tuple[str, str], tuple[str, str]]:
    entries = task.get("allowed_exact_numeric_outcomes", [])
    if not isinstance(entries, list):
        raise ValueError("allowed_exact_numeric_outcomes must be a list")
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("numeric outcome allowlist entries must be objects")
        value = entry.get("numeric_value")
        unit = entry.get("numeric_unit")
        evidence_id = entry.get("evidence_id")
        printed_support = entry.get("printed_support")
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not isinstance(unit, str)
            or not isinstance(evidence_id, str)
            or not isinstance(printed_support, str)
            or evidence_id not in allowed_evidence
            or evidence_id not in evidence_text
            or printed_support not in evidence_text[evidence_id]
            or not _printed_support_matches(printed_support, float(value), unit)
        ):
            raise ValueError("task numeric outcome allowlist is not source-derived")
        result[_normalized_numeric_key(float(value), unit)] = (evidence_id, printed_support)
    return result


def validate_visual_response(response: Mapping[str, Any], task: Mapping[str, Any]) -> None:
    """Reject all response rows that leave the immutable source slot envelope."""
    try:
        parsed = FigureResponse.model_validate(response)
    except Exception as exc:
        raise ValueError(f"visual response schema is invalid: {exc}") from exc
    if parsed.figure != task.get("figure"):
        raise ValueError("response figure identity does not match its task")
    slots = [Slot.model_validate(row) for row in task.get("slots", [])]
    expected = {slot.slot_id: slot for slot in slots}
    if not expected or len(expected) != len(slots):
        raise ValueError("task has invalid or duplicate slots")
    accounting_ids = set(parsed.slot_accounting)
    if accounting_ids != set(expected):
        raise ValueError("slot accounting must contain every task slot and no invented slots")
    allowed_evidence = _allowed_ids(task)
    evidence_text = _evidence_text_by_id(task)
    allowed_numeric = _allowed_numeric_keys(
        task, evidence_text, allowed_evidence
    )
    outcome_ids: set[str] = set()
    for outcome in parsed.outcomes:
        if outcome.slot_id not in expected:
            raise ValueError("outcome links an invented slot")
        if outcome.slot_id in outcome_ids:
            raise ValueError("each slot may have exactly once returned outcome")
        outcome_ids.add(outcome.slot_id)
        slot = expected[outcome.slot_id]
        if outcome.experiment_id != slot.experiment_id:
            raise ValueError("outcome experiment identity changed")
        for field in ("formulation", "payload", "dose", "recipient_cell", "assay", "endpoint"):
            if getattr(outcome, field) != getattr(slot, field):
                raise ValueError(f"outcome identity changed {field}")
        unknown = set(outcome.evidence_ids) - allowed_evidence
        if unknown:
            raise ValueError("outcome cites evidence outside the task envelope")
        if outcome.numeric_value is not None:
            assert outcome.numeric_unit is not None
            assert outcome.exact_printed_support is not None
            numeric_key = _normalized_numeric_key(
                outcome.numeric_value, outcome.numeric_unit
            )
            allowlisted = allowed_numeric.get(numeric_key)
            if not allowlisted or allowlisted[0] not in outcome.evidence_ids:
                raise ValueError(
                    "numeric outcome is absent from the source-derived allowlist "
                    "or its cited source evidence"
                )
            if (
                outcome.exact_printed_support not in evidence_text[allowlisted[0]]
                or not _printed_support_matches(
                    outcome.exact_printed_support,
                    outcome.numeric_value,
                    outcome.numeric_unit,
                )
            ):
                raise ValueError(
                    "numeric exact_printed_support is not verbatim cited source evidence"
                )
        entry = parsed.slot_accounting[outcome.slot_id]
        if entry.disposition == "not_explicit":
            raise ValueError("not_explicit accounting cannot link a returned outcome")
        if entry.disposition != "extracted" or entry.outcome_slot_id != outcome.slot_id:
            raise ValueError("returned outcomes require matching extracted accounting")
    for slot_id, entry in parsed.slot_accounting.items():
        unknown = set(entry.evidence_ids) - allowed_evidence
        if unknown:
            raise ValueError("accounting cites evidence outside the task envelope")
        if entry.disposition == "extracted":
            if entry.outcome_slot_id != slot_id or slot_id not in outcome_ids:
                raise ValueError("extracted accounting must link its one returned outcome")
        elif entry.outcome_slot_id is not None:
            raise ValueError("not_explicit accounting cannot link an outcome")


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _verified_preflight(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _read_json(manifest_path, label="preflight manifest")
    signed = dict(manifest)
    recorded_manifest_sha = signed.pop("manifest_sha256", None)
    if not isinstance(recorded_manifest_sha, str) or _sha256(_canonical_json(signed)) != recorded_manifest_sha:
        raise ValueError("preflight manifest integrity check failed")
    if manifest.get("paper_id") != PAPER_ID or manifest.get("provider_calls") != 0:
        raise ValueError("preflight manifest is not a zero-call NP-002 manifest")
    requests = manifest.get("requests")
    if not isinstance(requests, list) or [row.get("figure") if isinstance(row, Mapping) else None for row in requests] != ["Figure 2", "Figure 4"]:
        raise ValueError("preflight manifest must contain Figure 2 then Figure 4")
    if not all(isinstance(row, dict) for row in requests):
        raise ValueError("preflight requests must be objects")
    return manifest, requests


def _verified_approved_request_envelope(
    task: Mapping[str, Any],
    entry: Mapping[str, Any],
    request: Mapping[str, Any],
) -> None:
    """Bind the approved request's user content to the task used locally."""
    inputs = request.get("input")
    if not isinstance(inputs, list) or len(inputs) != 2:
        raise ValueError("approved request task envelope is malformed")
    user_message = inputs[1]
    if not isinstance(user_message, Mapping) or user_message.get("role") != "user":
        raise ValueError("approved request task envelope is malformed")
    content = user_message.get("content")
    if not isinstance(content, list) or len(content) != 2:
        raise ValueError("approved request task envelope is malformed")
    text_parts = [
        row.get("text")
        for row in content
        if isinstance(row, Mapping) and row.get("type") == "input_text"
    ]
    image_parts = [
        row.get("image_url")
        for row in content
        if isinstance(row, Mapping) and row.get("type") == "input_image"
    ]
    if len(text_parts) != 1 or not isinstance(text_parts[0], str):
        raise ValueError("approved request task envelope lacks canonical text")
    try:
        embedded_payload = json.loads(text_parts[0])
    except json.JSONDecodeError as exc:
        raise ValueError("approved request task envelope text is not JSON") from exc
    expected_payload = _task_validation_envelope(task)
    if (
        not isinstance(embedded_payload, dict)
        or text_parts[0] != _canonical_json(embedded_payload)
        or embedded_payload != expected_payload
    ):
        raise ValueError("approved request task envelope differs from immutable task")
    if len(image_parts) != 1 or not isinstance(image_parts[0], str):
        raise ValueError("approved request crop envelope lacks one image")
    image_url = image_parts[0]
    prefix = "data:image/png;base64,"
    if not image_url.startswith(prefix):
        raise ValueError("approved request crop envelope is not a PNG data URL")
    try:
        embedded_crop = base64.b64decode(image_url[len(prefix):], validate=True)
    except ValueError as exc:
        raise ValueError("approved request crop envelope has invalid base64") from exc
    embedded_crop_sha = _sha256(embedded_crop)
    expected_crop_sha = task.get("crop_sha256")
    if (
        embedded_crop_sha != expected_crop_sha
        or embedded_crop_sha != entry.get("crop_sha256")
        or embedded_crop != Path(str(entry["crop_path"])).read_bytes()
    ):
        raise ValueError("approved request crop differs from immutable task crop")


def _verified_task_and_request(entry: Mapping[str, Any]) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    required_paths = ("task_path", "crop_path", "request_path")
    if any(not isinstance(entry.get(field), str) for field in required_paths):
        raise ValueError("preflight request lacks immutable artifact paths")
    task_path = Path(str(entry["task_path"]))
    task = _read_json(task_path, label="immutable task")
    recorded_task_sha = task.get("task_sha256")
    unsigned_task = dict(task)
    unsigned_task.pop("task_sha256", None)
    if not isinstance(recorded_task_sha, str) or _sha256(_canonical_json(unsigned_task)) != recorded_task_sha:
        raise ValueError("immutable task integrity check failed")
    if task.get("task_sha256") != entry.get("task_sha256") or task.get("figure") != entry.get("figure"):
        raise ValueError("immutable task does not match preflight request")
    evidence = task.get("evidence")
    if not isinstance(evidence, list) or not all(
        isinstance(row, Mapping) and isinstance(row.get("evidence_id"), str)
        for row in evidence
    ):
        raise ValueError("immutable task evidence records are invalid")
    derived_allowed_evidence_ids = [str(row["evidence_id"]) for row in evidence]
    if (
        len(set(derived_allowed_evidence_ids)) != len(derived_allowed_evidence_ids)
        or task.get("allowed_evidence_ids") != derived_allowed_evidence_ids
    ):
        raise ValueError("immutable task allowed evidence IDs differ from supplied evidence")
    crop_path = Path(str(entry["crop_path"]))
    if task.get("crop_path") != str(crop_path.resolve()) or not crop_path.is_file():
        raise ValueError("immutable task crop path integrity check failed")
    if _sha256(crop_path.read_bytes()) != entry.get("crop_sha256") or task.get("crop_sha256") != entry.get("crop_sha256"):
        raise ValueError("immutable crop checksum changed")
    request_path = Path(str(entry["request_path"]))
    request_bytes = request_path.read_bytes()
    if _sha256(request_bytes) != entry.get("request_sha256"):
        raise ValueError("immutable request checksum changed")
    if entry.get("request_bytes") != len(request_bytes):
        raise ValueError("immutable request byte count changed")
    try:
        request = json.loads(request_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("immutable request is not valid JSON") from exc
    if not isinstance(request, dict):
        raise ValueError("immutable request must be a JSON object")
    _verified_approved_request_envelope(task, entry, request)
    return task, request_bytes, request


def _exclusive_marker(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as marker:
            marker.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            marker.flush()
            os.fsync(marker.fileno())
    except FileExistsError as exc:
        raise FileExistsError("An approved selective-vision invocation already started") from exc


def _response_object(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        dumped = dict(value)
    else:
        raise TypeError("provider response is not serializable")
    if not isinstance(dumped, dict):
        raise TypeError("provider response serialization must be an object")
    return dumped


def _usage_object(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return _response_object(usage)


def _normalize_qualitative_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Remove numeric-only support text from rows that report no numeric value."""
    normalized = json.loads(_canonical_json(response))
    if not isinstance(normalized, dict):
        raise ValueError("visual response must be a JSON object")
    outcomes = normalized.get("outcomes")
    if not isinstance(outcomes, list):
        return normalized
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        if (
            outcome.get("numeric_value") is None
            and outcome.get("numeric_unit") is None
        ):
            outcome["exact_printed_support"] = None
    return normalized


def _raw_output_text(raw_response: Mapping[str, Any]) -> str:
    direct = raw_response.get("output_text")
    if isinstance(direct, str):
        return direct
    output = raw_response.get("output")
    if not isinstance(output, list):
        raise ValueError("saved raw response has no structured output")
    texts = [
        content.get("text")
        for message in output
        if isinstance(message, Mapping)
        for content in message.get("content", [])
        if isinstance(content, Mapping) and content.get("type") == "output_text"
    ]
    if len(texts) != 1 or not isinstance(texts[0], str):
        raise ValueError("saved raw response has no unique structured output")
    return texts[0]


def _parse_output_text(output_text: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def run_approved(
    manifest_path: Path,
    approvals: Mapping[str, str],
    output_root: Path,
    client: Any | None = None,
) -> dict[str, Any]:
    """Dispatch the two exact approved request bytes once and sequentially."""
    manifest_path = Path(manifest_path)
    _, entries = _verified_preflight(manifest_path)
    required_approvals = {"Figure 2", "Figure 4"}
    if set(approvals) != required_approvals or any(
        not isinstance(value, str) for value in approvals.values()
    ):
        raise ValueError("approval must name exact hashes for Figure 2 and Figure 4")
    for entry in entries:
        figure = str(entry["figure"])
        if approvals[figure] != entry.get("request_sha256"):
            raise ValueError(f"approval hash does not match immutable {figure} request")

    run_dir = Path(output_root) / PAPER_ID
    root_marker = run_dir / "invocation_started.json"
    if root_marker.exists():
        raise FileExistsError("An approved selective-vision invocation already started")
    # Verify both artifact envelopes before the first paid boundary. Each is
    # re-read again immediately before its dispatch below.
    for entry in entries:
        _verified_task_and_request(entry)
    started_at = datetime.now(timezone.utc)
    _exclusive_marker(
        root_marker,
        {
            "status": "invocation_started",
            "paper_id": PAPER_ID,
            "manifest_path": str(manifest_path.resolve()),
            "approval_hashes": dict(approvals),
            "started_at": started_at.isoformat(),
        },
    )
    provider_client = client
    if provider_client is None:
        if OpenAI is None:
            raise RuntimeError("OpenAI SDK is required for an approved provider call")
        provider_client = OpenAI(max_retries=0)
    completed: list[dict[str, Any]] = []
    paid_dispatches = 0
    active_request: dict[str, Any] | None = None
    try:
        for entry in entries:
            figure = str(entry["figure"])
            task, request_bytes, request = _verified_task_and_request(entry)
            if _sha256(request_bytes) != approvals[figure]:
                raise ValueError(f"approved {figure} request bytes changed before dispatch")
            figure_dir = run_dir / str(task["slug"])
            _exclusive_marker(
                figure_dir / "invocation_started.json",
                {
                    "status": "invocation_started",
                    "paper_id": PAPER_ID,
                    "figure": figure,
                    "approval_sha256": approvals[figure],
                    "request_sha256": _sha256(request_bytes),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            (figure_dir / "request.json").write_bytes(request_bytes)
            active_request = {
                "figure": figure,
                "slug": str(task["slug"]),
                "figure_dir": figure_dir,
                "request_sha256": _sha256(request_bytes),
            }
            try:
                paid_dispatches += 1
                response = provider_client.responses.create(**request)
            except Exception as exc:
                _write_json(
                    figure_dir / "failure.json",
                    {"status": "provider_exception", "figure": figure, "message": str(exc)},
                )
                raise
            raw_response = _response_object(response)
            _write_json(figure_dir / "response.json", raw_response)
            usage = _usage_object(response)
            _write_json(figure_dir / "usage.json", usage)
            output_text = getattr(response, "output_text", None)
            if not isinstance(output_text, str) or not output_text.strip():
                raise ValueError(f"{figure} response has no structured output")
            trial_response = _parse_output_text(
                output_text, label=f"{figure} response"
            )
            _write_json(figure_dir / "trial_response.json", trial_response)
            validated_response = _normalize_qualitative_response(trial_response)
            validate_visual_response(validated_response, task)
            _write_json(figure_dir / "validated_response.json", validated_response)
            completed.append(
                {
                    "figure": figure,
                    "slug": task["slug"],
                    "request_sha256": _sha256(request_bytes),
                    "response_sha256": _sha256(_canonical_json(validated_response)),
                    "raw_response_sha256": _artifact_sha256(figure_dir / "response.json"),
                    "trial_response_sha256": _artifact_sha256(figure_dir / "trial_response.json"),
                    "usage_sha256": _artifact_sha256(figure_dir / "usage.json"),
                    "usage": usage,
                }
            )
            active_request = None
    except Exception as exc:
        failed_request = None
        if active_request is not None:
            failed_request = _failed_request_artifacts(
                str(active_request["figure"]),
                str(active_request["slug"]),
                active_request["figure_dir"],
                str(active_request["request_sha256"]),
            )
        failed_manifest = {
            "status": "failed",
            "paper_id": PAPER_ID,
            "paid_api_requests": paid_dispatches,
            "completed_figures": [row["figure"] for row in completed],
            "message": str(exc),
        }
        if failed_request is not None:
            failed_manifest["failed_request"] = failed_request
        _write_json(
            run_dir / "manifest.json",
            failed_manifest,
        )
        raise
    result = {
        "status": "validated",
        "paper_id": PAPER_ID,
        "paid_api_requests": 2,
        "repair_calls": 0,
        "requests": completed,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(run_dir / "manifest.json", result)
    return result


def resume_failed_figure_2(
    manifest_path: Path,
    approvals: Mapping[str, str],
    output_root: Path,
    *,
    figure_2_raw_response_sha256: str,
    client: Any | None = None,
) -> dict[str, Any]:
    """Validate one explicitly approved raw Figure 2 response, then dispatch Figure 4."""
    manifest_path = Path(manifest_path)
    _, entries = _verified_preflight(manifest_path)
    entries_by_figure = {str(entry["figure"]): entry for entry in entries}
    if set(approvals) != {"Figure 2", "Figure 4"} or any(
        approvals.get(figure) != entry.get("request_sha256")
        for figure, entry in entries_by_figure.items()
    ):
        raise ValueError("resume requires exact Figure 2 and Figure 4 approval hashes")
    figure_2_entry = entries_by_figure["Figure 2"]
    figure_4_entry = entries_by_figure["Figure 4"]
    figure_2_task, figure_2_request_bytes, _ = _verified_task_and_request(figure_2_entry)
    figure_4_task, figure_4_request_bytes, figure_4_request = _verified_task_and_request(figure_4_entry)
    run_dir = Path(output_root) / PAPER_ID
    failed_manifest = _read_json(run_dir / "manifest.json", label="failed selective-vision run manifest")
    if (
        failed_manifest.get("status") != "failed"
        or failed_manifest.get("paper_id") != PAPER_ID
        or failed_manifest.get("paid_api_requests") != 1
    ):
        raise ValueError("resume requires the exact one-call failed Figure 2 run")
    root_marker = _read_json(run_dir / "invocation_started.json", label="failed run invocation marker")
    if root_marker.get("paper_id") != PAPER_ID or root_marker.get("approval_hashes") != dict(approvals):
        raise ValueError("failed run invocation marker does not match approved requests")
    figure_2_dir = run_dir / str(figure_2_task["slug"])
    figure_2_marker = _read_json(
        figure_2_dir / "invocation_started.json", label="Figure 2 invocation marker"
    )
    if (
        figure_2_marker.get("paper_id") != PAPER_ID
        or figure_2_marker.get("figure") != "Figure 2"
        or figure_2_marker.get("approval_sha256") != approvals["Figure 2"]
        or figure_2_marker.get("request_sha256") != figure_2_entry["request_sha256"]
    ):
        raise ValueError("Figure 2 invocation marker does not match approved request")
    if (run_dir / str(figure_4_task["slug"]) / "invocation_started.json").exists():
        raise FileExistsError("Figure 4 invocation already started; refusing resume")
    saved_request_bytes = (figure_2_dir / "request.json").read_bytes()
    if saved_request_bytes != figure_2_request_bytes or _sha256(saved_request_bytes) != approvals["Figure 2"]:
        raise ValueError("saved Figure 2 request does not match approved preflight")
    if not isinstance(figure_2_raw_response_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", figure_2_raw_response_sha256
    ) is None:
        raise ValueError("resume requires an explicit approved Figure 2 raw response SHA-256")
    raw_response_path = figure_2_dir / "response.json"
    raw_response_sha256 = _sha256(raw_response_path.read_bytes())
    if raw_response_sha256 != figure_2_raw_response_sha256:
        raise ValueError("saved Figure 2 raw response does not match approved Figure 2 raw response SHA-256")
    failed_request = failed_manifest.get("failed_request")
    if isinstance(failed_request, Mapping):
        recorded_raw_sha256 = failed_request.get("raw_response_sha256")
        if recorded_raw_sha256 is not None and recorded_raw_sha256 != raw_response_sha256:
            raise ValueError("failed manifest does not match approved Figure 2 raw response")
    raw_response = _read_json(raw_response_path, label="saved raw Figure 2 response")
    raw_trial = _parse_output_text(
        _raw_output_text(raw_response), label="approved raw Figure 2 output"
    )
    trial_response_path = figure_2_dir / "trial_response.json"
    _write_json(trial_response_path, raw_trial)
    trial_response_sha256 = _sha256(trial_response_path.read_bytes())
    validated_figure_2 = _normalize_qualitative_response(raw_trial)
    validate_visual_response(validated_figure_2, figure_2_task)
    validated_figure_2_sha256 = _sha256(_canonical_json(validated_figure_2))
    _write_json(figure_2_dir / "validated_response.json", validated_figure_2)
    _write_json(
        figure_2_dir / "recovery_provenance.json",
        {
            "status": "validated_saved_figure_2",
            "figure": "Figure 2",
            "request_sha256": _sha256(saved_request_bytes),
            "raw_response_sha256": raw_response_sha256,
            "approved_raw_response_sha256": figure_2_raw_response_sha256,
            "trial_response_sha256": trial_response_sha256,
            "validated_response_sha256": validated_figure_2_sha256,
        },
    )
    figure_4_dir = run_dir / str(figure_4_task["slug"])
    _exclusive_marker(
        figure_4_dir / "invocation_started.json",
        {
            "status": "invocation_started",
            "paper_id": PAPER_ID,
            "figure": "Figure 4",
            "approval_sha256": approvals["Figure 4"],
            "request_sha256": _sha256(figure_4_request_bytes),
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    (figure_4_dir / "request.json").write_bytes(figure_4_request_bytes)
    provider_client = client
    if provider_client is None:
        if OpenAI is None:
            raise RuntimeError("OpenAI SDK is required for an approved provider call")
        provider_client = OpenAI(max_retries=0)
    try:
        response = provider_client.responses.create(**figure_4_request)
        raw_figure_4 = _response_object(response)
        _write_json(figure_4_dir / "response.json", raw_figure_4)
        usage_figure_4 = _usage_object(response)
        _write_json(figure_4_dir / "usage.json", usage_figure_4)
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise ValueError("Figure 4 response has no structured output")
        trial_figure_4 = _parse_output_text(output_text, label="Figure 4 response")
        _write_json(figure_4_dir / "trial_response.json", trial_figure_4)
        validated_figure_4 = _normalize_qualitative_response(trial_figure_4)
        validate_visual_response(validated_figure_4, figure_4_task)
        _write_json(figure_4_dir / "validated_response.json", validated_figure_4)
    except Exception as exc:
        failed_request = _failed_request_artifacts(
            "Figure 4",
            str(figure_4_task["slug"]),
            figure_4_dir,
            _sha256(figure_4_request_bytes),
        )
        _write_json(
            figure_4_dir / "failure.json",
            {
                "status": "post_dispatch_failure",
                "figure": "Figure 4",
                "message": str(exc),
                "artifacts": failed_request,
            },
        )
        _write_json(
            run_dir / "manifest.json",
            {
                "status": "failed",
                "paper_id": PAPER_ID,
                "paid_api_requests": 2,
                "completed_figures": ["Figure 2"],
                "failed_request": failed_request,
                "message": str(exc),
            },
        )
        raise
    result = {
        "status": "validated",
        "paper_id": PAPER_ID,
        "paid_api_requests": 2,
        "repair_calls": 0,
        "resumed_from_failed_figure": "Figure 2",
        "requests": [
            {
                "figure": "Figure 2",
                "slug": figure_2_task["slug"],
                "request_sha256": _sha256(saved_request_bytes),
                "response_sha256": validated_figure_2_sha256,
                "raw_response_sha256": raw_response_sha256,
                "trial_response_sha256": trial_response_sha256,
                "usage": _read_json(figure_2_dir / "usage.json", label="saved Figure 2 usage"),
            },
            {
                "figure": "Figure 4",
                "slug": figure_4_task["slug"],
                "request_sha256": _sha256(figure_4_request_bytes),
                "response_sha256": _sha256(_canonical_json(validated_figure_4)),
                "raw_response_sha256": _artifact_sha256(figure_4_dir / "response.json"),
                "trial_response_sha256": _artifact_sha256(figure_4_dir / "trial_response.json"),
                "usage_sha256": _artifact_sha256(figure_4_dir / "usage.json"),
                "usage": usage_figure_4,
            },
        ],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(run_dir / "manifest.json", result)
    return result


def _reported(value: Any, evidence_ids: list[str]) -> dict[str, Any]:
    return {"value": value, "status": "reported", "evidence_ids": evidence_ids, "missing_reason": None}


def _missing(reason: str) -> dict[str, Any]:
    return {"value": None, "status": "missing", "evidence_ids": [], "missing_reason": reason}


def _formulation_id(formulation: str) -> str:
    mapping = {"MC3": "FORM::MC3_LNP", "cKK-E12": "FORM::cKK-E12_LNP"}
    try:
        return mapping[formulation]
    except KeyError as exc:
        raise ValueError(f"unknown NP-002 formulation: {formulation}") from exc


def merge_validated(manifest_path: Path, run_root: Path, output_path: Path) -> dict[str, Any]:
    """Merge locally validated visual rows with the committed paper-level map."""
    preflight, entries = _verified_preflight(Path(manifest_path))
    run_manifest = _read_json(
        Path(run_root) / PAPER_ID / "manifest.json",
        label="validated selective-vision run manifest",
    )
    if run_manifest.get("status") != "validated":
        raise ValueError("merge requires a validated selective-vision run manifest")
    recorded_requests = run_manifest.get("requests")
    if (
        not isinstance(recorded_requests, list)
        or [row.get("figure") if isinstance(row, Mapping) else None for row in recorded_requests]
        != ["Figure 2", "Figure 4"]
        or not all(isinstance(row, dict) for row in recorded_requests)
    ):
        raise ValueError("run manifest must record Figure 2 then Figure 4")
    for preflight_entry, recorded_entry in zip(entries, recorded_requests, strict=True):
        if (
            recorded_entry.get("figure") != preflight_entry.get("figure")
            or recorded_entry.get("request_sha256") != preflight_entry.get("request_sha256")
            or not isinstance(recorded_entry.get("response_sha256"), str)
        ):
            raise ValueError("run manifest request hashes do not match preflight")
    recorded_by_figure = {row["figure"]: row for row in recorded_requests}
    paper_map = _read_json(PAPER_MAP_PATH, label="committed v5.2 paper map")
    if paper_map.get("paper_id") != PAPER_ID:
        raise ValueError("committed paper map is not NP-002")
    inventory = preflight.get("experiment_inventory")
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("preflight lacks a verified experiment inventory")
    experiments: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    slot_accounting: dict[str, Any] = {}
    seen_slots: set[str] = set()
    for entry in entries:
        task, _, _ = _verified_task_and_request(entry)
        figure_dir = Path(run_root) / PAPER_ID / str(task["slug"])
        response = _read_json(figure_dir / "validated_response.json", label="validated visual response")
        if _sha256(_canonical_json(response)) != recorded_by_figure[task["figure"]]["response_sha256"]:
            raise ValueError("validated visual response checksum does not match run manifest")
        validate_visual_response(response, task)
        for slot_id, accounting in response["slot_accounting"].items():
            slot_accounting[slot_id] = accounting
        for row in response["outcomes"]:
            slot_id = str(row["slot_id"])
            if slot_id in seen_slots:
                raise ValueError("validated visual rows duplicate a slot across figures")
            seen_slots.add(slot_id)
            evidence_ids = list(row["evidence_ids"])
            source_experiment_id = str(row["experiment_id"])
            arm = inventory.get(source_experiment_id)
            if not isinstance(arm, Mapping):
                raise ValueError("visual outcome links an unknown experiment identity")
            for key in ("formulation", "payload"):
                if row[key] != arm.get(key):
                    raise ValueError(f"visual outcome conflicts with experiment {key}")
            if row.get("dose") != arm.get("dose", {}).get("value"):
                raise ValueError("visual outcome conflicts with experiment dose")
            arm_evidence_ids = list(arm.get("joint_evidence_ids", []))
            experiment_id = f"ROW::{source_experiment_id}::{slot_id}"
            experiments.append(
                {
                    "experiment_id": experiment_id,
                    "source_experiment_id": source_experiment_id,
                    "formulation_id": str(arm["formulation_id"]),
                    "payload_name": _reported(arm["payload"], arm_evidence_ids),
                    "dose": dict(arm["dose"]),
                    "dose_unit": dict(arm["dose_unit"]),
                    "delivery_recipient_cell": _reported(row["recipient_cell"], evidence_ids),
                    "route": dict(arm["route"]),
                    "species": dict(arm["species"]),
                    "experimental_model": dict(arm["experimental_model"]),
                    "tissue_or_organ": dict(arm["organ"]),
                    "timepoint": dict(arm["timepoint"]),
                    "timepoint_unit": dict(arm["timepoint_unit"]),
                }
            )
            outcomes.append(
                {
                    "outcome_id": f"VIS-OUT::{slot_id}",
                    "experiment_id": experiment_id,
                    "slot_id": slot_id,
                    "figure": task["figure"],
                    "figure_panel": row["figure_panel"],
                    "evidence_ids": evidence_ids,
                    "assay": _reported(row["assay"], evidence_ids),
                    "endpoint": _reported(row["endpoint"], evidence_ids),
                    "comparator": _reported(row["comparison_target"], evidence_ids)
                    if row.get("comparison_target")
                    else _missing("No source-supported comparator was reported."),
                    "outcome_value": _missing("The figure bar has no printed measured value."),
                    "outcome_unit": _missing("The figure bar has no printed measured unit."),
                    "numeric_value": None,
                    "numeric_unit": None,
                    "qualitative_outcome": _reported(row["qualitative_outcome"], evidence_ids),
                    "significance_wording": row.get("significance_wording"),
                }
            )
    artifact = {
        "contract_version": "np002-selective-vision-merge-1.0.0",
        "paper_id": PAPER_ID,
        "paper_map": paper_map,
        "formulations": [
            {"formulation_id": "FORM::MC3_LNP", "formulation_name": _reported("MC3", [])},
            {"formulation_id": "FORM::cKK-E12_LNP", "formulation_name": _reported("cKK-E12", [])},
        ],
        "experiments": experiments,
        "outcomes": outcomes,
        "slot_accounting": slot_accounting,
        "paid_api_requests": 2,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output_path, artifact)
    return artifact
