"""Build Day 8 afternoon metrics and the remaining human-review queue."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .merge_day8_evidence import OUTPUT
from .pdf_multimodal_contracts import EvidenceVerification, MergedEvidenceRecord
from .run_abstract_first import ROOT


def build() -> dict:
    corrected_merged = OUTPUT / "merged_evidence.human_corrected.json"
    merged_path = (
        corrected_merged if corrected_merged.exists()
        else OUTPUT / "merged_evidence.json"
    )
    records = {
        row.merged_record_id: row
        for row in (
            MergedEvidenceRecord.model_validate(item)
            for item in json.loads(merged_path.read_text())
        )
    }
    adjudication_path = OUTPUT / "human_adjudications.json"
    adjudications = (
        json.loads(adjudication_path.read_text())
        if adjudication_path.exists() else []
    )
    adjudicated_ids = {row["record_id"] for row in adjudications}
    verification_paths = [
        path for path in sorted((OUTPUT / "verification").glob("*.validated.json"))
        if ".pre_caption_fix." not in path.name
    ]
    verifications = [
        EvidenceVerification.model_validate_json(path.read_text())
        for path in verification_paths
    ]
    response_paths = [
        path for path in sorted((OUTPUT / "verification").glob("*.response.json"))
        if ".pre_caption_fix." not in path.name
    ]
    usage = [
        json.loads(path.read_text()).get("usage") or {}
        for path in response_paths
    ]
    input_tokens = sum(row.get("input_tokens", 0) for row in usage)
    output_tokens = sum(row.get("output_tokens", 0) for row in usage)
    review_rows = [
        row for row in verifications
        if row.disposition == "human_review"
        and row.merged_record_id not in adjudicated_ids
    ]

    cases = {
        "GO-006": {
            "role": "structured-table regression",
            "result": "targeted PDF matched; retained only when the exact table cell was visible",
        },
        "GO-017": {
            "role": "direct measurement versus inferred mechanism rejection",
            "result": "unsupported biological interpretation rejected (D8M-0108)",
        },
        "GO-018": {
            "role": "image/panel regression",
            "result": (
                "object vision recovered panel/channel/quadrant labels; source-type exact "
                "gold match remains pending human adjudication"
            ),
        },
    }
    metrics = {
        "merged_records": len(records),
        "verified_records": len(verifications),
        "dispositions": {
            value: sum(row.disposition == value for row in verifications)
            for value in ("retain", "correct", "reject", "human_review")
        },
        "human_review_rate": len(review_rows) / len(verifications) if verifications else 0,
        "human_adjudicated": len(adjudicated_ids),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost": None,
        "estimated_cost_note": "Not computed: no stable model price was encoded in the run.",
        "frozen_regressions": cases,
        "curation_policy": (
            "Only retain dispositions may enter curation; reject and human_review "
            "records remain blocked."
        ),
    }
    (OUTPUT / "day8_afternoon_metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n"
    )

    cards = []
    for verification in review_rows:
        record = records[verification.merged_record_id]
        sources = []
        for source in record.sources:
            crop = ""
            if source.crop_path:
                crop_path = ROOT / source.crop_path
                crop = (
                    f"<p><a href='{html.escape(str(crop_path))}'>Open original crop</a></p>"
                    f"<img src='{html.escape(str(crop_path))}' alt='source crop'>"
                )
            sources.append(f"""
<div class="source">
  <p><strong>{html.escape(source.source_id)}</strong> — {html.escape(source.file_name)},
  page {source.page}, {html.escape(source.figure_or_table or '')}
  {html.escape(source.panel_or_cell or '')}</p>
  <p><strong>Visible support:</strong> {html.escape(source.evidence_quote)}</p>
  {crop}
</div>""")
        cards.append(f"""
<section>
  <h2>{html.escape(record.merged_record_id)} — {html.escape(record.endpoint)}</h2>
  <p><strong>Population:</strong> {html.escape(record.population)}</p>
  <p><strong>Intervention:</strong> {html.escape(record.intervention)}</p>
  <p><strong>Proposed value:</strong> {html.escape(record.canonical_value)}
  {html.escape(record.canonical_unit or '')}</p>
  <p class="reason"><strong>Why you must check it:</strong>
  {html.escape(verification.reason)}</p>
  {''.join(sources)}
</section>""")

    output = OUTPUT / "human_review.html"
    output.write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Day 8 afternoon human review</title>
<style>
body{{font:15px system-ui;max-width:1200px;margin:24px auto;padding:0 18px;background:#f4f6f7;color:#172126}}
section{{background:white;border:1px solid #d5dde0;border-radius:10px;padding:18px;margin:18px 0}}
.reason{{background:#fff4ce;border-left:4px solid #b7791f;padding:10px}}
.source{{border-top:1px solid #dde3e6;margin-top:12px;padding-top:10px}}
img{{max-width:100%;max-height:720px;border:1px solid #aab7bd}}
</style></head><body>
<h1>Day 8 afternoon — human verification queue</h1>
<p>Open each original source and decide whether the proposed record should be retained,
corrected, or rejected. All other records have completed independent verification.</p>
<p><strong>{len(review_rows)} records require you.</strong> The pipeline retained
{metrics['dispositions']['retain']} and blocked {metrics['dispositions']['reject']} automatically.</p>
{''.join(cards)}
</body></html>""", encoding="utf-8")
    return {"review_path": str(output), **metrics}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
