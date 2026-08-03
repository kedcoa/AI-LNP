"""Prepare immutable, source-grounded qualitative vision requests for NP-002."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


ROOT = Path(__file__).resolve().parents[2]
PAPER_ID = "NP-002"
PDF_PATH = ROOT / "data/staging/new_papers/NP-002/PMC6816632.pdf"
HTML_PATH = ROOT / "data/staging/new_papers/NP-002/PMC6816632.html"
PREFLIGHT_VERSION = "np002-selective-outcomes-preflight-1.0.0"
TASK_VERSION = "np002-selective-outcomes-task-1.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Slot(StrictModel):
    slot_id: str = Field(min_length=1)
    formulation: str = Field(min_length=1)
    payload: str = Field(min_length=1)
    dose: float | None
    recipient_cell: str = Field(min_length=1)
    assay: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)


class OutcomeRow(StrictModel):
    slot_id: str = Field(min_length=1)
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


def _slots(
    *, figure: str, payload: str, doses: list[float | None], assay: str, endpoint: str
) -> list[dict[str, Any]]:
    return [
        Slot(
            slot_id=_slot_id(figure, formulation, dose, recipient),
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


def _task_specs(html_source: str) -> list[dict[str, Any]]:
    return [
        {
            "figure": "Figure 2",
            "slug": "figure_2",
            "pdf_page": 7,
            "crop_box": (40.0, 70.0, 575.0, 565.0),
            "max_output_tokens": 4_000,
            "slots": _slots(
                figure="Figure 2",
                payload="QUANT DNA",
                doses=[None],
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
    "exact_printed_support quotes an explicitly printed number in supplied evidence."
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
    payload = {key: task[key] for key in ("paper_id", "figure", "slots", "evidence", "crop_evidence_id")}
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


def prepare(output_root: Path, model: str) -> dict[str, Any]:
    """Persist exactly two local immutable requests; this function has no client."""
    if not model:
        raise ValueError("model is required")
    if not PDF_PATH.is_file() or not HTML_PATH.is_file():
        raise FileNotFoundError("Committed NP-002 PDF and HTML are required")
    root = (output_root / PAPER_ID).resolve()
    root.mkdir(parents=True, exist_ok=True)
    html_source = HTML_PATH.read_text(encoding="utf-8")
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
            "evidence": [{"evidence_id": crop_evidence_id, "source_id": "PDF crop", "text": f"Rendered {spec['figure']} crop."}, *spec["evidence"]],
            "allowed_evidence_ids": [crop_evidence_id, *[row["evidence_id"] for row in spec["evidence"]]],
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
    unsigned = {"preflight_version": PREFLIGHT_VERSION, "paper_id": PAPER_ID, "model": model, "provider_calls": 0, "human_approval_required": True, "requests": requests}
    manifest = {**unsigned, "manifest_sha256": _sha256(_canonical_json(unsigned))}
    _write_json(root / "manifest.json", manifest)
    return manifest


def _allowed_ids(task: Mapping[str, Any]) -> set[str]:
    values = task.get("allowed_evidence_ids")
    if isinstance(values, list):
        return {value for value in values if isinstance(value, str)}
    evidence = task.get("evidence", [])
    return {row["evidence_id"] for row in evidence if isinstance(row, Mapping) and isinstance(row.get("evidence_id"), str)}


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
    outcome_ids: set[str] = set()
    for outcome in parsed.outcomes:
        if outcome.slot_id not in expected:
            raise ValueError("outcome links an invented slot")
        if outcome.slot_id in outcome_ids:
            raise ValueError("each slot may have exactly once returned outcome")
        outcome_ids.add(outcome.slot_id)
        slot = expected[outcome.slot_id]
        for field in ("formulation", "payload", "dose", "recipient_cell", "assay", "endpoint"):
            if getattr(outcome, field) != getattr(slot, field):
                raise ValueError(f"outcome identity changed {field}")
        unknown = set(outcome.evidence_ids) - allowed_evidence
        if unknown:
            raise ValueError("outcome cites evidence outside the task envelope")
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
