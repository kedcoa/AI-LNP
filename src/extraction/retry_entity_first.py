"""Retry failed abstract extraction as small, fully logged entity requests."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from .run_abstract_first import ROOT, gold_inputs


OUTPUT = ROOT / "data" / "staging" / "extraction" / "abstract_entity_retry_v1"
FAILED = {"GP-005", "GP-006", "GP-007"}
ENTITY_TYPES = ("formulation", "component", "experiment", "outcome")


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_name: str
    value: str | float | None
    value_status: Literal["reported", "missing"]
    evidence_quote: str | None
    confidence: Literal["high", "medium", "low"]
    missing_reason: str | None


class EntityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: Literal["formulation", "component", "experiment", "outcome"]
    records: list[list[Fact]] = Field(default_factory=list)


def run() -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    model = os.getenv("SENSENOVA_MODEL", "sensenova-6.7-flash-lite")
    client = OpenAI(
        api_key=os.environ["SENSENOVA_API_KEY"],
        base_url=os.getenv("SENSENOVA_BASE_URL", "https://token.sensenova.cn/v1"),
        max_retries=1,
        timeout=90.0,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"run_at": datetime.now(timezone.utc).isoformat(), "model": model, "requests": []}
    for item in gold_inputs():
        if item["paper_id"] not in FAILED:
            continue
        for entity_type in ENTITY_TYPES:
            stem = f"{item['paper_id']}.{entity_type}"
            prompt = {
                "task": f"Extract only {entity_type} facts explicitly stated in the title/abstract.",
                "rules": [
                    "Use no outside knowledge and make no inferences.",
                    "Each record is a list of field facts.",
                    "For reported facts quote exact supporting abstract text.",
                    "Use missing only inside an otherwise identifiable record.",
                    "Return JSON with entity_type and records only.",
                ],
                "required_fact_keys": ["field_name", "value", "value_status", "evidence_quote", "confidence", "missing_reason"],
                "paper_id": item["paper_id"],
                "title": item["title"],
                "abstract": item["abstract"],
            }
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                max_completion_tokens=2500,
                timeout=90.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a literal scientific abstract extractor. Return valid JSON only."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            )
            choice = response.choices[0]
            envelope = {
                "paper_id": item["paper_id"],
                "entity_type": entity_type,
                "model": response.model,
                "finish_reason": choice.finish_reason,
                "content": choice.message.content,
                "usage": response.usage.model_dump() if response.usage else None,
            }
            (OUTPUT / f"{stem}.response.json").write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            try:
                parsed = EntityResponse.model_validate_json(choice.message.content or "")
                if parsed.entity_type != entity_type:
                    raise ValueError("response entity_type does not match request")
                (OUTPUT / f"{stem}.validated.json").write_text(parsed.model_dump_json(indent=2) + "\n", encoding="utf-8")
                status, error = "validated", None
            except Exception as exc:
                status, error = "rejected", str(exc)
            manifest["requests"].append({"paper_id": item["paper_id"], "entity_type": entity_type, "status": status, "error": error})
    (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
