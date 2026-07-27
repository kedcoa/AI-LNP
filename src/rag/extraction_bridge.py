from __future__ import annotations

from dataclasses import dataclass

from .guardrails import evidence_prompt, gate_packet
from .index import HybridIndex
from .models import RetrievalPacket, RetrievalQuery


FIELD_QUERIES = {
    "formulation": (
        "What exact LNP lipid components, chemical names, molar ratios, and preparation "
        "conditions are reported?", [], "formulation"
    ),
    "payload": (
        "What exact molecular cargo is encapsulated, and what does it encode or target?",
        ["lnp", "payload"], "payload"
    ),
    "biological_model": (
        "For each distinct LNP intervention, what species, biological model, disease or "
        "physiological context, dose, route, timepoint, and control are reported?",
        ["lnp", "species"], "model_context"
    ),
    "recipient_cell": (
        "Which cells physically receive the LNP or express its payload in each experiment?",
        ["lnp", "cell"], "recipient_cell"
    ),
    "therapeutic_target": (
        "Which cells are acted upon for the therapeutic effect in each experiment, "
        "distinguishing them from delivery recipient cells?", ["cell"], "therapeutic_target"
    ),
    "assay": (
        "For each distinct LNP intervention, which assay or measurement method was used, "
        "and which experiment does it belong to?", [], "outcome"
    ),
    "endpoint": (
        "For each distinct LNP intervention, what endpoint was measured, including "
        "negative, qualitative, cell-specific, and comparator endpoints?",
        ["outcome"], "outcome"
    ),
    "outcomes": (
        "For each endpoint in each distinct LNP intervention, what exact quantitative or "
        "qualitative outcome was observed, including zero, absent, or below-detection results?",
        ["outcome"], "outcome"
    ),
}


@dataclass
class ExtractionInput:
    paper_id: str
    packets: dict[str, RetrievalPacket]

    def validated_context(self) -> dict[str, str]:
        return {field: evidence_prompt(packet) for field, packet in self.packets.items()}


def retrieve_extraction_input(index: HybridIndex, paper_id: str, k: int = 6) -> ExtractionInput:
    packets = {}
    for number, (field, (question, entity_types, group)) in enumerate(FIELD_QUERIES.items(), 1):
        packet = index.retrieve(RetrievalQuery(
            query_id=f"{paper_id}-{number:02d}-{field}",
            paper_id=paper_id,
            question=question,
            field_group=group,
            required_entity_types=entity_types,
        ), k=k)
        packet = index.expand_hierarchy_context(packet)
        packets[field] = packet
    return ExtractionInput(paper_id=paper_id, packets=packets)


def blocked_fields(value: ExtractionInput) -> dict[str, list[str]]:
    return {
        field: gate.reasons
        for field, packet in value.packets.items()
        if not (gate := gate_packet(packet)).passed
    }
