"""Extract detailed fields inside frozen experiment boundaries and verify twice."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .contracts_v3_fields import (
    ExperimentScopedExtractionV3,
    PaperVerificationV3,
    SourceValueV3,
)
from .run_abstract_first import ROOT, gold_inputs


BOUNDARIES = ROOT / "data" / "staging" / "extraction" / "g1_v3_frozen_boundaries"
SENTENCES = ROOT / "data" / "staging" / "extraction" / "g1_v3_boundaries"
OUTPUT = ROOT / "data" / "staging" / "extraction" / "g1_v3_fields"


def normalized(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def envelope(response: Any) -> dict[str, Any]:
    choice = response.choices[0]
    return {
        "model": response.model,
        "finish_reason": choice.finish_reason,
        "content": choice.message.content,
        "usage": response.usage.model_dump() if response.usage else None,
    }


def call_json(client: OpenAI, model: str, system: str, payload: dict[str, Any], max_tokens: int):
    return client.chat.completions.create(
        model=model, temperature=0, max_completion_tokens=max_tokens, timeout=120.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )


def extract_one(client: OpenAI, model: str, item: dict[str, Any], boundary: dict[str, Any],
                source_sentences: list[dict[str, str]], paper_dir: Path) -> ExperimentScopedExtractionV3:
    allowed_ids = boundary["evidence_sentence_ids"]
    scoped = [row for row in source_sentences if row["sentence_id"] in allowed_ids]
    payload = {
        "paper_id": item["paper_id"],
        "frozen_experiment": boundary,
        "approved_source_sentences_only": scoped,
        "rules": [
            "Extract only this one frozen experiment and only from approved_source_sentences_only.",
            "Every reported SourceValue requires one exact sentence ID and a verbatim quote that directly supports that field.",
            "If the approved sentences do not explicitly establish a value, mark it missing. Never use outside knowledge.",
            "is_lnp_experiment is true only when this scoped event explicitly uses an LNP/liposomal nanoparticle.",
            "lnp_components are formulation materials only. Never put mRNA, siRNA, sgRNA, encoded proteins, or other cargo there.",
            "lnp_composition_raw_reported is only an explicit material list/ratio, not a general LNP description.",
            "Payload type is the molecular cargo class; payload name is e.g. HGF mRNA; encoded product is e.g. HGF.",
            "Represent every distinct biological cell/population once in cell_entities. Link recipient and therapeutic-target roles using its cell_entity_id. If roles are the same, reuse the same ID.",
            "A tissue, disease, tumor, gene, protein, or biological effect is not a cell.",
            "Do not infer in vivo merely from the word mice unless the scoped text explicitly describes administration or an in-vivo experiment.",
            "Create one lnp_outcome per distinct endpoint; never combine effects such as steatosis reversal and liver-function restoration.",
            "For non-LNP neighboring experiments, keep LNP-specific values missing and lnp_components empty.",
            "Use the exact supplied paper_id, experiment_id, and experiment_label.",
        ],
        "schema": ExperimentScopedExtractionV3.model_json_schema(),
    }
    response_path = paper_dir / f'{boundary["experiment_id"]}.response.json'
    if response_path.exists():
        response_data = json.loads(response_path.read_text())
    else:
        response = call_json(
            client, model,
            "You are a conservative scientific data extractor. Return one valid JSON object only.",
            payload, 14000,
        )
        response_data = envelope(response)
        response_path.write_text(
            json.dumps(response_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    result = ExperimentScopedExtractionV3.model_validate_json(response_data["content"] or "")
    if (result.paper_id, result.lnp_experiment_id, result.experiment_label) != (
        item["paper_id"], boundary["experiment_id"], boundary["experiment_label"]
    ):
        raise ValueError("model changed a frozen experiment identity")
    return result


def audit(result: ExperimentScopedExtractionV3, scoped: list[dict[str, str]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    lookup = {row["sentence_id"]: row["text"] for row in scoped}

    def walk(value: Any, path: str):
        if isinstance(value, SourceValueV3) and value.status == "reported":
            source = lookup.get(value.evidence_sentence_id or "", "")
            if not source:
                issues.append({"experiment_id": result.lnp_experiment_id, "field_name": path, "issue_type": "unknown_evidence_sentence"})
            elif normalized(value.evidence_quote) not in normalized(source):
                issues.append({"experiment_id": result.lnp_experiment_id, "field_name": path, "issue_type": "quote_not_in_cited_sentence"})
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif hasattr(value.__class__, "model_fields"):
            for name in value.__class__.model_fields:
                walk(getattr(value, name), f"{path}.{name}" if path else name)

    walk(result, "")
    for outcome in result.lnp_outcomes:
        name = normalized(outcome.endpoint_name_reported.value)
        if " and " in name or ";" in name:
            issues.append({"experiment_id": result.lnp_experiment_id, "field_name": "endpoint_name_reported", "issue_type": "possibly_merged_outcomes"})
    return issues


def run(paper_ids: set[str] | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    extraction_model = os.getenv("G1_V3_FIELD_MODEL", "deepseek-v4-flash")
    verifier_model = os.getenv("G1_V3_VERIFIER_MODEL", "glm-5.2")
    client = OpenAI(
        api_key=os.environ["SENSENOVA_API_KEY"],
        base_url=os.getenv("SENSENOVA_BASE_URL", "https://token.sensenova.cn/v1"),
        timeout=120.0, max_retries=1,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inputs = {item["paper_id"]: item for item in gold_inputs()}
    manifest: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "models": {"extractor": extraction_model, "verifier": verifier_model},
        "papers": [],
    }
    for boundary_path in sorted(BOUNDARIES.glob("GP-*.json")):
        boundary_map = json.loads(boundary_path.read_text())
        paper_id = boundary_map["paper_id"]
        if paper_ids and paper_id not in paper_ids:
            continue
        paper_dir = OUTPUT / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)
        if not boundary_map["experiments"]:
            manifest["papers"].append({"paper_id": paper_id, "status": "validated_expected_zero", "experiments": 0})
            continue
        item = inputs[paper_id]
        source_sentences = json.loads((SENTENCES / paper_id / "sentences.json").read_text())
        extractions, deterministic = [], []
        failures = []
        for boundary in boundary_map["experiments"]:
            scoped = [row for row in source_sentences if row["sentence_id"] in boundary["evidence_sentence_ids"]]
            try:
                validated_path = paper_dir / f'{boundary["experiment_id"]}.validated.json'
                if validated_path.exists():
                    result = ExperimentScopedExtractionV3.model_validate_json(validated_path.read_text())
                else:
                    result = extract_one(client, extraction_model, item, boundary, source_sentences, paper_dir)
                extractions.append(result)
                deterministic.extend(audit(result, scoped))
                validated_path.write_text(
                    result.model_dump_json(indent=2) + "\n", encoding="utf-8"
                )
            except Exception as error:
                failures.append({"experiment_id": boundary["experiment_id"], "error": str(error)})
        (paper_dir / "deterministic_audit.json").write_text(
            json.dumps(deterministic, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        verification = None
        verifier_failure = None
        verifier_path = paper_dir / "verification.validated.json"
        if not failures and verifier_path.exists():
            verification = PaperVerificationV3.model_validate_json(verifier_path.read_text())
        elif not failures:
            verifier_payload = {
                "paper_id": paper_id,
                "frozen_experiments_and_approved_sentences": [
                    {
                        "boundary": boundary,
                        "sentences": [row for row in source_sentences if row["sentence_id"] in boundary["evidence_sentence_ids"]],
                    }
                    for boundary in boundary_map["experiments"]
                ],
                "first_pass_extractions": [row.model_dump(mode="json") for row in extractions],
                "tasks": [
                    "Read every approved sentence again independently.",
                    "Flag every omitted explicit fact, unsupported value, wrong entity/link, merged outcome, and evidence mismatch.",
                    "Do not request facts that occur outside an experiment's approved sentences.",
                ],
                "schema": PaperVerificationV3.model_json_schema(),
            }
            try:
                response = call_json(
                    client, verifier_model,
                    "You are an independent second-pass scientific verifier. Do not trust the extraction. Return valid JSON only.",
                    verifier_payload, 14000,
                )
                verifier_data = envelope(response)
                (paper_dir / "verification.response.json").write_text(
                    json.dumps(verifier_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                verification = PaperVerificationV3.model_validate_json(verifier_data["content"] or "")
                verifier_path.write_text(verification.model_dump_json(indent=2) + "\n", encoding="utf-8")
            except Exception as error:
                verifier_failure = str(error)
        blocking = 0 if verification is None else sum(issue.severity == "blocking" for issue in verification.issues)
        status = "rejected" if failures or verifier_failure else ("manual_review_required" if deterministic or blocking else "accepted_after_two_reads")
        manifest["papers"].append({
            "paper_id": paper_id, "status": status, "experiments": len(extractions),
            "failures": failures, "deterministic_issues": len(deterministic),
            "verifier_issues": 0 if verification is None else len(verification.issues),
            "blocking_verifier_issues": blocking,
            "verifier_failure": verifier_failure,
        })
        (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    args = parser.parse_args()
    print(json.dumps(run(set(args.paper_id) if args.paper_id else None), indent=2))
