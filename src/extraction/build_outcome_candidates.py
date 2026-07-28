"""Group compact-packet evidence into conservative possible outcome candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from src.extraction.outcome_coverage_contracts import OutcomeCandidate
from src.rag.compact_api_packet import CompactApiPacket


ENDPOINT_PATTERNS = {
    "gene_editing": r"\b(edit(?:ing|ed)?|insertion|deletion|indel|knockout)\b",
    "expression": (
        r"\b(expression|expressed|fluorescen|luminescen|luciferase|egfp|gfp)\w*"
        r"|\bdeliver(?:ed|y|ies|ing)?\s+(?:the\s+)?mRNA\b"
    ),
    "uptake": r"\b(uptake|internaliz|accumulat|biodistribution)\w*",
    "knockdown": r"\b(knockdown|silenc|reduc(?:e|ed|tion)|sirna)\w*",
    "therapeutic_function": r"\b(activity|efficacy|survival|fibrosis|steatosis|necrosis|protection|therapeutic)\w*",
    "cell_target_effect": (
        r"\b(phagocyt|eliminat|eradicated|killing|colocali[sz]|"
        r"co-stain|cell marker)\w*"
    ),
    "toxicity": r"\b(toxicity|cytotoxic|alt|ast|inflamm|injury)\w*",
}
DIRECT_SIGNAL = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|fold|ng|mg|µg|ug|hours?|days?|weeks?)|"
    r"±|significant|increased|decreased|higher|lower|observed|measured|"
    r"showed|resulted|reached|maintained|compared|versus|vs\.?|assessed|analysis|"
    r"attenuat|eradicated|eliminat|phagocyt|colocali[sz]|locali[sz]|"
    r"\bfew\b|absent|virtually all|solely|co-stain|"
    r"figure\s*\w+|fig\.\s*\w+|table\s*\w+)",
    re.I,
)
EXPLICIT_VALUE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?\s*%?|"
    r"\d+(?:\.\d+)?\s*(?:%|fold|ng|mg|µg|ug|hours?|days?|weeks?))",
    re.I,
)
OUTCOME_VALUE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?\s*%?|"
    r"\d+(?:\.\d+)?\s*(?:%|fold))",
    re.I,
)
VISUAL_REFERENCE = re.compile(
    r"\b((?:supplementary\s+)?(?:table|figure|fig\.)\s*[A-Za-z0-9.-]+)",
    re.I,
)
ENDPOINT_SIGNATURES = {
    "insertion": r"\binsertion\w*",
    "deletion": r"\bdeletion\w*",
    "indel": r"\bindel\w*",
    "fviii_activity": r"\b(?:fviii|factor\s+viii).{0,30}\bactivity\b|\bactivity.{0,30}(?:fviii|factor\s+viii)\b",
    "luciferase": r"\bluciferase|luminescen",
    "egfp_gfp": r"\b(?:e?gfp|green fluorescent protein)\b",
    "uptake": r"\buptake|internaliz",
    "fibrosis": r"\bfibrosis|collagen|sirius red",
    "alt_ast": r"\b(?:alt|ast)\b",
    "knockdown": r"\bknockdown|silenc",
    "cell_target_effect": r"\bphagocyt|eliminat|eradicated|killing|colocali[sz]|cell marker",
}
SIGNATURE_FAMILY = {
    "insertion": "gene_editing",
    "deletion": "gene_editing",
    "indel": "gene_editing",
    "fviii_activity": "therapeutic_function",
    "luciferase": "expression",
    "egfp_gfp": "expression",
    "uptake": "uptake",
    "fibrosis": "therapeutic_function",
    "alt_ast": "toxicity",
    "knockdown": "knockdown",
    "cell_target_effect": "cell_target_effect",
}
RESULT_SIGNAL = re.compile(
    r"\b(?:increased|decreased|higher|lower|reduced|improved|restored|"
    r"attenuated|eradicated|eliminated|observed|reached|maintained|"
    r"expressed|no obvious|exclusively)\b",
    re.I,
)
INTERVENTION_SIGNAL = re.compile(
    r"\b(?:lnp|lipid nanoparticle|mrna|sirna|sgrna|cas9|fapcar|"
    r"hgf|egf|simicu1)\b",
    re.I,
)
TARGET_CONTEXT_SIGNAL = re.compile(
    r"\b(?:liver|hepatic|hepatocyte|kupffer|lsec|sinusoidal endothelial|"
    r"macrophage|bmdms?|bone marrow-derived macrophages?|"
    r"stellate|hsc|fibrosis|fviii|factor viii|f8|cd11b|cd31|cd45|"
    r"f4/80|lyve-?1|js-?1|lx-?2|target cells?)\b",
    re.I,
)
QUANTITATIVE_BIOLOGICAL_RESULT = re.compile(
    r"(?:"
    r"\b(?:over|under|more than|less than|fewer than|approximately|about)?\s*"
    r"\d+(?:\.\d+)?\s*%.{0,100}"
    r"\b(?:express|transfect|deliver|edit|insert|delete|indel|activity|uptake|"
    r"knockdown|silenc|surviv|efficacy|bmdm|macrophage|hepatocyte)\w*"
    r"|"
    r"\b(?:express|transfect|deliver|edit|insert|delete|indel|activity|uptake|"
    r"knockdown|silenc|surviv|efficacy|bmdm|macrophage|hepatocyte)\w*"
    r".{0,100}\b(?:over|under|more than|less than|fewer than|"
    r"approximately|about)?\s*\d+(?:\.\d+)?\s*%"
    r")",
    re.I,
)
VISUAL_OUTCOME_SIGNAL = re.compile(
    r"\b(?:shown|displayed|results?|frequency|percentage|ratio|activity|"
    r"efficacy|editing|expression|uptake|knockdown)\b",
    re.I,
)
METHOD_ONLY = re.compile(
    r"\b(?:(?:was|were)\s+(?:used|performed|conducted|measured|assessed|analyzed)|"
    r"plated|seeded|incubated|prepared|protocol|determination|formula)\b",
    re.I,
)


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _candidate_id(paper_id: str, key: tuple[str, ...]) -> str:
    digest = hashlib.sha256(_canonical([paper_id, *key]).encode()).hexdigest()[:16]
    return f"OC-{digest}"


def _location(source: dict) -> str | None:
    return (
        source.get("table_number")
        or source.get("figure_number")
        or source.get("supplement_identifier")
    )


def _text_visual_for_signature(text: str, signature: str) -> str:
    labels = [match.group(1) for match in VISUAL_REFERENCE.finditer(text)]
    if not labels:
        return ""
    preferred_suffix = {
        "insertion": "s2",
        "deletion": "s1",
    }.get(signature)
    if preferred_suffix:
        preferred = next(
            (
                label
                for label in labels
                if re.sub(r"[^a-z0-9]", "", label.lower()).endswith(
                    preferred_suffix
                )
            ),
            None,
        )
        if preferred:
            return preferred
    return labels[0]


def build_candidates(packet: CompactApiPacket) -> list[OutcomeCandidate]:
    sources = {
        row.source_id: row.model_dump(mode="json", exclude_none=True)
        for row in packet.sources
    }
    grouped: dict[tuple[str, str, str, str], list] = defaultdict(list)
    for evidence in packet.evidence:
        if not DIRECT_SIGNAL.search(evidence.text):
            continue
        if METHOD_ONLY.search(evidence.text) and not (
            OUTCOME_VALUE.search(evidence.text) or RESULT_SIGNAL.search(evidence.text)
        ):
            continue
        families = [
            name
            for name, pattern in ENDPOINT_PATTERNS.items()
            if re.search(pattern, evidence.text, re.I)
        ]
        if not families:
            continue
        outcome_tagged = "outcomes" in evidence.retrieval_field_tags
        quantitative_biological_outcome = bool(
            QUANTITATIVE_BIOLOGICAL_RESULT.search(evidence.text)
            and TARGET_CONTEXT_SIGNAL.search(evidence.text)
        )
        qualitative_biological_outcome = bool(
            TARGET_CONTEXT_SIGNAL.search(evidence.text)
            and re.search(
                r"\b(?:absent|few|virtually all|solely|locali[sz]|colocali[sz]|"
                r"co-stain|express|phagocyt|eliminat|eradicated|improved|"
                r"reduced|increased|decreased)\w*",
                evidence.text,
                re.I,
            )
        )
        if (
            not outcome_tagged
            and not quantitative_biological_outcome
            and not qualitative_biological_outcome
        ):
            continue
        for source_id in evidence.source_ids:
            source = sources.get(source_id, {})
            section = str(source.get("section") or "").lower()
            if section in {"introduction", "background"}:
                continue
            signatures = [
                name
                for name, pattern in ENDPOINT_SIGNATURES.items()
                if re.search(pattern, evidence.text, re.I)
            ] or ["general"]
            for signature in signatures:
                visual = _location(source) or _text_visual_for_signature(
                    evidence.text, signature
                )
                family = SIGNATURE_FAMILY.get(signature)
                if family not in families:
                    family = families[0]
                # Source identity prevents unrelated result passages that merely
                # share a broad endpoint family from becoming one repair target.
                grouped[
                    (family, signature, visual.lower(), source_id)
                ].append(evidence)

    candidates: list[OutcomeCandidate] = []
    for key, rows in sorted(grouped.items()):
        family, _, key_visual, _ = key
        evidence_ids = list(dict.fromkeys(row.evidence_id for row in rows))
        source_ids = list(
            dict.fromkeys(source_id for row in rows for source_id in row.source_ids)
        )
        text = " ".join(dict.fromkeys(row.text.strip() for row in rows))
        visual_matches = [
            match.group(1) for match in VISUAL_REFERENCE.finditer(text)
        ]
        visual = key_visual or (visual_matches[0] if visual_matches else "")
        route_hint = (
            "vision" if visual and not EXPLICIT_VALUE.search(text) else "text"
        )
        confidence_reasons = []
        relevant_context = bool(
            TARGET_CONTEXT_SIGNAL.search(text)
            or family in {"gene_editing", "therapeutic_function"}
        )
        if QUANTITATIVE_BIOLOGICAL_RESULT.search(text) and relevant_context:
            confidence_reasons.append("explicit_numeric_result")
        if (
            RESULT_SIGNAL.search(text)
            and INTERVENTION_SIGNAL.search(text)
            and relevant_context
        ):
            confidence_reasons.append("explicit_result_language")
        if (
            route_hint == "vision"
            and VISUAL_OUTCOME_SIGNAL.search(text)
            and (
                INTERVENTION_SIGNAL.search(text)
                or family == "gene_editing"
            )
            and relevant_context
        ):
            confidence_reasons.append("visual_result_location")
        confidence = (
            "high"
            if "explicit_numeric_result" in confidence_reasons
            or "explicit_result_language" in confidence_reasons
            or "visual_result_location" in confidence_reasons
            else "medium"
        )
        signals = list(dict.fromkeys(match.group(0) for match in DIRECT_SIGNAL.finditer(text)))
        candidates.append(
            OutcomeCandidate(
                candidate_id=_candidate_id(packet.paper_id, key),
                paper_id=packet.paper_id,
                endpoint_family=family,
                evidence_ids=evidence_ids,
                source_ids=source_ids,
                evidence_text=text,
                direct_signal_terms=signals[:12],
                figure_or_table=visual or None,
                route_hint=route_hint,
                confidence=confidence,
                confidence_reasons=confidence_reasons,
            )
        )
    return candidates


def load_packet(path: Path) -> CompactApiPacket:
    return CompactApiPacket.model_validate_json(path.read_text(encoding="utf-8"))
