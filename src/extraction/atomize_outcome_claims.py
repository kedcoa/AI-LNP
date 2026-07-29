"""Deterministically split local evidence into evidence-backed outcome claims."""

from __future__ import annotations

import hashlib
import re

from src.extraction.v12_structure_contracts import (
    AtomicClaimV12,
    EvidenceReferenceV12,
)
from src.rag.compact_api_packet import CompactApiPacket


RELATIONS = [
    ("recognized", re.compile(r"\brecogniz(?:ed|es|ing)\b", re.I)),
    ("phagocytosed", re.compile(r"\bphagocyt(?:osed|osing|es)\b", re.I)),
    ("eliminated", re.compile(r"\b(?:eliminat(?:ed|es|ing)|eradicated)\b", re.I)),
    (
        "colocalized_with",
        re.compile(r"\b(?:co-?locali[sz](?:ed|ation)|co-stain(?:ed|ing)?)\b", re.I),
    ),
    ("localized_to", re.compile(r"\blocali[sz](?:ed|ation)\b", re.I)),
    ("expressed", re.compile(r"\bexpress(?:ed|es|ion|ing)?\b", re.I)),
    ("uptake_by", re.compile(r"\b(?:uptake|internaliz(?:ed|ation))\b", re.I)),
    (
        "edited",
        re.compile(r"\b(?:edit(?:ed|ing)|insertion|deletion|indel)\b", re.I),
    ),
    ("delivered_to", re.compile(r"\bdeliver(?:ed|y|ies)\b", re.I)),
    ("increased", re.compile(r"\b(?:increased|higher|enhanced)\b", re.I)),
    ("decreased", re.compile(r"\b(?:decreased|lower)\b", re.I)),
    ("reduced", re.compile(r"\b(?:reduced|attenuated|diminished)\b", re.I)),
    ("reached", re.compile(r"\b(?:reached|achieved|generated)\b", re.I)),
    ("maintained", re.compile(r"\b(?:maintained|sustained)\b", re.I)),
]
CLAUSE_SPLIT = re.compile(
    r"\s*(?:;|\bwhile\b|\bwhereas\b|\bindicating that\b|"
    r"\bsuggesting that\b|,\s*together with\b)\s*",
    re.I,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])(?:\s+|(?=Figure\b))")
MIXED_CELL_EXPRESSION = re.compile(
    r"^(?P<positive>.*?\b(?P<marker>[A-Za-z0-9α-]+)\s+expression\b"
    r".*?\b(?:in|among)\s+(?P<positive_cells>[^,.;()]+?))"
    r"\s*(?:,\s*)?and\s+(?:was|were|is|are)\s+"
    r"(?P<negative_qual>(?:almost\s+)?absent|not detectable)"
    r"\s+(?:in|among)\s+(?P<negative_cells>[^,.;()]+)",
    re.I,
)
BIOLOGICAL_CONTEXT = re.compile(
    r"\b(?:cells?|liver|hepatic|hepatocytes?|Kupffer|LSECs?|LYVE-?1|"
    r"macrophages?|BMDMs?|HSCs?|stellate|F4/80|CD11b|CD163|GFP|eGFP|"
    r"FAPCAR|FVIII|factor VIII|fibrosis|mitochondri|calcium|"
    r"defenestration|insertion|deletion|indel|activity|PCNA|Heps?|"
    r"ALT|serum|steatosis)\b",
    re.I,
)
CELL_MENTIONS = re.compile(
    r"\b(?:F4/80[- ]positive\s+Kupffer cells?|CD11b[- ]positive cells?|"
    r"LYVE-?1[- ]positive\s+(?:liver cells?|LSECs?)|"
    r"Desmin[- ]positive\s+HSCs?|FAP[- ]positive\s+activated HSCs?|"
    r"activated HSCs?|Kupffer cells?|hepatocytes?|LSECs?|"
    r"BMDMs?|macrophages?|hepatic stellate cells?|HSCs?|Heps?|"
    r"hepatic cell types?|parenchyma of the liver)\b",
    re.I,
)
ENDPOINT = re.compile(
    r"\b(?:e?GFP expression|luciferase expression|expression|uptake|"
    r"insertion frequency|deletion frequency|indel frequency|"
    r"FVIII activity|factor VIII activity|activity|fibrosis|"
    r"mitochondrial damage|calcium accumulation|defenestration)\b",
    re.I,
)
NUMBER = re.compile(
    r"(?:(?P<qualifier>over|under|more than|less than|fewer than|about|approximately)"
    r"\s+)?(?P<value>\d+(?:\.\d+)?)"
    r"(?:(?:\s*(?:±|\+/-)\s*(?P<uncertainty>\d+(?:\.\d+)?))"
    r"\s*(?P<uncertainty_unit>%|percent|fold)?"
    r"|\s*(?P<unit>%|percent|fold))",
    re.I,
)
QUALITATIVE = re.compile(
    r"\b(?:few|absent|no obvious|virtually all|solely|exclusively|"
    r"higher|lower|rapid|strong|significant(?:ly)?|markedly|"
    r"colocali[sz](?:ed|ation)|localized|sustained|maintained|"
    r"reduced|attenuated|recognized|phagocytosed|eliminated)\b",
    re.I,
)
NEGATIVE = re.compile(
    r"\b(?:no|not|none|absent|without|rather than)\b",
    re.I,
)


