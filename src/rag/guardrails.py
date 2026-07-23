from __future__ import annotations

import re
from collections import Counter

from .models import EvidenceGate, RetrievalPacket


NEGATION = re.compile(r"\b(no|not|none|without|failed|did not|was not|were not)\b", re.I)


def gate_packet(
    packet: RetrievalPacket,
    *,
    min_hits: int = 2,
    require_entity_types: bool = True,
) -> EvidenceGate:
    """Prevent retrieval output from silently becoming an extracted fact."""
    reasons: list[str] = []
    if len(packet.hits) < min_hits:
        reasons.append(f"Only {len(packet.hits)} evidence block(s) were retrieved.")
    if any(hit.paper_id != packet.query.paper_id for hit in packet.hits):
        reasons.append("Cross-paper evidence leakage detected.")
    if require_entity_types and packet.query.required_entity_types:
        observed = Counter(t for hit in packet.hits for t in hit.entity_types)
        missing = [t for t in packet.query.required_entity_types if not observed[t]]
        if missing:
            reasons.append("Required entity types absent from evidence: " + ", ".join(missing))
    block_ids = [hit.block_id for hit in packet.hits]
    if len(block_ids) != len(set(block_ids)):
        reasons.append("Duplicate evidence blocks detected.")
    polarity = {bool(NEGATION.search(hit.text)) for hit in packet.hits}
    contradictory = len(polarity) > 1
    if contradictory:
        # Mixed polarity is common in legitimate comparisons (e.g. uptake but no
        # translation). Preserve it for review; do not discard the evidence packet.
        pass
    passed = not reasons
    return EvidenceGate(
        passed=passed,
        paper_id=packet.query.paper_id,
        query_id=packet.query.query_id,
        accepted_block_ids=block_ids if passed else [],
        reasons=reasons,
        requires_human_review=contradictory,
    )


def evidence_prompt(packet: RetrievalPacket) -> str:
    """Serialize source text without letting a generated answer masquerade as evidence."""
    gate = gate_packet(packet)
    if not gate.passed:
        raise ValueError("Evidence gate failed: " + "; ".join(gate.reasons))
    return "\n\n".join(
        (
            f"[{hit.block_id}] paper={hit.paper_id}; section={hit.section_path}; "
            f"source={hit.source_path}; page={hit.page_number or 'n/a'}\n{hit.text}"
        )
        for hit in packet.hits
    )
