"""Deterministically remove clear false positives and merge semantic duplicates."""

from __future__ import annotations

import re

from src.extraction.outcome_coverage_contracts import OutcomeCandidate
from src.extraction.outcome_inventory_contracts import (
    CandidateDisposition,
    OutcomeInventory,
)
from src.rag.compact_api_packet import CompactApiPacket


METHOD_SECTION = re.compile(r"\b(?:methods?|materials?|protocol)\b", re.I)
BACKGROUND_SECTION = re.compile(
    r"\b(?:introduction|background|references?)\b", re.I
)
FORMULA_ONLY = re.compile(
    r"(?:EE\s*\(%\)\s*=|encapsulation efficiency\s*(?:was\s+)?calculated|"
    r"formula\s+(?:used|for)|humidity|light.?dark cycle)",
    re.I,
)
BIOLOGICAL_RESULT = re.compile(
    r"\b(?:express|transfect|deliver|uptake|internaliz|edit|insert|delet|"
    r"indel|knockdown|silenc|activity|efficacy|survival|fibrosis|steatosis|"
    r"necrosis|phagocyt|eliminat|locali[sz]|colocali[sz]|protect|improv|"
    r"reduce|increase|decrease|few|virtually all|solely)\w*",
    re.I,
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _similar(first: OutcomeCandidate, second: OutcomeCandidate) -> bool:
    if first.endpoint_family != second.endpoint_family:
        return False
    if (
        first.figure_or_table
        and second.figure_or_table
        and first.figure_or_table.lower() != second.figure_or_table.lower()
    ):
        return False
    if set(first.evidence_ids) & set(second.evidence_ids):
        return True
    first_tokens = _tokens(first.evidence_text)
    second_tokens = _tokens(second.evidence_text)
    overlap = len(first_tokens & second_tokens)
    overlap_rate = overlap / max(1, min(len(first_tokens), len(second_tokens)))
    if overlap_rate >= 0.92:
        return True
    if not set(first.source_ids) & set(second.source_ids):
        return False
    return overlap_rate >= 0.72


def consolidate(
    *,
    paper_id: str,
    source_packet_checksum: str,
    candidates: list[OutcomeCandidate],
    packet: CompactApiPacket,
) -> OutcomeInventory:
    source_by_id = {row.source_id: row for row in packet.sources}
    retained: list[OutcomeCandidate] = []
    dispositions: list[CandidateDisposition] = []
    for candidate in candidates:
        sections = " ".join(
            source_by_id[source_id].section
            for source_id in candidate.source_ids
            if source_id in source_by_id
        )
        text = candidate.evidence_text
        if FORMULA_ONLY.search(text) and not re.search(
            r"\b(?:cells?|mice|rats?|liver|hepatic|hepatocyte|macrophage|"
            r"lsec|hsc|bmdm)\b",
            text,
            re.I,
        ):
            dispositions.append(
                CandidateDisposition(
                    candidate_id=candidate.candidate_id,
                    decision="rejected_formula",
                    canonical_candidate_id=None,
                    reason="Formula or environmental percentage without a biological result.",
                )
            )
            continue
        if METHOD_SECTION.search(sections) and not BIOLOGICAL_RESULT.search(text):
            dispositions.append(
                CandidateDisposition(
                    candidate_id=candidate.candidate_id,
                    decision="rejected_method",
                    canonical_candidate_id=None,
                    reason="Methods-only passage without reported biological result.",
                )
            )
            continue
        if BACKGROUND_SECTION.search(sections):
            dispositions.append(
                CandidateDisposition(
                    candidate_id=candidate.candidate_id,
                    decision="rejected_background",
                    canonical_candidate_id=None,
                    reason="Background/reference passage is not a study outcome.",
                )
            )
            continue
        duplicate = next(
            (existing for existing in retained if _similar(candidate, existing)),
            None,
        )
        if duplicate:
            duplicate.evidence_ids = list(
                dict.fromkeys([*duplicate.evidence_ids, *candidate.evidence_ids])
            )
            duplicate.source_ids = list(
                dict.fromkeys([*duplicate.source_ids, *candidate.source_ids])
            )
            dispositions.append(
                CandidateDisposition(
                    candidate_id=candidate.candidate_id,
                    decision="merged_duplicate",
                    canonical_candidate_id=duplicate.candidate_id,
                    reason="Same endpoint family and strongly overlapping source context.",
                )
            )
            continue
        retained.append(candidate)
        dispositions.append(
            CandidateDisposition(
                candidate_id=candidate.candidate_id,
                decision=(
                    "retained_unique"
                    if candidate.confidence == "high"
                    else "needs_human_review"
                ),
                canonical_candidate_id=candidate.candidate_id,
                reason=(
                    "High-confidence biological outcome candidate."
                    if candidate.confidence == "high"
                    else "Plausible outcome lacking a direct high-confidence signal."
                ),
            )
        )
    return OutcomeInventory(
        inventory_version="full-outcome-inventory-1.0.0",
        paper_id=paper_id,
        source_packet_checksum=source_packet_checksum,
        raw_candidate_count=len(candidates),
        retained_candidates=retained,
        dispositions=dispositions,
        candidate_recall_gate=(
            "needs_human_review"
            if any(row.decision == "needs_human_review" for row in dispositions)
            else "ready_for_coverage"
        ),
    )
