"""Build a coarse, gold-blind experiment inventory from local evidence.

The inventory deliberately precedes atomic claim assignment.  It identifies
paper-level activities from payload and experimental-context anchors; it does
not decide how many outcomes each activity contains.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from src.extraction.build_full_outcome_inventory import full_corpus_view
from src.extraction.v12_structure_contracts import (
    ExperimentAnchorV12,
    ProvisionalExperimentInventoryV12,
    ProvisionalExperimentV12,
)
from src.rag.compact_api_packet import ApiEvidence, CompactApiPacket
from src.rag.compact_packet import CompactEvidencePacket


ROOT = Path(__file__).resolve().parents[2]
PACKET_ROOT = ROOT / "data/staging/rag/compact_packets_v1"
CORPUS_ROOT = ROOT / "data/staging/rag/gold_v1"
OUTPUT_ROOT = ROOT / "data/staging/extraction/v12_provisional_experiments"

PAYLOAD_PATTERNS = [
    ("fapcar", re.compile(r"\b(?:FAPCAR|CAR[- ]?M)\b", re.I)),
    (
        "cas9_sgrna",
        re.compile(r"\b(?:Cas9|sgRNA|NSGHA|CRISPR)\w*\b", re.I),
    ),
    ("simicu1", re.compile(r"\bsiMicu1\b", re.I)),
    ("hgf_egf", re.compile(r"\b(?:HGF|EGF)\b", re.I)),
    (
        "egfp_gfp",
        re.compile(r"\b(?:eGFP|GFP|green fluorescent protein)\b", re.I),
    ),
    ("luciferase_zsgreen", re.compile(r"\b(?:luciferase|ZsGreen)\b", re.I)),
    ("sirna", re.compile(r"\bsiRNA\b", re.I)),
]
GENERIC_LNP = re.compile(r"\b(?:LNP|lipid nanoparticle)s?\b", re.I)
EXPERIMENT_SIGNAL = re.compile(
    r"\b(?:administer|inject|treat|expos|incubat|transfect|deliver|"
    r"express|edit|insert|delet|indel|uptake|colocali[sz]|"
    r"recogniz|phagocyt|eliminat|measure|assay|stain|imaging|"
    r"flow cytometry|sequenc|activity|efficacy|fibrosis)\w*\b",
    re.I,
)
IN_VITRO = re.compile(
    r"\b(?:in vitro|cultured?|cell culture|incubat|BMDMs?|JS-?1|LX-?2|"
    r"cell line)\b",
    re.I,
)
IN_VIVO = re.compile(
    r"\b(?:in vivo|mice|mouse|murine|intravenous|tail vein|mg/kg|"
    r"liver sections?|fibrotic liver)\b",
    re.I,
)
CELL_PATTERNS = {
    "kupffer_cell": re.compile(r"\b(?:Kupffer|F4/80)\b", re.I),
    "lsec": re.compile(
        r"\b(?:LSEC|liver sinusoidal endothelial|LYVE-?1)\w*\b",
        re.I,
    ),
    "hepatocyte": re.compile(r"\b(?:hepatocyte|Heps?)\b", re.I),
    "macrophage": re.compile(r"\b(?:macrophage|BMDM|CD163)\w*\b", re.I),
    "hsc": re.compile(
        r"\b(?:HSCs?|hepatic stellate|stellate cells?|JS-?1)\b",
        re.I,
    ),
}
ASSAY_PATTERNS = {
    "immunostaining": re.compile(
        r"\b(?:immunostain|immunofluorescen|immunohistochem|IHC)\w*\b",
        re.I,
    ),
    "flow_cytometry": re.compile(r"\bflow cytometr\w*\b", re.I),
    "sequencing": re.compile(r"\b(?:sequenc|scRNA-seq)\w*\b", re.I),
    "imaging": re.compile(r"\b(?:imaging|microscop)\w*\b", re.I),
    "phagocytosis_cytotoxicity": re.compile(
        r"\b(?:phagocyt|cytotoxic|eliminat|killing)\w*\b",
        re.I,
    ),
    "coagulation_activity": re.compile(
        r"\b(?:aPTT|FVIII|factor VIII|coagulation)\b",
        re.I,
    ),
    "histology": re.compile(
        r"\b(?:histolog|Sirius red|fibrosis staining)\w*\b",
        re.I,
    ),
}
BACKGROUND_SECTION = re.compile(
    r"\b(?:introduction|background|discussion|references?)\b",
    re.I,
)


def _payload_signature(text: str) -> str | None:
    for name, pattern in PAYLOAD_PATTERNS:
        if pattern.search(text):
            return name
    if GENERIC_LNP.search(text) and EXPERIMENT_SIGNAL.search(text):
        return "generic_lnp"
    return None


def _context(text: str) -> str:
    in_vitro = bool(IN_VITRO.search(text))
    in_vivo = bool(IN_VIVO.search(text))
    if in_vitro and not in_vivo:
        return "in_vitro"
    if in_vivo and not in_vitro:
        return "in_vivo"
    return "unknown"


def _stable_experiment_id(
    paper_id: str,
    payload_signature: str,
    context: str,
) -> str:
    digest = hashlib.sha256(
        f"{paper_id}:{payload_signature}:{context}".encode()
    ).hexdigest()[:12]
    return f"PEX-{paper_id}-{digest}"


def _anchor(
    anchor_type: str,
    value: str,
    rows: list[ApiEvidence],
) -> ExperimentAnchorV12:
    return ExperimentAnchorV12(
        anchor_type=anchor_type,
        value=value,
        evidence_ids=list(dict.fromkeys(row.evidence_id for row in rows)),
    )


def _collapse_unknown_contexts(
    grouped: dict[tuple[str, str], list[ApiEvidence]],
) -> dict[tuple[str, str], list[ApiEvidence]]:
    collapsed = {key: list(rows) for key, rows in grouped.items()}
    for signature in {key[0] for key in grouped}:
        unknown_key = (signature, "unknown")
        known_keys = [
            key
            for key in grouped
            if key[0] == signature and key[1] != "unknown"
        ]
        if unknown_key not in collapsed or not known_keys:
            continue
        unknown_rows = collapsed.pop(unknown_key)
        if len(known_keys) == 1:
            collapsed[known_keys[0]].extend(unknown_rows)
        # With two known contexts, context-free rows are shared/ambiguous
        # support. They must not manufacture a third experiment.
    return collapsed


def build_provisional_inventory(
    packet: CompactApiPacket,
) -> ProvisionalExperimentInventoryV12:
    sources = {row.source_id: row for row in packet.sources}
    grouped: dict[tuple[str, str], list[ApiEvidence]] = defaultdict(list)
    for evidence in packet.evidence:
        signature = _payload_signature(evidence.text)
        if signature is None or not EXPERIMENT_SIGNAL.search(evidence.text):
            continue
        sections = " ".join(
            sources[source_id].section
            for source_id in evidence.source_ids
            if source_id in sources
        )
        if BACKGROUND_SECTION.search(sections):
            continue
        grouped[(signature, _context(evidence.text))].append(evidence)

    grouped = _collapse_unknown_contexts(grouped)
    grouped = {
        key: rows
        for key, rows in grouped.items()
        if any(GENERIC_LNP.search(row.text) for row in rows)
    }
    if any(key[0] != "generic_lnp" for key in grouped):
        grouped = {
            key: rows
            for key, rows in grouped.items()
            if key[0] != "generic_lnp"
        }
    experiments: list[ProvisionalExperimentV12] = []
    for (signature, context), rows in sorted(grouped.items()):
        anchors = [_anchor("payload", signature, rows)]
        if context != "unknown":
            anchors.append(_anchor("model", context, rows))

        joined = " ".join(row.text for row in rows)
        for value, pattern in CELL_PATTERNS.items():
            matched = [row for row in rows if pattern.search(row.text)]
            if matched:
                anchors.append(_anchor("cell_context", value, matched))
        for value, pattern in ASSAY_PATTERNS.items():
            matched = [row for row in rows if pattern.search(row.text)]
            if matched:
                anchors.append(_anchor("assay", value, matched))

        identifier = _stable_experiment_id(packet.paper_id, signature, context)
        experiments.append(
            ProvisionalExperimentV12(
                provisional_experiment_id=identifier,
                label=f"{signature} / {context}",
                anchors=anchors,
                boundary_status=(
                    "inferred" if context != "unknown" else "ambiguous"
                ),
                boundary_reason=(
                    "Grouped by a distinct payload/intervention signature and "
                    "experimental context; atomic claims are assigned later."
                ),
                confidence="medium" if context != "unknown" else "low",
            )
        )

    return ProvisionalExperimentInventoryV12(
        inventory_version="provisional-experiments-1.2.0",
        paper_id=packet.paper_id,
        source_packet_checksum=packet.packet_checksum,
        experiments=experiments,
        validation_notes=[
            "Gold annotations were not read by this builder.",
            "Unknown-context evidence is merged only when exactly one compatible "
            "context exists for that payload signature.",
        ],
    )


def load_full_view(paper_id: str) -> CompactApiPacket:
    packet_path = PACKET_ROOT / f"{paper_id}.json"
    packet = CompactEvidencePacket.model_validate_json(
        packet_path.read_text(encoding="utf-8")
    )
    corpus_path = CORPUS_ROOT / f"{paper_id}.blocks.jsonl"
    return full_corpus_view(packet, corpus_path)


def write_inventory(
    paper_id: str,
    *,
    output_root: Path = OUTPUT_ROOT,
) -> Path:
    inventory = build_provisional_inventory(load_full_view(paper_id))
    destination = output_root / paper_id / "inventory.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        inventory.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append")
    args = parser.parse_args()
    paper_ids = args.paper_id or sorted(
        path.stem for path in PACKET_ROOT.glob("GP-*.json")
    )
    written = [str(write_inventory(paper_id)) for paper_id in paper_ids]
    print(json.dumps({"written": written}, indent=2))


if __name__ == "__main__":
    main()
