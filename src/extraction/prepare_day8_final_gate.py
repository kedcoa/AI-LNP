"""Build a deduplicated, bundled, cache-addressed Batch API Day 8 workload."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from openai.lib._pydantic import to_strict_json_schema

from .pdf_multimodal_contracts import ObjectVisionExtraction, ReconstructedDocumentObject
from .run_abstract_first import ROOT


OUTPUT = ROOT / "data/staging/extraction/day8_final_gate"
OBJECT_OUTPUT = ROOT / "data/staging/extraction/day8_object_vision"
SYSTEM_PROMPT = """You extract exhaustive, source-grounded scientific evidence from reconstructed
PDF figures and tables. Process every supplied object and return one extraction per object_id.
Transcribe every readable panel label, legend, group, timepoint, sample size, significance mark,
printed data label, table cell, and all Q1-Q4 values for every flow plot. Exact numeric facts are
allowed only when visibly printed; never infer exact values from axis position. Preserve qualitative
comparisons when values are not printed. Mark ambiguity or unreadability for human review."""


class ObjectExtractionBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extractions: list[ObjectVisionExtraction]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def optimize(rows: list[ReconstructedDocumentObject]) -> tuple[list[dict], list[ReconstructedDocumentObject]]:
    inventory: list[dict] = []
    canonical: list[ReconstructedDocumentObject] = []
    seen_exact: dict[str, str] = {}
    for row in rows:
        crop = ROOT / row.crop_path
        digest = sha256(crop)
        duplicate_of = seen_exact.get(digest)
        duplicate_kind = "exact" if duplicate_of else None
        if duplicate_of is None:
            canonical.append(row)
            seen_exact[digest] = row.object_id
        inventory.append({
            **row.model_dump(mode="json"),
            "crop_sha256": digest,
            "duplicate_of": duplicate_of,
            "duplicate_kind": duplicate_kind,
        })
    return inventory, canonical


def bundles(rows: list[ReconstructedDocumentObject], size: int) -> list[list[ReconstructedDocumentObject]]:
    grouped: dict[tuple[str, str], list[ReconstructedDocumentObject]] = defaultdict(list)
    for row in rows:
        grouped[(row.paper_id, row.source_file)].append(row)
    result = []
    for group in grouped.values():
        group.sort(key=lambda row: (row.page, row.object_id))
        result.extend(group[index:index + size] for index in range(0, len(group), size))
    return result


def request(bundle: list[ReconstructedDocumentObject], model: str) -> dict:
    content: list[dict] = [{
        "type": "input_text",
        "text": json.dumps({
            "objects": [{
                "object_id": row.object_id,
                "paper_id": row.paper_id,
                "source_file": row.source_file,
                "page": row.page,
                "label": row.label,
                "complete_caption": row.caption,
                "surrounding_text": row.surrounding_text,
            } for row in bundle]
        }, ensure_ascii=False),
    }]
    for row in bundle:
        content.extend([
            {"type": "input_text", "text": f"IMAGE FOR OBJECT_ID: {row.object_id}"},
            {"type": "input_image", "image_url": data_url(ROOT / row.crop_path), "detail": "original"},
        ])
    # Generate the bundle as one Pydantic schema so all $defs live at the schema root.
    schema = to_strict_json_schema(ObjectExtractionBundle)
    identity = hashlib.sha256(
        (SYSTEM_PROMPT + model + "".join(sha256(ROOT / row.crop_path) for row in bundle)).encode()
    ).hexdigest()
    return {
        "custom_id": f"day8-{identity[:24]}",
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
                {"role": "user", "content": content},
            ],
            "text": {"format": {
                "type": "json_schema",
                "name": "day8_object_bundle",
                "schema": schema,
                "strict": True,
            }},
            "prompt_cache_key": "day8-object-extraction-v3",
        },
        "_local": {
            "cache_key": identity,
            "object_ids": [row.object_id for row in bundle],
        },
    }


def run(bundle_size: int = 4, model: str = "gpt-5.4") -> dict:
    rows = [
        ReconstructedDocumentObject.model_validate(row)
        for row in json.loads((OBJECT_OUTPUT / "object_inventory.json").read_text())
    ]
    inventory, canonical = optimize(rows)
    work = bundles(canonical, bundle_size)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "optimized_object_inventory.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n"
    )
    batch_path = OUTPUT / "object_extraction_batch.jsonl"
    index_path = OUTPUT / "request_index.jsonl"
    index_path.unlink(missing_ok=True)
    with batch_path.open("w", encoding="utf-8") as handle:
        for bundle in work:
            row = request(bundle, model)
            local = row.pop("_local")
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            with index_path.open("a", encoding="utf-8") as index:
                index.write(json.dumps({"custom_id": row["custom_id"], **local}) + "\n")
    manifest = {
        "model": model,
        "inventory_objects": len(rows),
        "canonical_objects": len(canonical),
        "deduplicated_objects": len(rows) - len(canonical),
        "batch_requests": len(work),
        "bundle_size": bundle_size,
        "estimated_call_reduction_vs_one_object_per_call": (
            1 - len(work) / len(rows) if rows else 0
        ),
        "batch_file": str(batch_path.relative_to(ROOT)),
    }
    (OUTPUT / "workload_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-size", type=int, default=4)
    parser.add_argument("--model", default="gpt-5.4")
    args = parser.parse_args()
    print(json.dumps(run(args.bundle_size, args.model), indent=2))
