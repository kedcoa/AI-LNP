"""Consolidate v2 first/second-read disagreements into a human packet."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .run_abstract_first import ROOT, gold_inputs


RUN = ROOT / "data" / "staging" / "extraction" / "g1_v2"
REVIEW = ROOT / "data" / "review" / "day5_g1_v2_human_review.jsonl"
PACKET = ROOT / "reports" / "extraction" / "day5_g1_v2_human_review.html"
SUMMARY = ROOT / "reports" / "extraction" / "day5_g1_v2_pre_review.json"


def find_field(bundle: dict[str, Any], entity_id: str, field_name: str) -> tuple[Any, str | None]:
    if field_name in {"lnp_formulations", "lnp_components", "lnp_experiments", "lnp_outcomes"}:
        collection = bundle[field_name]
        quotes = []
        for record in collection:
            for field in record.values():
                if isinstance(field, dict) and field.get("evidence_quote"):
                    quotes.append(field["evidence_quote"])
        unique_quotes = list(dict.fromkeys(quotes))
        return collection, " | ".join(unique_quotes) if unique_quotes else None
    for collection in ("lnp_formulations", "lnp_components", "lnp_experiments", "lnp_outcomes"):
        for record in bundle[collection]:
            if entity_id in {str(value) for key, value in record.items() if key.endswith("_id")}:
                if field_name not in record:
                    continue
                field = record.get(field_name)
                if isinstance(field, dict):
                    return field.get("value"), field.get("evidence_quote")
                return field, None
    return None, None


def find_entity(bundle: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    for collection in ("lnp_formulations", "lnp_components", "lnp_experiments", "lnp_outcomes"):
        for record in bundle[collection]:
            if entity_id in {str(value) for key, value in record.items() if key.endswith("_id")}:
                return record
    return None


def build() -> dict[str, Any]:
    sources = {item["paper_id"]: item for item in gold_inputs()}
    existing_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    if REVIEW.exists():
        for line in REVIEW.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            old = json.loads(line)
            old_key = (
                old.get("paper_id", ""),
                old.get("entity_id", ""),
                old.get("field_name", ""),
                old.get("preliminary_classification", ""),
            )
            existing_by_key[old_key] = old
    rows: list[dict[str, Any]] = []
    paper_status: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    extracted_fields = 0
    reported_fields = 0
    exact_quote_fields = 0

    for paper_id, source in sources.items():
        paper_dir = RUN / paper_id
        assembled = paper_dir / "extraction.assembled.json"
        validated = paper_dir / "extraction.validated.json"
        if not source["eligible_records_expected"]:
            paper_status.append({"paper_id": paper_id, "status": "validated_expected_zero"})
            continue
        if not assembled.exists():
            paper_status.append({"paper_id": paper_id, "status": "missing_or_invalid_extraction"})
            rows.append({"paper_id": paper_id, "entity_type": "paper", "field_name": "model_response", "value": None, "evidence_quotes": [], "preliminary_classification": "invalid_model_response", "verifier_explanation": "No assembled v2 extraction exists.", "human_decision": "pending"})
            continue
        bundle = json.loads(assembled.read_text(encoding="utf-8"))
        for collection in ("lnp_formulations", "lnp_components", "lnp_experiments", "lnp_outcomes"):
            for record in bundle[collection]:
                for field in record.values():
                    if isinstance(field, dict) and "status" in field:
                        extracted_fields += 1
                        if field["status"] == "reported":
                            reported_fields += 1
                            quote = field.get("evidence_quote") or ""
                            if quote and quote.lower() in source["abstract"].lower():
                                exact_quote_fields += 1

        deterministic_path = paper_dir / "deterministic_audit.json"
        for issue in json.loads(deterministic_path.read_text(encoding="utf-8")) if deterministic_path.exists() else []:
            key = (paper_id, issue["entity_id"], issue["field_name"], issue["issue_type"])
            if key in seen:
                continue
            seen.add(key)
            value, quote = find_field(bundle, issue["entity_id"], issue["field_name"])
            rows.append({"paper_id": paper_id, "entity_id": issue["entity_id"], "entity_type": "deterministic_audit", "field_name": issue["field_name"], "value": value, "entity_context": find_entity(bundle, issue["entity_id"]), "evidence_quotes": [quote] if quote else [], "preliminary_classification": issue["issue_type"], "verifier_explanation": "Deterministic source check failed.", "abstract": source["abstract"], "human_decision": "pending"})

        verification_path = paper_dir / "verification.validated.json"
        if not verification_path.exists():
            paper_status.append({"paper_id": paper_id, "status": "missing_second_read"})
            rows.append({"paper_id": paper_id, "entity_type": "paper", "field_name": "second_read", "value": None, "evidence_quotes": [], "preliminary_classification": "missing_second_read", "verifier_explanation": "No valid independent verification exists.", "human_decision": "pending"})
            continue
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        paper_status.append({"paper_id": paper_id, "status": "two_reads_complete", "completeness": verification["completeness_assessment"], "issues": len(verification["issues"])})
        for issue in verification["issues"]:
            key = (paper_id, issue["entity_id"], issue["field_name"], issue["issue_type"])
            if key in seen:
                continue
            seen.add(key)
            value, quote = find_field(bundle, issue["entity_id"], issue["field_name"])
            rows.append({"paper_id": paper_id, "entity_id": issue["entity_id"], "entity_type": "second_read", "field_name": issue["field_name"], "value": value, "entity_context": find_entity(bundle, issue["entity_id"]), "evidence_quotes": [quote] if quote else ([issue["supporting_or_corrective_quote"]] if issue.get("supporting_or_corrective_quote") else []), "preliminary_classification": issue["issue_type"], "severity": issue["severity"], "verifier_explanation": issue["explanation"], "abstract": source["abstract"], "human_decision": "pending"})

    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW.open("w", encoding="utf-8") as handle:
        for index, row in enumerate(rows, 1):
            key = (row.get("paper_id", ""), row.get("entity_id", ""), row.get("field_name", ""), row.get("preliminary_classification", ""))
            previous = existing_by_key.get(key, {})
            for saved_field in ("human_decision", "reviewer_reason", "reviewer", "reviewed_at"):
                if previous.get(saved_field):
                    row[saved_field] = previous[saved_field]
            handle.write(json.dumps({"review_id": f"G1V2-{index:04d}", **row}, ensure_ascii=False) + "\n")
    table = []
    for index, row in enumerate(rows, 1):
        table.append(f"<tr><td>G1V2-{index:04d}</td><td>{html.escape(row['paper_id'])}</td><td>{html.escape(row.get('field_name',''))}</td><td>{html.escape(str(row.get('value','')))}</td><td>{html.escape(row.get('verifier_explanation',''))}</td><td>{html.escape(' | '.join(row.get('evidence_quotes',[])))}</td></tr>")
    PACKET.write_text("<!doctype html><meta charset='utf-8'><title>G1 v2 review</title><style>body{font:14px sans-serif;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:6px;vertical-align:top}</style><h1>G1 v2 two-read disagreements</h1><table><tr><th>ID</th><th>Paper</th><th>Field</th><th>Value</th><th>Verifier finding</th><th>Evidence</th></tr>" + "".join(table) + "</table>", encoding="utf-8")
    summary = {
        "paper_status": paper_status,
        "review_rows": len(rows),
        "extracted_source_fields": extracted_fields,
        "reported_source_fields": reported_fields,
        "reported_fields_with_exact_abstract_quote": exact_quote_fields,
        "exact_quote_coverage": exact_quote_fields / reported_fields if reported_fields else None,
        "g1_status": "pending_human_verification",
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
