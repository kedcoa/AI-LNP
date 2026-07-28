"""Make the single authorized GP-008 G1 repair call, validate, and merge it."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ConfigDict, BaseModel, Field

from src.extraction.compact_contracts import (
    CompactExtractionResponse,
    ExperimentRecord,
    OutcomeRecord,
)
from src.rag.compact_api_packet import CompactApiPacket


ROOT = Path(__file__).resolve().parents[2]
TASK_PATH = ROOT / "reports/extraction/day5_afternoon_g1/GP-008-repair-request.json"
PACKET_PATH = ROOT / "data/staging/rag/compact_api_packets_v1_1/GP-008.json"
BASE_PATH = (
    ROOT / "data/staging/extraction/compact_merged_v1/GP-008/final_result.json"
)
OUTPUT_ROOT = ROOT / "data/staging/extraction/day5_gp008_repair_v1"
MERGED_PATH = (
    ROOT
    / "data/staging/extraction/compact_merged_v1_1/GP-008/final_result.json"
)
PROMPT_VERSION = "day5-g1-gp008-repair-1.0.0"
PROMPT = """Return exactly one new in-vitro experiment and exactly two new
outcomes using only the supplied evidence. Do not change existing records.
Keep >80 and <20 as distinct outcomes and preserve the inequality meaning.
The unmodified LNP result is the comparator to targeted alpha-CD163 LNP.
Use only supplied evidence IDs. Use missing fields when the evidence does not
report a value. Do not attach these records to the existing in-vivo experiment."""


class RepairFragment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment: ExperimentRecord
    outcomes: list[OutcomeRecord] = Field(min_length=2, max_length=2)
    explanation: str = Field(min_length=1, max_length=500)


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def strict_schema(value: object) -> object:
    """Make every object property required for OpenAI strict structured output."""
    if isinstance(value, list):
        return [strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: strict_schema(item) for key, item in value.items()}
    properties = result.get("properties")
    if isinstance(properties, dict):
        result["required"] = list(properties)
        result["additionalProperties"] = False
    return result


def run() -> dict:
    task = json.loads(TASK_PATH.read_text(encoding="utf-8"))
    packet = CompactApiPacket.model_validate_json(
        PACKET_PATH.read_text(encoding="utf-8")
    )
    base = CompactExtractionResponse.model_validate_json(
        BASE_PATH.read_text(encoding="utf-8")
    )
    evidence = [
        item
        for candidate in task["candidates"]
        for item in candidate["evidence"]
    ]
    allowed = {item["evidence_id"] for item in evidence}
    model = os.getenv("NARROW_REPAIR_MODEL", "gpt-5.6-terra")
    schema = strict_schema(RepairFragment.model_json_schema())
    fingerprint = hashlib.sha256(
        canonical(
            {
                "task": task,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "schema": schema,
            }
        ).encode()
    ).hexdigest()
    run_dir = OUTPUT_ROOT / fingerprint
    result_path = run_dir / "result.json"
    manifest_path = run_dir / "manifest.json"
    if result_path.exists() and manifest_path.exists():
        return {
            **json.loads(manifest_path.read_text(encoding="utf-8")),
            "cache_hit": True,
            "paid_api_requests_this_run": 0,
        }
    if run_dir.exists():
        raise FileExistsError("Incomplete run directory exists; refusing a retry")
    run_dir.mkdir(parents=True)
    payload = {
        "paper_id": "GP-008",
        "existing_formulation_ids": [
            item.formulation_id for item in base.formulations
        ],
        "reserved_experiment_ids": [
            item.experiment_id for item in base.experiments
        ],
        "reserved_outcome_ids": [item.outcome_id for item in base.outcomes],
        "required_output": task["required_fragment"],
        "evidence": evidence,
    }
    request = {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "system_prompt": PROMPT,
        "payload": payload,
        "fingerprint": fingerprint,
    }
    (run_dir / "request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    load_dotenv(ROOT / ".env")
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=300,
        max_retries=0,
    )
    started = datetime.now(timezone.utc)
    response = client.responses.create(
        model=model,
        reasoning={"effort": "low"},
        store=False,
        service_tier="default",
        max_output_tokens=3_500,
        input=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": canonical(payload)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "GP008RepairFragment",
                "schema": schema,
                "strict": True,
            }
        },
    )
    completed = datetime.now(timezone.utc)
    (run_dir / "response.json").write_text(
        json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    if not response.output_text:
        raise RuntimeError("The authorized repair returned no structured output")
    fragment = RepairFragment.model_validate_json(response.output_text)
    if fragment.experiment.experimental_context.value != "in_vitro":
        raise ValueError("Repair experiment is not in vitro")
    if fragment.experiment.formulation_id not in {
        item.formulation_id for item in base.formulations
    }:
        raise ValueError("Repair references an unknown formulation")
    if fragment.experiment.experiment_id in {
        item.experiment_id for item in base.experiments
    }:
        raise ValueError("Repair reused an existing experiment ID")
    if any(
        row.experiment_id != fragment.experiment.experiment_id
        for row in fragment.outcomes
    ):
        raise ValueError("Repair outcomes do not link to the new experiment")
    if {row.outcome_id for row in fragment.outcomes} & {
        row.outcome_id for row in base.outcomes
    }:
        raise ValueError("Repair reused an existing outcome ID")
    for record in [fragment.experiment, *fragment.outcomes]:
        for field_name in record.__class__.model_fields:
            value = getattr(record, field_name)
            evidence_ids = getattr(value, "evidence_ids", [])
            unknown = set(evidence_ids) - allowed
            if unknown:
                raise ValueError(f"Repair cited unknown evidence IDs: {sorted(unknown)}")
    used = {
        evidence_id
        for record in [fragment.experiment, *fragment.outcomes]
        for field_name in record.__class__.model_fields
        for evidence_id in getattr(getattr(record, field_name), "evidence_ids", [])
    }
    if used != allowed:
        raise ValueError("Repair did not use both required evidence passages")

    merged_dict = base.model_dump(mode="json")
    merged_dict["experiments"].append(fragment.experiment.model_dump(mode="json"))
    merged_dict["outcomes"].extend(
        row.model_dump(mode="json") for row in fragment.outcomes
    )
    merged = CompactExtractionResponse.model_validate(merged_dict)
    merged.validate_evidence_ids({row.evidence_id for row in packet.evidence})
    MERGED_PATH.parent.mkdir(parents=True, exist_ok=True)
    MERGED_PATH.write_text(merged.model_dump_json(indent=2) + "\n", encoding="utf-8")
    result_path.write_text(fragment.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest = {
        "status": "completed_validated_merged",
        "paper_id": "GP-008",
        "model_requested": model,
        "model_returned": response.model,
        "response_id": response.id,
        "paid_api_requests": 1,
        "cache_hit": False,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
        "result_path": str(result_path),
        "merged_path": str(MERGED_PATH),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
