"""Short scientific instructions for compact extraction route v1."""

from __future__ import annotations

import hashlib


PROMPT_VERSION = "compact-prompt-1.1.0"

COMPACT_EXTRACTION_PROMPT = (
    "Extract only directly reported LNP evidence from the supplied packet. "
    "Use no outside knowledge. For every scientific field, return either a reported value "
    "with valid packet evidence IDs or missing with a short reason and no evidence IDs. "
    "Set eligibility to eligible only for original experimental LNP delivery of mRNA, siRNA, "
    "saRNA, or circRNA with evidence relevant to hepatocytes, Kupffer cells, LSECs, or hepatic "
    "stellate cells and a formulation-experiment-outcome link. Set a clearly failed criterion "
    "to ineligible and insufficient evidence to uncertain. Ineligible or uncertain papers "
    "must return empty extraction lists. "
    "Keep formulations, components, experiments, and outcomes separate and preserve their "
    "links. Do not infer hepatocytes from liver-level evidence. "
    "Do not mix facts from different experiments. "
    "Do not store payload as an LNP component. "
    "Do not convert a mechanism, hypothesis, or interpretation into a measured outcome. "
    "A reported negative result is an outcome, not missing. List unresolved ambiguities. "
    "Return only the structured response required by the supplied schema."
)


def prompt_sha256() -> str:
    return hashlib.sha256(COMPACT_EXTRACTION_PROMPT.encode("utf-8")).hexdigest()