def _subject(segment: str, relation_start: int) -> str:
    before = segment[:relation_start]
    cells = list(CELL_MENTIONS.finditer(before))
    if cells:
        return cells[-1].group(0).strip()
    following_cells = list(CELL_MENTIONS.finditer(segment[relation_start:]))
    if following_cells:
        return following_cells[0].group(0).strip()
    cleaned = re.sub(
        r"^(?:the\s+)?(?:results?|images?|analysis|study|data)\s+"
        r"(?:showed|indicated|demonstrated|found)\s+(?:that\s+)?",
        "",
        before,
        flags=re.I,
    ).strip(" ,:-")
    words = cleaned.split()
    return " ".join(words[-10:]) or "reported outcome"


def _object(
    segment: str,
    relation_end: int,
    *,
    next_relation_start: int | None,
    final_relation_end: int,
) -> str | None:
    tail = segment[relation_end:].strip(" ,:-")
    if next_relation_start is not None:
        between = segment[relation_end:next_relation_start]
        between = re.sub(
            r"^(?:\s|,|\band\b|\bbut\b|\bnot only\b|\bcan also\b)+",
            "",
            between,
            flags=re.I,
        ).strip(" ,:-")
        if between:
            tail = re.sub(
                r"\s+\b(?:and|but)\s+(?:can\s+)?(?:also)?\s*$",
                "",
                between,
                flags=re.I,
            ).strip()
        else:
            tail = segment[final_relation_end:].strip(" ,:-")
    elif final_relation_end > relation_end:
        tail = segment[final_relation_end:].strip(" ,:-")
    tail = re.sub(r"^(?:with|to|by|in|of)\s+", "", tail, flags=re.I)
    tail = re.split(
        r"[.;]|,?\s+(?:suggesting|indicating)\s+that\b",
        tail,
        maxsplit=1,
        flags=re.I,
    )[0].strip()
    tail = re.sub(
        r"\s*\((?:Supplementary\s+)?Fig(?:ure)?\.?.*$",
        "",
        tail,
        flags=re.I,
    ).strip(" ,:-")
    return tail[:240] or None


def _atomic_segments(text: str) -> list[str]:
    segments: list[str] = []
    for sentence in SENTENCE_SPLIT.split(text):
        for segment in CLAUSE_SPLIT.split(sentence):
            segment = segment.strip(" ,")
            if not segment:
                continue
            mixed = MIXED_CELL_EXPRESSION.match(segment)
            if mixed:
                segments.extend(
                    [
                        mixed.group("positive").strip(" ,"),
                        (
                            f"{mixed.group('marker')} expression was "
                            f"{mixed.group('negative_qual')} in "
                            f"{mixed.group('negative_cells')}"
                        ).strip(" ,"),
                    ]
                )
            else:
                segments.append(segment)
    return segments


def _nominal_relation_is_superseded(
    segment: str,
    predicate: str,
    match: re.Match[str],
    relation_matches: list[tuple[str, re.Match[str]]],
) -> bool:
    """Avoid duplicating a comparative expression fact as plain expression."""

    if (
        predicate == "colocalized_with"
        and match.group(0).casefold() == "colocalization"
        and re.match(r"\s+(?:stud(?:y|ies)|analysis|assay)\b", segment[match.end():], re.I)
    ):
        return True
    if predicate != "expressed" or match.group(0).casefold() != "expression":
        return False
    comparative = {"increased", "decreased", "reduced"}
    return any(
        other_predicate in comparative
        and abs(other_match.start() - match.end()) <= 100
        for other_predicate, other_match in relation_matches
    )


