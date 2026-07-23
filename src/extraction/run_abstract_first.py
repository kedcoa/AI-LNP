"""Run evidence-gated, abstract-only extraction on the frozen gold papers."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIError, APITimeoutError, OpenAI
from pydantic import ValidationError

from .contracts import ExtractionBundle


ROOT = Path(__file__).resolve().parents[2]
GOLD_PAPERS = ROOT / "data" / "annotations" / "gold_v1" / "papers.csv"
METADATA = ROOT / "data" / "staging" / "searches" / "screening_metadata.jsonl"
OUTPUT = ROOT / "data" / "staging" / "extraction" / "abstract_first_v1"

SYSTEM_PROMPT = """You extract LNP information only from the supplied title and abstract.
Do not use outside knowledge. Do not infer ratios, units, chemical identities, component
roles, comparators, outcomes, or experimental details. Every reported value must quote
an abstract evidence record. Use explicit missing values for fields not stated. Screening
has already happened separately. Return only one JSON object matching the supplied schema.
If eligible_records_expected is false, return empty entity and evidence lists."""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def gold_inputs() -> list[dict[str, Any]]:
    with GOLD_PAPERS.open(newline="", encoding="utf-8") as handle:
        papers = list(csv.DictReader(handle))
    metadata = {row["candidate_id"]: row for row in load_jsonl(METADATA)}
    inputs = []
    for paper in papers:
        source = metadata[paper["candidate_id"]]
        inputs.append(
            {
                "paper_id": paper["gold_paper_id"],
                "screening_cell_type": paper["screening_cell_type"],
                "screening_decision": paper["screening_decision"],
                "eligible_records_expected": paper["screening_decision"] != "exclude",
                "title": source["title"],
                "abstract": source["abstract"],
            }
        )
    return inputs


def extract_one(client: OpenAI, model: str, item: dict[str, Any]) -> tuple[dict[str, Any], ExtractionBundle]:
    prompt = {
        "instructions": {
            "paper_id": item["paper_id"],
            "screening_cell_type": item["screening_cell_type"],
            "screening_decision": item["screening_decision"],
            "eligible_records_expected": item["eligible_records_expected"],
            "id_rules": "Use IDs beginning AF-, followed by paper ID and entity type.",
        },
        "source": {"title": item["title"], "abstract": item["abstract"]},
        "schema": ExtractionBundle.model_json_schema(),
    }
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_completion_tokens=6000,
        timeout=90.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    )
    content = response.choices[0].message.content or ""
    raw = json.loads(content)
    return raw, ExtractionBundle.model_validate(raw)


def run(limit: int | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    api_key = os.environ["SENSENOVA_API_KEY"]
    base_url = os.getenv("SENSENOVA_BASE_URL", "https://token.sensenova.cn/v1")
    model = os.getenv("SENSENOVA_MODEL", "sensenova-6.7-flash-lite")
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=2, timeout=90.0)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    items = gold_inputs()[:limit]
    manifest: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "source_scope": "title_and_abstract_only",
        "contract_version": "1.0.0",
        "papers": [],
    }
    for item in items:
        paper_id = item["paper_id"]
        output_path = OUTPUT / f"{paper_id}.json"
        if output_path.exists():
            manifest["papers"].append({"paper_id": paper_id, "status": "reused_validated"})
            continue
        raw: dict[str, Any] | None = None
        try:
            raw, validated = extract_one(client, model, item)
            output_path.write_text(
                json.dumps(validated.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest["papers"].append({"paper_id": paper_id, "status": "validated"})
        except (json.JSONDecodeError, ValidationError, KeyError, TypeError, APIError, APITimeoutError) as error:
            if raw is not None:
                (OUTPUT / f"{paper_id}.invalid.json").write_text(
                    json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
            manifest["papers"].append(
                {"paper_id": paper_id, "status": "validation_error", "error": str(error)}
            )
    (OUTPUT / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    result = run(args.limit)
    print(json.dumps(result, indent=2))
