import hashlib
import json

from src.extraction.build_provisional_experiments import (
    build_provisional_inventory,
)
from src.rag.compact_api_packet import (
    ApiEvidence,
    ApiSource,
    CompactApiPacket,
)


def packet(rows: list[str]) -> CompactApiPacket:
    source = ApiSource(
        source_id="S1",
        chunk_id="B1",
        source_path="paper.xml",
        source_kind="pmc_xml",
        block_type="paragraph",
        section="Results",
    )
    evidence = [
        ApiEvidence(
            evidence_id=f"E{index}",
            text=text,
            retrieval_field_tags=["outcomes"],
            source_ids=["S1"],
        )
        for index, text in enumerate(rows, 1)
    ]
    unsigned = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": "GP-X",
        "blocked_fields": [],
        "sources": [source.model_dump(mode="json", exclude_none=True)],
        "evidence": [
            row.model_dump(mode="json", exclude_none=True)
            for row in evidence
        ],
    }
    canonical = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return CompactApiPacket.model_validate(
        {
            **unsigned,
            "packet_checksum": hashlib.sha256(canonical.encode()).hexdigest(),
        }
    )


def test_reporter_and_editing_activities_are_separate():
    inventory = build_provisional_inventory(
        packet(
            [
                (
                    "Mice received GFP mRNA-LNP intravenously and liver "
                    "sections showed GFP expression in LYVE-1-positive LSECs."
                ),
                (
                    "Mice were injected with Cas9 mRNA and sgRNA LNPs for "
                    "in vivo editing measured by sequencing."
                ),
            ]
        )
    )
    payloads = {
        experiment.anchors[0].value
        for experiment in inventory.experiments
    }
    assert payloads == {"egfp_gfp", "cas9_sgrna"}


def test_same_payload_is_split_across_in_vitro_and_in_vivo_contexts():
    inventory = build_provisional_inventory(
        packet(
            [
                (
                    "BMDMs were incubated in vitro with FAPCAR mRNA LNPs "
                    "and phagocytosed activated HSCs."
                ),
                (
                    "Fibrotic mice were treated in vivo with FAPCAR mRNA "
                    "LNPs and liver fibrosis was reduced."
                ),
            ]
        )
    )
    labels = {experiment.label for experiment in inventory.experiments}
    assert labels == {"fapcar / in_vitro", "fapcar / in_vivo"}


def test_unknown_context_joins_one_compatible_payload_context():
    inventory = build_provisional_inventory(
        packet(
            [
                "Mice received GFP mRNA-LNP and expressed GFP in liver cells.",
                "GFP expression colocalized with LYVE-1.",
            ]
        )
    )
    assert len(inventory.experiments) == 1
    assert len(inventory.experiments[0].anchors[0].evidence_ids) == 2


def test_background_payload_mentions_do_not_create_experiments():
    value = packet(["GFP reporters are commonly used in prior LNP studies."])
    value.sources[0].section = "Introduction"
    assert build_provisional_inventory(value).experiments == []
