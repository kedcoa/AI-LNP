"""Run v2 abstract extraction, deterministic audit, and an independent second read."""

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

from .contracts_v2 import (
    AbstractExtractionV2,
    ComponentResponseV2,
    ExperimentResponseV2,
    FormulationResponseV2,
    OutcomeResponseV2,
    SecondReadVerificationV2,
    SourceValue,
)
from .run_abstract_first import ROOT, gold_inputs


OUTPUT = ROOT / "data" / "staging" / "extraction" / "g1_v2"


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def deterministic_audit(bundle: AbstractExtractionV2, abstract: str) -> list[dict[str, str]]:
    """Re-read every inline quote and enforce cross-field scientific boundaries."""
    issues: list[dict[str, str]] = []
    for collection_name in ("lnp_formulations", "lnp_components", "lnp_experiments", "lnp_outcomes"):
        for record in getattr(bundle, collection_name):
            record_id = next((str(value) for name, value in record if name.endswith("_id")), collection_name)
            for field_name in record.__class__.model_fields:
                field = getattr(record, field_name)
                if isinstance(field, SourceValue) and field.status == "reported":
                    if normalize(field.evidence_quote) not in normalize(abstract):
                        issues.append({"entity_id": record_id, "field_name": field_name, "issue_type": "evidence_quote_not_in_abstract"})
    for outcome in bundle.lnp_outcomes:
        name = normalize(outcome.endpoint_name_reported.value)
        if " and " in name or ";" in name:
            issues.append({"entity_id": outcome.lnp_outcome_id, "field_name": "endpoint_name_reported", "issue_type": "possibly_merged_outcomes"})
    return issues


def response_envelope(response: Any) -> dict[str, Any]:
    choice = response.choices[0]
    return {
        "model": response.model,
        "finish_reason": choice.finish_reason,
        "content": choice.message.content,
        "usage": response.usage.model_dump() if response.usage else None,
    }


def call_json(client: OpenAI, model: str, system: str, payload: dict[str, Any], max_tokens: int = 7000):
    return client.chat.completions.create(
        model=model,
        temperature=0,
        max_completion_tokens=max_tokens,
        timeout=120.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )


def split_extract(client: OpenAI, model: str, item: dict[str, Any], paper_dir: Path) -> AbstractExtractionV2:
    """Extract sequential entity slices to avoid provider length truncation."""
    shared_rules = [
        "Read only the supplied title and abstract.",
        "Use exact verbatim evidence quotes for reported values; otherwise mark missing.",
        "Make no outside-knowledge inference.",
        "For every SourceValue: status reported requires non-null value and quote; status missing requires null value, null quote, and a missing reason.",
    ]
    requests: list[tuple[str, Any, dict[str, Any]]] = [
        (
            "formulations",
            FormulationResponseV2,
            {
                "rules": shared_rules + [
                    "Always create a formulation record when an identifiable LNP is explicitly mentioned, even if it has only a generic reported name and missing composition.",
                    "lnp_composition_raw_reported contains only LNP material identities and ratios, never cargo or a general LNP description."
                ],
            },
        )
    ]
    results: dict[str, Any] = {}
    for entity_name, response_model, extra in requests:
        payload = {
            "paper_id": item["paper_id"],
            "title": item["title"],
            "abstract": item["abstract"],
            **extra,
            "schema": response_model.model_json_schema(),
        }
        response = call_json(client, model, f"Extract only LNP {entity_name}. Return valid JSON only.", payload, 3500)
        envelope = response_envelope(response)
        (paper_dir / f"{entity_name}.response.json").write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        parsed = response_model.model_validate_json(envelope["content"] or "")
        results[entity_name] = getattr(parsed, f"lnp_{entity_name}")

    formulation_ids = [row.lnp_formulation_id for row in results["formulations"]]
    followups = [
        (
            "components",
            ComponentResponseV2,
            "lnp_components",
            shared_rules + ["Extract formulation materials only. RNA, mRNA, siRNA, sgRNA, and encoded products are never lnp_components. lnp_formulation_id must be one exact allowed string, never a SourceValue object."],
            {"allowed_lnp_formulation_ids": formulation_ids},
        ),
        (
            "experiments",
            ExperimentResponseV2,
            "lnp_experiments",
            shared_rules + ["Separate recipient cell, therapeutic target cell, tissue, disease, payload type, payload name, encoded product, and molecular target. lnp_formulation_id must be one exact allowed string, never a SourceValue object."],
            {"allowed_lnp_formulation_ids": formulation_ids},
        ),
    ]
    for entity_name, response_model, result_key, rules, context in followups:
        payload = {"paper_id": item["paper_id"], "title": item["title"], "abstract": item["abstract"], "rules": rules, **context, "schema": response_model.model_json_schema()}
        response = call_json(client, model, f"Extract only LNP {entity_name}. Return valid JSON only.", payload, 10000)
        envelope = response_envelope(response)
        (paper_dir / f"{entity_name}.response.json").write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        parsed = response_model.model_validate_json(envelope["content"] or "")
        results[entity_name] = getattr(parsed, result_key)

    experiment_ids = [row.lnp_experiment_id for row in results["experiments"]]
    outcome_payload = {
        "paper_id": item["paper_id"],
        "title": item["title"],
        "abstract": item["abstract"],
        "rules": shared_rules + ["Create one outcome record per distinct, explicitly reported endpoint. Never combine endpoints with 'and'. Keep uptake separate from functional expression. Do not create redundant outcomes for each wording or disease model; use at most six outcomes from one abstract."],
        "allowed_lnp_experiment_ids": experiment_ids,
        "schema": OutcomeResponseV2.model_json_schema(),
    }
    response = call_json(client, model, "Extract only distinct nonredundant LNP outcomes. Return valid JSON only.", outcome_payload, 16000)
    envelope = response_envelope(response)
    (paper_dir / "outcomes.response.json").write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    parsed_outcomes = OutcomeResponseV2.model_validate_json(envelope["content"] or "")
    results["outcomes"] = parsed_outcomes.lnp_outcomes
    return AbstractExtractionV2(
        contract_version="2.0.0",
        paper_id=item["paper_id"],
        lnp_formulations=results["formulations"],
        lnp_components=results["components"],
        lnp_experiments=results["experiments"],
        lnp_outcomes=results["outcomes"],
    )


