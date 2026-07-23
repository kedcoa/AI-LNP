from __future__ import annotations

import re

from .models import DocumentBlock, EntityCandidate


PATTERNS = {
    "lnp": r"\b(?:lipid nanoparticles?|LNPs?|liposomes?)\b",
    "payload": r"\b(?:mRNA|siRNA|sgRNA|saRNA|circRNA|messenger RNA|small interfering RNA)\b",
    "cell": r"\b(?:hepatocytes?|Kupffer cells?|LSECs?|liver sinusoidal endothelial cells?|hepatic stellate cells?|HSCs?|macrophages?|BMDMs?|endothelial cells?)\b",
    "species": r"\b(?:mice|mouse|rats?|human|humans?)\b",
    "route": r"\b(?:intravenously|intravenous|tail vein|oral(?:ly)?|intramuscular(?:ly)?)\b",
    "gene_or_protein": r"\b(?:Cas9|FVIII|Micu1|MICU1|HGF|EGF|eGFP|EGFP|FAP|FAPCAR)\b",
    "lipid_or_material": r"\b(?:MC3|SM-102|DSPC|DOPE|cholesterol|DMG-PEG(?:2000|2K)?|DSPE-PEG(?:-maleimide)?)\b",
    "outcome": r"\b(?:expression|transfection|translation|uptake|activity|frequency|efficiency|ameliorat\w*|reduc\w*|increas\w*)\b",
}


def regex_candidates(blocks: list[DocumentBlock]) -> list[EntityCandidate]:
    rows = []
    count = 0
    for block in blocks:
        for entity_type, pattern in PATTERNS.items():
            for match in re.finditer(pattern, block.text, re.I):
                count += 1
                rows.append(EntityCandidate(
                    candidate_id=f"EC-{count:07d}", paper_id=block.paper_id, block_id=block.block_id,
                    text=match.group(0), entity_type=entity_type,
                    char_start=match.start(), char_end=match.end(),
                    detector="high_precision_regex", confidence=0.95,
                ))
    return rows


def scispacy_candidates(blocks: list[DocumentBlock]) -> list[EntityCandidate]:
    """Optional candidate enrichment; absence never blocks deterministic candidates."""
    try:
        import spacy
        nlp = spacy.load("en_core_sci_sm")
    except (ImportError, OSError):
        return []
    rows = []
    count = 0
    for block in blocks:
        for entity in nlp(block.text).ents:
            count += 1
            rows.append(EntityCandidate(
                candidate_id=f"SC-{count:07d}", paper_id=block.paper_id, block_id=block.block_id,
                text=entity.text, entity_type="gene_or_protein",
                char_start=entity.start_char, char_end=entity.end_char,
                detector="scispacy_en_core_sci_sm", confidence=0.65,
            ))
    return rows
