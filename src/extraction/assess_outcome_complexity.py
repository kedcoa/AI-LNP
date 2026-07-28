"""Cheaply classify compact packets before candidate building or the first LLM call."""

from __future__ import annotations

import re

from src.extraction.build_outcome_candidates import (
    DIRECT_SIGNAL,
    ENDPOINT_PATTERNS,
    INTERVENTION_SIGNAL,
    OUTCOME_VALUE,
    QUANTITATIVE_BIOLOGICAL_RESULT,
    RESULT_SIGNAL,
    TARGET_CONTEXT_SIGNAL,
    VISUAL_REFERENCE,
    VISUAL_OUTCOME_SIGNAL,
)
from src.extraction.outcome_coverage_contracts import ComplexityAssessment
from src.rag.compact_api_packet import CompactApiPacket


def assess(packet: CompactApiPacket) -> ComplexityAssessment:
    """Use a fast signal census; never construct detailed outcome candidates."""
    sources = {
        row.source_id: row.model_dump(mode="json", exclude_none=True)
        for row in packet.sources
    }
    signal_passages = []
    families: set[str] = set()
    contextual_passages = 0
    contextual_families: set[str] = set()
    visual_locations: set[str] = set()
    outcome_tagged_passages = sum(
        "outcomes" in evidence.retrieval_field_tags for evidence in packet.evidence
    )
    for evidence in packet.evidence:
        outcome_tagged = "outcomes" in evidence.retrieval_field_tags
        tag_robust_outcome = bool(
            QUANTITATIVE_BIOLOGICAL_RESULT.search(evidence.text)
            or (
                RESULT_SIGNAL.search(evidence.text)
                and INTERVENTION_SIGNAL.search(evidence.text)
                and TARGET_CONTEXT_SIGNAL.search(evidence.text)
            )
            or (
                VISUAL_REFERENCE.search(evidence.text)
                and VISUAL_OUTCOME_SIGNAL.search(evidence.text)
            )
        )
        if not outcome_tagged and not tag_robust_outcome:
            continue
        if not DIRECT_SIGNAL.search(evidence.text):
            continue
        passage_families = {
            name
            for name, pattern in ENDPOINT_PATTERNS.items()
            if re.search(pattern, evidence.text, re.I)
        }
        if not passage_families:
            continue
        if INTERVENTION_SIGNAL.search(evidence.text):
            contextual_passages += 1
            contextual_families |= passage_families
        text_visual = VISUAL_REFERENCE.search(evidence.text)
        strong = bool(
            OUTCOME_VALUE.search(evidence.text)
            or (
                RESULT_SIGNAL.search(evidence.text)
                and INTERVENTION_SIGNAL.search(evidence.text)
            )
            or (
                text_visual
                and VISUAL_OUTCOME_SIGNAL.search(evidence.text)
                and (
                    INTERVENTION_SIGNAL.search(evidence.text)
                    or "gene_editing" in passage_families
                )
            )
        )
        if not strong:
            continue
        signal_passages.append(evidence)
        families |= passage_families
        if text_visual:
            visual_locations.add(text_visual.group(1).lower())
        for source_id in evidence.source_ids:
            source = sources.get(source_id, {})
            location = (
                source.get("table_number")
                or source.get("figure_number")
                or source.get("supplement_identifier")
            )
            if location:
                visual_locations.add(str(location).lower())
    reasons: list[str] = []
    score = 0
    if len(signal_passages) >= 8:
        score += 2
        reasons.append("eight_or_more_direct_outcome_groups")
    elif len(signal_passages) >= 4:
        score += 1
        reasons.append("four_to_seven_direct_outcome_groups")
    if len(families) >= 4:
        score += 2
        reasons.append("four_or_more_endpoint_families")
    elif len(families) >= 2:
        score += 1
        reasons.append("multiple_endpoint_families")
    if visual_locations:
        score += 2
        reasons.append("visual_outcome_evidence")
    if len(visual_locations) >= 2:
        score += 1
        reasons.append("multiple_visual_outcome_locations")
    if contextual_passages >= 4:
        score += 2
        reasons.append("four_or_more_intervention_endpoint_passages")
    if len(contextual_families) >= 2:
        score += 2
        reasons.append("multiple_intervention_endpoint_families")
    if outcome_tagged_passages >= 60:
        score += 2
        reasons.append("sixty_or_more_outcome_tagged_passages")
    route = "complex" if score >= 4 else "simple"
    return ComplexityAssessment(
        assessment_version="outcome-complexity-1.1.0",
        paper_id=packet.paper_id,
        complexity_score=score,
        route=route,
        reasons=reasons,
        candidate_groups=len(signal_passages),
        endpoint_families=len(families),
        visual_candidate_groups=len(visual_locations),
    )
