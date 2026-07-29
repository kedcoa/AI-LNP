"""Short scientific instructions for compact extraction route v1."""

from __future__ import annotations

import hashlib


PROMPT_VERSION = "compact-prompt-1.2.0"

COMPACT_EXTRACTION_PROMPT = (
    "Extract only directly reported LNP evidence from the supplied packet. "
    "Use no outside knowledge. For each scientific field, return a reported value "
    "with valid supplied evidence IDs, or missing with a reason and no evidence IDs. "
    "Set eligibility to eligible only for original experimental LNP delivery of "
    "supported RNA involving an eligible liver cell and a linked formulation, "
    "experiment, and outcome. Failed criteria are ineligible; insufficient evidence "
    "is uncertain. Ineligible or uncertain papers must return empty extraction lists. "
    "Keep record types and links separate. Do not infer hepatocytes from liver-level evidence. "
    "Do not mix facts from different experiments. "
    "Do not store payload as an LNP component. "
    "Do not convert a mechanism, hypothesis, or interpretation into a measured outcome. "
    "Treat recall-support candidates as navigation aids, not facts: verify cited "
    "evidence, preserve experiment boundaries, keep distinct relationships separate, "
    "and deduplicate. A reported negative result is an outcome, not missing. "
    "List ambiguities. Return only the required structured response."
)


def prompt_sha256() -> str:
    return hashlib.sha256(COMPACT_EXTRACTION_PROMPT.encode("utf-8")).hexdigest()
