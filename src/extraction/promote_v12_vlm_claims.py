"""Promote only fully gated VLM claims into a gold-blind evidence registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .benchmark_v12_gemma_visual import model_slug
from .v12_visual_contracts import VlmVisualDecisionV12


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_OUTPUT_ROOT = ROOT / "data/staging/extraction/v12_vlm_benchmarks"
BENCHMARK_REPORT_ROOT = ROOT / "reports/extraction/v12_vlm_benchmarks"
REGISTRY_ROOT = ROOT / "data/staging/extraction/v12_accepted_visual_claims"


def _normalized(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _claim_key(claim: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        _normalized(claim.get(field))
        for field in (
            "subject",
            "predicate",
            "endpoint",
            "result_type",
            "value",
            "unit",
            "intervention_context",
            "panel_or_cell",
        )
    )


def _display_path(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def promote(
    model: str,
    *,
    thinking: bool = False,
    report_path: Path | None = None,
    benchmark_output: Path | None = None,
    registry_root: Path = REGISTRY_ROOT,
) -> dict[str, Any]:
    slug = f"{model_slug(model)}-thinking-{'on' if thinking else 'off'}"
    report_path = report_path or BENCHMARK_REPORT_ROOT / slug / "evaluation.json"
    benchmark_output = benchmark_output or BENCHMARK_OUTPUT_ROOT / slug
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("model") != model:
        raise ValueError(
            f"benchmark model mismatch: expected {model}, got {report.get('model')}"
        )
    if not report.get("integration_gate_passed"):
        raise ValueError("VLM benchmark gate failed; no claim may be promoted")
    requirements = report.get("integration_gate_requirements", {})
    if (
        not requirements.get("full_fixture_coverage")
        or not requirements.get("minimum_repeats_met")
        or not requirements.get("every_run_passed")
    ):
        raise ValueError(
            "VLM benchmark report lacks the complete three-repeat gate"
        )

    accepted: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for run in report.get("runs", []):
        if not run.get("passed") or run.get("expected_status") != "extract":
            continue
        decision_path = (
            benchmark_output
            / run["query_id"]
            / f"repeat-{int(run['repeat']):02d}.decision.json"
        )
        decision = VlmVisualDecisionV12.model_validate_json(
            decision_path.read_text(encoding="utf-8")
        )
        for claim in decision.claims:
            # Numeric table intersections are promoted by the deterministic
            # Docling route, never by a generative visual reading.
            if claim.result_type == "exact_numeric":
                continue
            claim_payload = claim.model_dump(mode="json")
            semantic_payload = {
                key: value
                for key, value in claim_payload.items()
                if key != "claim_id"
            }
            semantic_digest = hashlib.sha256(json.dumps(
                {
                    "model_digest": report.get("model_digest"),
                    "object_id": decision.object_id,
                    "claim": semantic_payload,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()[:16]
            claim_payload["claim_id"] = f"VCL-{semantic_digest}"
            key = _claim_key(claim_payload)
            if key in seen:
                continue
            seen.add(key)
            digest_payload = json.dumps(
                {
                    "model_digest": report.get("model_digest"),
                    "object_id": decision.object_id,
                    "claim": claim_payload,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            evidence_id = "VLM-" + hashlib.sha256(
                digest_payload.encode("utf-8")
            ).hexdigest()[:16]
            image_path = Path(run["image_path"])
            if not image_path.is_absolute():
                image_path = ROOT / image_path
            if not image_path.is_file():
                raise FileNotFoundError(image_path)
            accepted.append({
                "evidence_id": evidence_id,
                "object_id": decision.object_id,
                "image_path": run["image_path"],
                "image_sha256": hashlib.sha256(
                    image_path.read_bytes()
                ).hexdigest(),
                "claim": claim_payload,
                "support_text": " | ".join(claim.visible_support),
            })

    registry = {
        "registry_version": "accepted-visual-claims-1.2.0",
        "model": model,
        "model_digest": report.get("model_digest"),
        "thinking": report.get("thinking"),
        "benchmark_report": _display_path(report_path),
        "benchmark_gate_passed": True,
        "claims": accepted,
        "gold_identifiers_in_payload": False,
    }
    serialized_claims = json.dumps(
        registry["claims"], ensure_ascii=False
    )
    if re.search(r"\bG[OX]-\d+", serialized_claims):
        raise ValueError(
            "accepted visual registry contains a gold identifier"
        )
    registry_root.mkdir(parents=True, exist_ok=True)
    output = registry_root / f"{slug}.json"
    output.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return registry


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    print(json.dumps(promote(args.model), ensure_ascii=False, indent=2))
