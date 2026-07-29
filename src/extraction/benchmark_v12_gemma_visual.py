"""Benchmark a local VLM with mandatory abstention.

Fixture expectations are used only after inference. They are never included in
the model prompt or Docling context.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from .v12_visual_contracts import (
    DoclingVisualObjectV12,
    VlmVisualDecisionV12,
)


ROOT = Path(__file__).resolve().parents[2]
DOCLING_ROOT = ROOT / "data/staging/extraction/v12_docling_visual"
FIXTURE = ROOT / "tests/fixtures/v12_visual/benchmark_cases.json"
BENCHMARK_OUTPUT_ROOT = ROOT / "data/staging/extraction/v12_vlm_benchmarks"
BENCHMARK_REPORT_ROOT = ROOT / "reports/extraction/v12_vlm_benchmarks"
OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
OLLAMA_SHOW = "http://127.0.0.1:11434/api/show"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"


def model_slug(model: str) -> str:
    """Return a filesystem-safe, stable directory name for an Ollama model."""

    slug = re.sub(r"[^a-z0-9._-]+", "-", model.lower()).strip("-")
    if not slug:
        raise ValueError("model must contain at least one filesystem-safe character")
    return slug


def _post(url: str, payload: dict[str, Any], timeout: float = 300.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(url: str, timeout: float = 60.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _query_terms(query: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "from", "this", "that", "after",
        "under", "rather", "than", "report", "extract", "determine",
    }
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9+/%.-]{3,}", query)
        if token.lower() not in stop
    }


ANCHOR_GROUPS: dict[str, tuple[str, ...]] = {
    "LSEC": ("lsec", "lsecs"),
    "macrophage": ("macrophage", "macrophages", "f4/80", "cd163"),
    "HSC": ("hsc", "hscs", "hepatic stellate", "desmin"),
    "hepatocyte": ("hepatocyte", "hepatocytes", "alb"),
    "ZsGreen": ("zsgreen",),
    "insertion frequency": ("insertion frequency",),
    "deletion frequency": ("deletion frequency",),
    "localization": (
        "localization",
        "localize",
        "localized",
        "colocalization",
        "co-localization",
        "co-staining",
        "costaining",
        "overlap",
    ),
    "Cas9/sgRNA": ("cas9", "sgrna", "sg/rna"),
    "total": ("total",),
}


def required_query_anchors(query: str) -> dict[str, tuple[str, ...]]:
    lowered = query.lower()
    return {
        label: variants
        for label, variants in ANCHOR_GROUPS.items()
        if any(variant in lowered for variant in variants)
    }


def compact_docling_context(
    parsed: DoclingVisualObjectV12, query: str, max_text_items: int = 80
) -> dict[str, Any]:
    terms = _query_terms(query)
    anchor_terms = {
        "zsgreen", "cd163", "desmin", "f4/80", "sox9", "alb",
        "macrophage", "hsc", "lsec", "insertion", "frequency", "total",
    }
    ranked: list[tuple[int, int, str]] = []
    for index, item in enumerate(parsed.text_items):
        lowered = item.text.lower()
        score = sum(term in lowered for term in terms)
        score += 2 * sum(term in lowered for term in anchor_terms)
        if score or item.label == "caption":
            ranked.append((score, index, item.text))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    text_items = [text for _, _, text in ranked[:max_text_items]]
    return {
        "object_id": parsed.object_id,
        "paper_id": parsed.paper_id,
        "source_file": parsed.source_file,
        "original_page": parsed.original_page,
        "figure_or_table": parsed.figure_or_table,
        "caption": parsed.caption,
        "docling_text": text_items,
        "docling_tables": [
            {"table_index": table.table_index, "grid": table.grid}
            for table in parsed.tables
        ],
        "warning": (
            "Docling OCR can be wrong. Use the image as primary evidence and "
            "Docling only as a layout/transcription aid."
        ),
    }


def build_prompt(
    query_id: str, query: str, parsed: DoclingVisualObjectV12
) -> str:
    schema = VlmVisualDecisionV12.model_json_schema()
    payload = {
        "task": "Extract one or more atomic outcomes from one scientific visual object.",
        "query_id": query_id,
        "query": query,
        "required_query_anchors": {
            label: list(variants)
            for label, variants in required_query_anchors(query).items()
        },
        "source_context": compact_docling_context(parsed, query),
        "mandatory_rules": [
            "First verify every required_query_anchor is visibly supported. If any one is absent, abstain; do not substitute a different visible outcome.",
            "Use only facts visibly supported by the supplied image, its caption, or the supplied Docling structure.",
            "If the requested subject, endpoint, relationship, or context is not visible, return status=abstain and claims=[].",
            "For abstention, always set abstention_reason to one allowed schema value and list missing_requirements.",
            "For extraction, copy every required query anchor into each claim's visible_support or abstain.",
            "If a required anchor is visible in a title or caption rather than the panel or intersecting table cell, add a separate visible_support item quoting that title or caption.",
            "Never use related-paper knowledge or infer a result from the query wording.",
            "A numeric claim is exact_numeric only when its value is visibly printed; never estimate bars, points, colors, or microscopy intensity.",
            "For a qualitative claim, use direction/localization words only: do not put measured numbers, percentages, approximate values, or estimated bar heights in value or visible_support; digits inside marker names such as F4/80 are allowed.",
            "Every claim requires value: copy the exact printed number for exact_numeric, or state the short observed relationship for qualitative.",
            "For a table claim, visible_support must name the row header, column header, and intersecting cell.",
            "For a qualitative image claim, visible_support must name the visible marker/channel/group labels and the observed direction or localization.",
            "Do not convert a caption describing what was measured into a positive result unless the result is visible in the object.",
            "Return the supplied object_id and query_id exactly.",
            "Return JSON only and follow the schema.",
        ],
        "schema": schema,
    }
    # Qwen3-family checkpoints support this soft switch; other VLMs treat it
    # as an ordinary concise-response instruction.
    return json.dumps(payload, ensure_ascii=False) + "\n/no_think"


def call_gemma(
    model: str,
    case: dict[str, Any],
    parsed: DoclingVisualObjectV12,
    *,
    seed: int,
    thinking: bool,
) -> tuple[VlmVisualDecisionV12 | None, dict[str, Any], str | None]:
    crop = ROOT / case.get("image_path", parsed.source_crop)
    image = base64.b64encode(crop.read_bytes()).decode("ascii")
    started = time.monotonic()
    raw = _post(OLLAMA_CHAT, {
        "model": model,
        "messages": [{
            "role": "user",
            "content": build_prompt(case["query_id"], case["query"], parsed),
            "images": [image],
        }],
        "stream": False,
        "think": thinking,
        "format": VlmVisualDecisionV12.model_json_schema(),
        "options": {
            "temperature": 0,
            "seed": seed,
            "num_ctx": 8192,
            "num_predict": 1200,
        },
        "keep_alive": "10m",
    })
    elapsed = time.monotonic() - started
    content = raw["message"]["content"]
    metadata = {
        "model": raw.get("model"),
        "created_at": raw.get("created_at"),
        "done_reason": raw.get("done_reason"),
        "total_duration_ns": raw.get("total_duration"),
        "load_duration_ns": raw.get("load_duration"),
        "prompt_eval_count": raw.get("prompt_eval_count"),
        "eval_count": raw.get("eval_count"),
        "elapsed_seconds": elapsed,
        "response_content": content,
        "response_message": raw.get("message"),
        "image_path": str(crop.relative_to(ROOT)),
    }
    try:
        decision = VlmVisualDecisionV12.model_validate_json(content)
    except Exception as exc:
        return None, metadata, f"{type(exc).__name__}: {exc}"
    return decision, metadata, None


def audit_decision(
    case: dict[str, Any],
    parsed: DoclingVisualObjectV12,
    decision: VlmVisualDecisionV12,
) -> list[str]:
    issues: list[str] = []
    if decision.object_id != parsed.object_id:
        issues.append("object_id mismatch")
    if decision.query_id != case["query_id"]:
        issues.append("query_id mismatch")
    if decision.status != case["expected_status"]:
        issues.append(
            f"expected {case['expected_status']} but model returned {decision.status}"
        )
    serialized = decision.model_dump_json().lower()
    for term in case["required_claim_terms"]:
        if term.lower() not in serialized:
            issues.append(f"required term missing: {term}")
    for term in case["forbidden_claim_terms"]:
        if term.lower() in serialized:
            issues.append(f"forbidden term present: {term}")
    claim_values = " | ".join(claim.value for claim in decision.claims)
    for pattern in case.get("required_value_patterns", []):
        if not re.search(pattern, claim_values, re.I):
            issues.append(f"required claim-value relationship missing: {pattern}")
    anchors = required_query_anchors(case["query"])
    claim_text = serialized
    for label, variants in anchors.items():
        if decision.status == "extract" and not any(
            variant in claim_text for variant in variants
        ):
            issues.append(f"claim omits required query anchor: {label}")
    docling_evidence = json.dumps(
        compact_docling_context(parsed, case["query"]),
        ensure_ascii=False,
    ).lower()
    for claim in decision.claims:
        support = " ".join(claim.visible_support).lower()
        for label, variants in anchors.items():
            if not any(variant in support for variant in variants):
                issues.append(
                    f"{claim.claim_id}: visible_support omits query anchor: {label}"
                )
        if claim.result_type == "exact_numeric":
            value = claim.value.lower().replace(" ", "")
            evidence = docling_evidence.replace(" ", "")
            if value not in evidence:
                issues.append(
                    f"{claim.claim_id}: exact value absent from Docling evidence"
                )
            if value not in support.replace(" ", ""):
                issues.append(
                    f"{claim.claim_id}: exact value absent from visible_support"
                )
            table_claim = "docling_table_cell" in claim.evidence_kinds
            if table_claim and not _table_intersection_supports(parsed, claim):
                issues.append(
                    f"{claim.claim_id}: value does not match the claimed table intersection"
                )
        if claim.result_type == "qualitative":
            if re.search(r"\b(?:approximately|about|~)\s*\d", support, re.I):
                issues.append(f"{claim.claim_id}: qualitative claim estimates a number")
    return issues


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9±.+>%/]", "", value.lower())


def _table_intersection_supports(
    parsed: DoclingVisualObjectV12, claim: Any
) -> bool:
    target = _normalized(claim.value)
    subject = claim.subject.lower()
    endpoint = " ".join(
        part for part in (claim.predicate, claim.endpoint or "") if part
    ).lower()
    support = " ".join(claim.visible_support).lower()
    for table in parsed.tables:
        row_candidates = {
            cell.row
            for cell in table.cells
            if cell.is_row_header
            and (
                cell.text.lower() in subject
                or subject in cell.text.lower()
                or cell.text.lower() in support
            )
        }
        column_candidates = {
            cell.column
            for cell in table.cells
            if cell.is_column_header
            and (
                cell.text.lower() in endpoint
                or endpoint in cell.text.lower()
                or cell.text.lower() in support
            )
        }
        for row in row_candidates:
            for column in column_candidates:
                if row < len(table.grid) and column < len(table.grid[row]):
                    if target == _normalized(table.grid[row][column]):
                        return True
    return False


def run(
    model: str,
    repeats: int,
    seed: int,
    query_ids: set[str] | None = None,
    *,
    thinking: bool = False,
    output_root: Path | None = None,
    report_root: Path | None = None,
) -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = [
        case for case in fixture["cases"]
        if query_ids is None or case["query_id"] in query_ids
    ]
    if query_ids and {case["query_id"] for case in cases} != query_ids:
        missing = sorted(query_ids - {case["query_id"] for case in cases})
        raise ValueError(f"query ids not in fixture: {missing}")
    model_info = _post(OLLAMA_SHOW, {"model": model}, timeout=60.0)
    tags = _get(OLLAMA_TAGS)
    model_digest = next(
        (
            row.get("digest")
            for row in tags.get("models", [])
            if row.get("name") == model or row.get("model") == model
        ),
        None,
    )
    slug = f"{model_slug(model)}-thinking-{'on' if thinking else 'off'}"
    output_root = output_root or BENCHMARK_OUTPUT_ROOT / slug
    report_root = report_root or BENCHMARK_REPORT_ROOT / slug
    output_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for case in cases:
        parsed = DoclingVisualObjectV12.model_validate_json(
            (DOCLING_ROOT / case["object_id"] / "docling_object.json").read_text()
        )
        for repeat in range(1, repeats + 1):
            decision, raw, validation_error = call_gemma(
                model, case, parsed, seed=seed, thinking=thinking
            )
            issues = (
                [f"response validation failed: {validation_error}"]
                if decision is None
                else audit_decision(case, parsed, decision)
            )
            case_dir = output_root / case["query_id"]
            case_dir.mkdir(parents=True, exist_ok=True)
            stem = f"repeat-{repeat:02d}"
            if decision is not None:
                (case_dir / f"{stem}.decision.json").write_text(
                    decision.model_dump_json(indent=2) + "\n"
                )
            else:
                (case_dir / f"{stem}.invalid.txt").write_text(
                    (validation_error or "unknown validation error") + "\n"
                )
            (case_dir / f"{stem}.response.json").write_text(
                json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
            )
            runs.append({
                "query_id": case["query_id"],
                "gold_outcome_id": case["gold_outcome_id"],
                "object_id": case["object_id"],
                "image_path": raw["image_path"],
                "repeat": repeat,
                "expected_status": case["expected_status"],
                "actual_status": decision.status if decision else "invalid",
                "claims": len(decision.claims) if decision else 0,
                "audit_issues": issues,
                "passed": not issues,
                "prompt_tokens": raw.get("prompt_eval_count"),
                "output_tokens": raw.get("eval_count"),
                "elapsed_seconds": raw["elapsed_seconds"],
            })
    positives = [row for row in runs if row["expected_status"] == "extract"]
    abstentions = [row for row in runs if row["expected_status"] == "abstain"]
    required_query_ids = {case["query_id"] for case in fixture["cases"]}
    covered_query_ids = {row["query_id"] for row in runs}
    full_fixture_coverage = covered_query_ids == required_query_ids
    minimum_repeats_met = repeats >= 3
    every_run_passed = bool(runs) and all(row["passed"] for row in runs)
    evaluation = {
        "contract_version": "1.0.0",
        "model": model,
        "model_slug": slug,
        "thinking": thinking,
        "model_digest": model_digest,
        "model_capabilities": model_info.get("capabilities", []),
        "repeats": repeats,
        "seed": seed,
        "paid_api_requests": 0,
        "local_only": True,
        "summary": {
            "runs": len(runs),
            "passed": sum(row["passed"] for row in runs),
            "positive_passed": sum(row["passed"] for row in positives),
            "positive_total": len(positives),
            "abstention_passed": sum(row["passed"] for row in abstentions),
            "abstention_total": len(abstentions),
            "total_prompt_tokens": sum(row["prompt_tokens"] or 0 for row in runs),
            "total_output_tokens": sum(row["output_tokens"] or 0 for row in runs),
            "total_elapsed_seconds": sum(row["elapsed_seconds"] for row in runs),
        },
        "integration_gate_requirements": {
            "all_fixture_query_ids": sorted(required_query_ids),
            "full_fixture_coverage": full_fixture_coverage,
            "minimum_repeats": 3,
            "minimum_repeats_met": minimum_repeats_met,
            "every_run_passed": every_run_passed,
        },
        "runs": runs,
    }
    evaluation["screening_passed"] = every_run_passed
    evaluation["integration_gate_passed"] = (
        full_fixture_coverage
        and minimum_repeats_met
        and every_run_passed
    )
    evaluation["integration_allowed"] = evaluation["integration_gate_passed"]
    evaluation["decision"] = (
        "eligible_for_human_approval"
        if evaluation["integration_gate_passed"]
        else (
            "screening_passed_run_full_three_repeat_gate"
            if evaluation["screening_passed"]
            else "reject_model_outputs"
        )
    )
    (report_root / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False) + "\n"
    )
    return evaluation


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--query-id", action="append")
    parser.add_argument("--thinking", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(
        args.model,
        args.repeats,
        args.seed,
        set(args.query_id) if args.query_id else None,
        thinking=args.thinking,
    ), indent=2))
