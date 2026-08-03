"""Short scientific instructions for compact extraction route v1."""

from __future__ import annotations

import hashlib


PROMPT_VERSION = "compact-prompt-1.4.0"

COMPACT_EXTRACTION_PROMPT = (
    "Extract directly reported LNP evidence from the supplied packet; use no "
    "outside knowledge. Return a reported value with valid supplied "
    "evidence IDs, or missing with a reason and no IDs. Set eligibility to eligible only "
    "for original LNP delivery of supported RNA or a validated tracer/barcode, an "
    "eligible liver cell, and linked formulation, experiment, and outcome. Report "
    "payload_role as therapeutic, reporter, biodistribution_tracer, or screening_barcode. "
    "Tracers are delivery evidence, not therapeutic RNA evidence. Put strains and "
    "engineered reporter models in experimental_model. Use disease_model "
    "only for actual disease. Failed criteria are ineligible; insufficient evidence is "
    "uncertain. Ineligible or uncertain papers must return empty extraction lists. "
    "Keep records separate. Do not infer hepatocytes from liver-level evidence. "
    "Do not mix facts from different experiments. "
    "Do not store payload as an LNP component. "
    "Do not convert a mechanism, hypothesis, or interpretation into a measured outcome. "
    "Candidates are navigation aids, not facts. A reported negative result is an outcome, "
    "not missing. Return only the required response."
)


def prompt_sha256() -> str:
    return hashlib.sha256(COMPACT_EXTRACTION_PROMPT.encode("utf-8")).hexdigest()
