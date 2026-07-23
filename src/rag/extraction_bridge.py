from __future__ import annotations

from dataclasses import dataclass

from .guardrails import evidence_prompt, gate_packet
from .index import HybridIndex
from .models import RetrievalPacket, RetrievalQuery


FIELD_QUERIES = {
    "lnp_composition_raw": (
        "What exact LNP lipid components, chemical names, molar ratios, and preparation "
        "conditions are reported?", ["lnp", "lipid_or_material"], "formulation"
    ),
    "payload": (
        "What exact molecular cargo is encapsulated, and what does it encode or target?",
        ["lnp", "payload"], "payload"
    ),
    "experiment_boundary": (
        "List each distinct intervention experiment with formulation, payload, model, "
        "dose, route, timepoint, assay, and control kept together.", ["lnp"], "experiment_boundary"
    ),
    "delivery_recipient_cell_reported": (
        "Which cells physically receive the LNP or express its payload in each experiment?",
        ["lnp", "cell"], "recipient_cell"
    ),
    "therapeutic_target_cell_reported": (
        "Which cells are acted upon for the therapeutic effect in each experiment, "
        "distinguishing them from delivery recipient cells?", ["cell"], "therapeutic_target"
    ),
    "outcomes": (
        "What distinct measured endpoint names and observed outcomes are reported for "
        "each experiment?", ["outcome"], "outcome"
    ),
}


@dataclass
class ExtractionInput:
    paper_id: str
    packets: dict[str, RetrievalPacket]

    def validated_context(self) -> dict[str, str]:
        return {field: evidence_prompt(packet) for field, packet in self.packets.items()}


def retrieve_extraction_input(index: HybridIndex, paper_id: str, k: int = 10) -> ExtractionInput:
    packets = {}
    for number, (field, (question, entity_types, group)) in enumerate(FIELD_QUERIES.items(), 1):
        packet = index.retrieve(RetrievalQuery(
            query_id=f"{paper_id}-{number:02d}-{field}",
            paper_id=paper_id,
            question=question,
            field_group=group,
            required_entity_types=entity_types,
        ), k=k)
        packets[field] = packet
    return ExtractionInput(paper_id=paper_id, packets=packets)


def blocked_fields(value: ExtractionInput) -> dict[str, list[str]]:
    return {
        field: gate.reasons
        for field, packet in value.packets.items()
        if not (gate := gate_packet(packet)).passed
    }