def _polarity(segment: str) -> str:
    without_not_only = re.sub(r"\bnot\s+only\b", "", segment, flags=re.I)
    return "negative" if NEGATIVE.search(without_not_only) else "positive"


def _comparator_only(segment: str, relation_start: int) -> bool:
    before = segment[:relation_start]
    comparison = re.search(r"\bcompar(?:ed|ison)\s+to\b", before, re.I)
    comparator_clause = re.search(r"\b(?:in|for)\s+which\b", before, re.I)
    return bool(
        comparison
        and comparator_clause
        and comparator_clause.start() > comparison.start()
    )


def atomize(packet: CompactApiPacket) -> list[AtomicClaimV12]:
    claims: list[AtomicClaimV12] = []
    sources = {source.source_id: source for source in packet.sources}
    for evidence in packet.evidence:
        if "outcomes" not in evidence.retrieval_field_tags:
            continue
        source_kinds = {
            sources[source_id].source_kind
            for source_id in evidence.source_ids
            if source_id in sources
        }
        if source_kinds and all(kind == "pdf" for kind in source_kinds):
            continue
        for segment_index, segment in enumerate(_atomic_segments(evidence.text), 1):
            if not BIOLOGICAL_CONTEXT.search(segment):
                continue
            relation_matches = [
                (predicate, match)
                for predicate, pattern in RELATIONS
                for match in pattern.finditer(segment)
            ]
            relation_matches.sort(key=lambda row: row[1].start())
            if not relation_matches:
                continue
            final_relation_end = relation_matches[-1][1].end()
            numbers = list(NUMBER.finditer(segment))
            endpoints = list(ENDPOINT.finditer(segment))
            qualitative_matches = list(QUALITATIVE.finditer(segment))
            for relation_index, (predicate, match) in enumerate(
                relation_matches, 1
            ):
                if _nominal_relation_is_superseded(
                    segment, predicate, match, relation_matches
                ):
                    continue
                number = min(
                    numbers,
                    key=lambda value: min(
                        abs(value.start() - match.end()),
                        abs(match.start() - value.end()),
                    ),
                    default=None,
                )
                endpoint = min(
                    endpoints,
                    key=lambda value: min(
                        abs(value.start() - match.end()),
                        abs(match.start() - value.end()),
                    ),
                    default=None,
                )
                qualitative = min(
                    qualitative_matches,
                    key=lambda value: min(
                        abs(value.start() - match.end()),
                        abs(match.start() - value.end()),
                    ),
                    default=None,
                )
                subject = _subject(segment, match.start())
                object_text = _object(
                    segment,
                    match.end(),
                    next_relation_start=(
                        relation_matches[relation_index][1].start()
                        if relation_index < len(relation_matches)
                        else None
                    ),
                    final_relation_end=final_relation_end,
                )
                if not any((object_text, endpoint, qualitative, number)):
                    continue
                digest = hashlib.sha256(
                    (
                        f"{packet.paper_id}:{evidence.evidence_id}:"
                        f"{segment_index}:{relation_index}:{predicate}:"
                        f"{subject}:{object_text or ''}"
                    ).encode()
                ).hexdigest()[:16]
                references = [
                    EvidenceReferenceV12(
                        evidence_id=evidence.evidence_id,
                        source_id=source_id,
                        quote=segment,
                    )
                    for source_id in evidence.source_ids
                ]
                qualifier = number.group("qualifier") if number else None
                value_text = number.group(0).strip() if number else None
                claims.append(
                    AtomicClaimV12(
                        claim_id=f"ACL-{digest}",
                        claim_kind="outcome",
                        subject_text=subject,
                        predicate=predicate,
                        object_text=object_text,
                        endpoint_text=endpoint.group(0) if endpoint else None,
                        qualitative_result=(
                            qualitative.group(0) if qualitative else None
                        ),
                        numeric_value=(
                            float(number.group("value")) if number else None
                        ),
                        value_text=(
                            f"{qualifier} {value_text}".strip()
                            if qualifier and value_text
                            else value_text
                        ),
                        unit=(
                            (
                                number.group("unit")
                                or number.group("uncertainty_unit")
                            )
                            if number
                            else None
                        ),
                        polarity=(
                            _polarity(segment)
                        ),
                        evidence=references,
                        review_status=(
                            "needs_review"
                            if _comparator_only(segment, match.start())
                            else "supported"
                        ),
                    )
                )
    return claims
