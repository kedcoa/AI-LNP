"""Independently verify merged Day 8 records against their original crop/page."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz
from dotenv import load_dotenv
from openai import OpenAI

from .merge_day8_evidence import OUTPUT
from .pdf_multimodal_contracts import EvidenceVerification, MergedEvidenceRecord
from .run_abstract_first import ROOT
from .run_day8_pdf import RAW_ROOT


def data_url(path: Path) -> str:
    media = "image/png" if path.suffix.lower() == ".png" else "application/pdf"
    return f"data:{media};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def find_pdf(file_name: str) -> Path:
    matches = list(RAW_ROOT.glob(f"PMC*/{file_name}"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one source PDF for {file_name}; found {len(matches)}")
    return matches[0]


def pages_pdf(path: Path, pages: list[int]) -> bytes:
    source = fitz.open(path)
    valid_pages = sorted(set(page for page in pages if 1 <= page <= source.page_count))
    if not valid_pages:
        raise ValueError(f"No valid pages {pages} for {path.name}")
    target = fitz.open()
    for page in valid_pages:
        target.insert_pdf(source, from_page=page - 1, to_page=page - 1)
    return target.tobytes(garbage=4, deflate=True)


def page_pdf(path: Path, page: int) -> bytes:
    return pages_pdf(path, [page])


def evidence_content(record: MergedEvidenceRecord) -> list[dict]:
    content: list[dict] = [{
        "type": "input_text",
        "text": json.dumps({
            "task": "Independently verify this one proposed scientific evidence record.",
            "record": record.model_dump(mode="json"),
            "source_contexts": [
                {
                    "source_id": source.source_id,
                    "complete_reconstructed_caption_or_text": source.source_context,
                    "original_pdf_pages_attached": source.source_pages or [source.page],
                }
                for source in record.sources
            ],
            "rules": [
                "Check the proposed value, unit, group, endpoint, panel/cell, and evidence quote against the attached original source.",
                "Return retain only when the source directly supports the record.",
                "Return correct with corrected_value/unit for a transcription error.",
                "Return reject for unsupported inference, axis-derived precision, wrong experiment, or wrong group.",
                "Return human_review when the source is ambiguous or too low resolution.",
                "A graph without a printed data label supports qualitative direction, not an exact number.",
                "Every source_id checked must be listed.",
            ],
        }, ensure_ascii=False),
    }]
    seen: set[tuple[str, int, str | None]] = set()
    for source in record.sources:
        identity = (source.file_name, source.page, source.crop_path)
        if identity in seen:
            continue
        seen.add(identity)
        if source.crop_path:
            path = ROOT / source.crop_path
            content.append({
                "type": "input_image", "image_url": data_url(path), "detail": "original",
            })
        pages = source.source_pages or [source.page]
        raw = pages_pdf(find_pdf(source.file_name), pages)
        page_label = "-".join(str(page) for page in pages)
        content.append({
            "type": "input_file",
            "filename": f"{Path(source.file_name).stem}-pages-{page_label}.pdf",
            "file_data": "data:application/pdf;base64," + base64.b64encode(raw).decode("ascii"),
        })
    return content


def verify(client: OpenAI, model: str, record: MergedEvidenceRecord) -> tuple[EvidenceVerification, dict]:
    response = client.responses.parse(
        model=model,
        input=[{"role": "user", "content": evidence_content(record)}],
        text_format=EvidenceVerification,
        timeout=300.0,
    )
    if response.output_parsed is None:
        raise ValueError("Verifier returned no parsed disposition")
    return response.output_parsed, {
        "id": response.id,
        "model": response.model,
        "usage": response.usage.model_dump() if response.usage else None,
        "output_text": response.output_text,
    }


def run(
    only_review_required: bool = False,
    limit: int | None = None,
    workers: int = 4,
    retry_human_review: bool = False,
) -> dict:
    load_dotenv(ROOT / ".env")
    model = os.getenv("DAY8_VERIFIER_MODEL", os.getenv("DAY8_OPENAI_MODEL", "gpt-5.6"))
    records = [
        MergedEvidenceRecord.model_validate(row)
        for row in json.loads((OUTPUT / "merged_evidence.json").read_text())
    ]
    if only_review_required:
        records = [row for row in records if row.requires_human_review]
    if limit is not None:
        records = records[:limit]
    result_dir = OUTPUT / "verification"
    result_dir.mkdir(parents=True, exist_ok=True)
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=300.0, max_retries=2)
    results: list[EvidenceVerification] = []
    cache_hits = 0
    pending: list[MergedEvidenceRecord] = []
    for record in records:
        validated_path = result_dir / f"{record.merged_record_id}.validated.json"
        if retry_human_review and validated_path.exists():
            prior = EvidenceVerification.model_validate_json(validated_path.read_text())
            if prior.disposition == "human_review":
                for suffix in ("validated.json", "response.json"):
                    current = result_dir / f"{record.merged_record_id}.{suffix}"
                    archive = result_dir / f"{record.merged_record_id}.pre_caption_fix.{suffix}"
                    if current.exists() and not archive.exists():
                        shutil.copy2(current, archive)
                pending.append(record)
                continue
        if validated_path.exists():
            result = EvidenceVerification.model_validate_json(validated_path.read_text())
            results.append(result)
            cache_hits += 1
        else:
            pending.append(record)

    def run_one(record: MergedEvidenceRecord) -> EvidenceVerification:
        result, raw = verify(client, model, record)
        (result_dir / f"{record.merged_record_id}.validated.json").write_text(
            result.model_dump_json(indent=2) + "\n"
        )
        (result_dir / f"{record.merged_record_id}.response.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
        )
        return result

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(run_one, record): record for record in pending}
        for future in as_completed(futures):
            results.append(future.result())
    manifest = {
        "model": model,
        "requested": len(records),
        "verified": len(results),
        "cache_hits": cache_hits,
        "dispositions": {
            disposition: sum(row.disposition == disposition for row in results)
            for disposition in ("retain", "correct", "reject", "human_review")
        },
    }
    (OUTPUT / "verification_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-review-required", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retry-human-review", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(
        args.only_review_required,
        args.limit,
        args.workers,
        args.retry_human_review,
    ), indent=2))
