"""Run one provenance-gated ChatPDF extraction message for one PDF."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from src.extraction.chatpdf_client import ChatPdfClient
from src.extraction.chatpdf_contracts import parse_extraction_response


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_prompt(paper_id: str) -> str:
    schema = {
        "paper_id": paper_id,
        "arms": [{
            "arm_id": "A1",
            "lnp_name": None,
            "chemical_formulation_total": None,
            "lnp_molar_ratio": None,
            "ionizable_lipid": None,
            "helper_lipid": None,
            "cholesterol": None,
            "peg_lipid": None,
            "others": None,
            "species": None,
            "biological_model": None,
            "target_or_recipient_organ": None,
            "intended_target_cell": None,
            "observed_transfected_cell": None,
            "payload": None,
            "encoded_product": None,
            "molecular_target": None,
            "dose": None,
            "route": None,
            "timepoint": None,
            "assay": None,
            "outcomes": [{
                "outcome_id": "O1",
                "endpoint": None,
                "quantitative_value": None,
                "unit": None,
                "normalization_basis": None,
                "qualitative_outcome": None,
                "evidence": {
                    "endpoint": [{"page": 1, "quote": "exact quotation"}]
                },
            }],
            "evidence": {
                "payload": [{"page": 1, "quote": "exact quotation"}]
            },
        }],
    }
    return (
        f"Extract every LNP administration arm from paper {paper_id}. Return a JSON object only; "
        "no markdown fences and no explanation. One arm means one unique combination of LNP "
        "formulation/intervention, biological model, payload, dose, route, and timepoint. Do not "
        "create separate arms merely because several outcomes or cell subgroups were measured; "
        "put all outcomes under the same arm. If a setup sentence is a shared protocol for several "
        "experiments, apply it only to the arms it explicitly governs. Separate "
        "target_or_recipient_organ, intended_target_cell, and observed_transfected_cell. Observed "
        "expression, uptake, staining, or transfection does not prove intentional targeting. Use "
        "null when the paper does not report a value. For every non-null field, provide an exact "
        "quotation and one-based PDF page in that field's evidence array. Extract LNP name, total "
        "chemical formulation, molar ratio, lipid components, other ligands, species, biological "
        "model, target organ/cell semantics, payload, encoded product, molecular target, dose, "
        "route, timepoint, assay, and every quantitative or qualitative outcome. Use exactly this "
        f"shape and no additional keys: {json.dumps(schema, separators=(',', ':'))}"
    )


def build_preflight(paper_id: str, pdf_path: Path) -> dict[str, Any]:
    pdf = Path(pdf_path)
    pages = len(PdfReader(pdf).pages)
    if pages > 74:
        raise ValueError("single-pilot PDF exceeds the approved 74-page ceiling")
    prompt = build_prompt(paper_id)
    return {
        "schema_version": "chatpdf-single-gap-pilot/v1",
        "paper_id": paper_id,
        "pdf_path": str(pdf.resolve()),
        "pdf_sha256": _sha256_file(pdf),
        "pdf_pages": pages,
        "upload_requests": 1,
        "message_requests": 1,
        "maximum_message_requests": 1,
        "silent_retries": 0,
        "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
    }


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def validate_local_quotes(payload: dict[str, Any], pdf_path: Path) -> dict[str, Any]:
    pages = [page.extract_text() or "" for page in PdfReader(pdf_path).pages]
    checks: list[dict[str, Any]] = []

    def check_evidence(label: str, evidence: dict[str, Any]) -> None:
        for field_name, citations in evidence.items():
            for citation in citations:
                page = citation["page"]
                quote = citation["quote"]
                supported = 1 <= page <= len(pages) and _normalized(quote) in _normalized(pages[page - 1])
                checks.append({
                    "field": f"{label}.{field_name}", "page": page,
                    "quote": quote, "supported": supported,
                })

    for arm in payload.get("arms", []):
        check_evidence(arm["arm_id"], arm.get("evidence", {}))
        for outcome in arm.get("outcomes", []):
            check_evidence(
                f"{arm['arm_id']}.{outcome['outcome_id']}",
                outcome.get("evidence", {}),
            )
    return {
        "checks": checks,
        "supported": sum(row["supported"] for row in checks),
        "unsupported": sum(not row["supported"] for row in checks),
    }


def run_single_pilot(
    *, paper_id: str, pdf_path: Path, output_dir: Path
) -> dict[str, Any]:
    preflight = build_preflight(paper_id, pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "preflight.json").write_text(
        json.dumps(preflight, indent=2) + "\n", encoding="utf-8"
    )
    prompt = build_prompt(paper_id)
    client = ChatPdfClient()
    source_id = client.add_file(pdf_path)
    message_payload = {
        "sourceId": source_id,
        "messages": [{"role": "user", "content": prompt}],
        "referenceSources": True,
    }
    message_hash = _sha256_bytes(
        json.dumps(message_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    response = client.ask(source_id, prompt, reference_sources=True)
    raw_record = {
        "paper_id": paper_id,
        "source_id": source_id,
        "message_request_sha256": message_hash,
        "response_sha256": _sha256_bytes(
            json.dumps(response.raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "response": response.raw,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "raw_response.json").write_text(
        json.dumps(raw_record, indent=2) + "\n", encoding="utf-8"
    )
    try:
        extraction = parse_extraction_response(response.content)
    except ValueError as error:
        report = {
            **preflight,
            "source_id": source_id,
            "message_request_sha256": message_hash,
            "contract_status": "rejected",
            "contract_error": str(error),
            "database_writes": 0,
        }
    else:
        quote_validation = validate_local_quotes(extraction.raw, pdf_path)
        report = {
            **preflight,
            "source_id": source_id,
            "message_request_sha256": message_hash,
            "contract_status": "accepted" if quote_validation["unsupported"] == 0 else "rejected",
            "extraction": asdict(extraction),
            "quote_validation": quote_validation,
            "database_writes": 0,
        }
    (output_dir / "validated_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


__all__ = ["build_preflight", "build_prompt", "run_single_pilot"]