def run(paper_ids: set[str] | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    model = os.getenv("G1_V2_MODEL", "deepseek-v4-flash")
    client = OpenAI(
        api_key=os.environ["SENSENOVA_API_KEY"],
        base_url=os.getenv("SENSENOVA_BASE_URL", "https://token.sensenova.cn/v1"),
        timeout=120.0,
        max_retries=1,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"run_at": datetime.now(timezone.utc).isoformat(), "model": model, "papers": []}
    for item in gold_inputs():
        if paper_ids and item["paper_id"] not in paper_ids:
            continue
        paper_id = item["paper_id"]
        paper_dir = OUTPUT / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)
        if not item["eligible_records_expected"]:
            empty = AbstractExtractionV2(contract_version="2.0.0", paper_id=paper_id, lnp_formulations=[], lnp_components=[], lnp_experiments=[], lnp_outcomes=[])
            (paper_dir / "extraction.validated.json").write_text(empty.model_dump_json(indent=2) + "\n", encoding="utf-8")
            manifest["papers"].append({"paper_id": paper_id, "status": "validated_expected_zero"})
            continue
        try:
            bundle = split_extract(client, model, item, paper_dir)
            (paper_dir / "extraction.assembled.json").write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
            deterministic = deterministic_audit(bundle, item["abstract"])
            (paper_dir / "deterministic_audit.json").write_text(json.dumps(deterministic, indent=2) + "\n", encoding="utf-8")

            verifier_payload = {
                "paper_id": paper_id,
                "title": item["title"],
                "abstract": item["abstract"],
                "first_pass_extraction": bundle.model_dump(mode="json"),
                "verification_tasks": [
                    "Read the entire abstract again from the beginning.",
                    "Find explicit facts the first pass omitted.",
                    "Flag payloads stored as components and descriptions stored as composition.",
                    "Flag recipient/target/tissue/disease conflation.",
                    "Flag merged experiments or outcomes.",
                    "Flag values whose attached quote does not directly support the field.",
                ],
                "schema": SecondReadVerificationV2.model_json_schema(),
            }
            verifier = call_json(client, model, "You are an independent scientific extraction verifier. Re-read the source; do not trust the first pass. Return valid JSON only.", verifier_payload, 8000)
            verifier_env = response_envelope(verifier)
            (paper_dir / "verification.response.json").write_text(json.dumps(verifier_env, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            verification = SecondReadVerificationV2.model_validate_json(verifier_env["content"] or "")
            (paper_dir / "verification.validated.json").write_text(verification.model_dump_json(indent=2) + "\n", encoding="utf-8")
            if deterministic or any(issue.severity == "blocking" for issue in verification.issues):
                status = "manual_review_required"
            else:
                status = "accepted_after_two_reads"
                (paper_dir / "extraction.validated.json").write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
            manifest["papers"].append({"paper_id": paper_id, "status": status, "deterministic_issues": len(deterministic), "verifier_issues": len(verification.issues)})
        except Exception as error:
            manifest["papers"].append({"paper_id": paper_id, "status": "rejected", "error": str(error)})
    (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    args = parser.parse_args()
    print(json.dumps(run(set(args.paper_id) if args.paper_id else None), indent=2))
