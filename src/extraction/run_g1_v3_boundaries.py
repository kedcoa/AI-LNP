"""Dual-reader experiment-boundary detection for the v3 G1 attempt."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .contracts_v3 import ExperimentMapV3, SourceSentenceV3
from .run_abstract_first import ROOT, gold_inputs


OUTPUT = ROOT / "data" / "staging" / "extraction" / "g1_v3_boundaries"


def split_sentences(text: str) -> list[SourceSentenceV3]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if part.strip()]
    return [SourceSentenceV3(sentence_id=f"S{index:02d}", text=part) for index, part in enumerate(parts, 1)]


def call_reader(client: OpenAI, model: str, item: dict[str, Any], reader_id: str, sentences: list[SourceSentenceV3]):
    payload = {
        "paper_id": item["paper_id"],
        "reader_id": reader_id,
        "title": item["title"],
        "sentences": [sentence.model_dump() for sentence in sentences],
        "task": "Identify distinct original experimental events before extracting detailed fields.",
        "rules": [
            "Return one experiment when treatment/payload, biological model, disease context, recipient population, dose, route, or timepoint materially differs.",
            "Healthy, fibrotic, cirrhotic, spontaneous tumor, primary xenograft, and secondary xenograft contexts are distinct experiments when separately reported.",
            "Different payloads are distinct experiments unless an explicit combination treatment is reported.",
            "Do not create an experiment for background, motivation, or general conclusions.",
            "Evidence sentence IDs must directly describe that experiment.",
            "The anchor quote must be verbatim from one cited sentence.",
            "Do not infer cell identity, species, or model details from outside knowledge.",
        ],
        "schema": ExperimentMapV3.model_json_schema(),
    }
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_completion_tokens=10000,
        timeout=120.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": f"You are {reader_id}, an independent scientific experiment-boundary reader. Return valid JSON only."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    choice = response.choices[0]
    envelope = {"model": response.model, "finish_reason": choice.finish_reason, "content": choice.message.content, "usage": response.usage.model_dump() if response.usage else None}
    return envelope, ExperimentMapV3.model_validate_json(choice.message.content or "")


def validate_map(result: ExperimentMapV3, sentences: list[SourceSentenceV3]) -> list[str]:
    errors = []
    lookup = {sentence.sentence_id: sentence.text for sentence in sentences}
    for experiment in result.experiments:
        unknown = set(experiment.evidence_sentence_ids) - set(lookup)
        if unknown:
            errors.append(f"{experiment.reader_experiment_key}: unknown sentences {sorted(unknown)}")
        if not any(experiment.experiment_anchor_quote in lookup.get(sentence_id, "") for sentence_id in experiment.evidence_sentence_ids):
            errors.append(f"{experiment.reader_experiment_key}: anchor quote not in cited sentences")
    return errors


def run(paper_ids: set[str] | None = None, reader_ids: set[str] | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    model_a = os.getenv("G1_V3_READER_A_MODEL", "deepseek-v4-flash")
    model_b = os.getenv("G1_V3_READER_B_MODEL", "glm-5.2")
    client = OpenAI(api_key=os.environ["SENSENOVA_API_KEY"], base_url=os.getenv("SENSENOVA_BASE_URL"), timeout=120.0, max_retries=1)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"run_at": datetime.now(timezone.utc).isoformat(), "models": {"reader_a": model_a, "reader_b": model_b}, "papers": []}
    for item in gold_inputs():
        if paper_ids and item["paper_id"] not in paper_ids:
            continue
        paper_dir = OUTPUT / item["paper_id"]
        paper_dir.mkdir(parents=True, exist_ok=True)
        sentences = split_sentences(item["abstract"])
        (paper_dir / "sentences.json").write_text(json.dumps([row.model_dump() for row in sentences], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if not item["eligible_records_expected"]:
            for reader_id in ("reader_a", "reader_b"):
                empty = ExperimentMapV3(contract_version="3.0.0", paper_id=item["paper_id"], reader_id=reader_id, original_experiments_present=False, experiments=[])
                (paper_dir / f"{reader_id}.validated.json").write_text(empty.model_dump_json(indent=2) + "\n", encoding="utf-8")
            manifest["papers"].append({"paper_id": item["paper_id"], "status": "expected_zero"})
            continue
        reader_status = []
        for reader_id in ("reader_a", "reader_b"):
            if reader_ids and reader_id not in reader_ids:
                continue
            try:
                reader_model = model_a if reader_id == "reader_a" else model_b
                envelope, result = call_reader(client, reader_model, item, reader_id, sentences)
                (paper_dir / f"{reader_id}.response.json").write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                errors = validate_map(result, sentences)
                if errors:
                    (paper_dir / f"{reader_id}.validation_warnings.json").write_text(json.dumps(errors, indent=2) + "\n", encoding="utf-8")
                (paper_dir / f"{reader_id}.validated.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
                reader_status.append({"reader": reader_id, "status": "validated_with_warnings" if errors else "validated", "experiments": len(result.experiments), "warnings": len(errors)})
            except Exception as error:
                reader_status.append({"reader": reader_id, "status": "rejected", "error": str(error)})
        manifest["papers"].append({"paper_id": item["paper_id"], "status": "complete" if all(x["status"] in {"validated", "validated_with_warnings"} for x in reader_status) else "incomplete", "readers": reader_status})
    (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    parser.add_argument("--reader-id", action="append", choices=["reader_a", "reader_b"])
    args = parser.parse_args()
    print(json.dumps(run(set(args.paper_id) if args.paper_id else None, set(args.reader_id) if args.reader_id else None), indent=2))
