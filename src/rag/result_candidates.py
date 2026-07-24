"""Deterministic result-candidate splitting and completeness validation."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from src.extraction.contracts_v4 import EvidenceGraphV4, SourceClauseV4
from src.extraction.outcome_contracts_v41 import (
    CandidateDispositionV41,
    OutcomeSidecarV41,
    ResultCandidateV41,
)


NUMERIC_VALUE = re.compile(
    r"(?:approximately\s+|about\s+|over\s+|fewer than\s+|less than\s+)?"
    r"\d+(?:\.\d+)?(?:\s*[±+/-]\s*\d+(?:\.\d+)?)?\s*(?:%|percent|fold)",
    re.I,
)
RESULT_CUE = re.compile(
    r"\b(express|detect|observ|show|found|result|increase|decrease|reduce|"
    r"improv|ameliorat|eliminat|phagocyt|colocali[sz]|uptake|translation|"
    r"knockdown|activity|frequency)\w*",
    re.I,
)
NEGATIVE = re.compile(
    r"\b(no|not|none|without|absent|solely|few|fewer than|less than|"
    r"below|undetect|exclusive(?:ly)?|did not|was not|were not)\b",
    re.I,
)
BELOW_DETECTION = re.compile(r"\b(no obvious|no detectable|undetect|below detection)\b", re.I)
COMPARISON = re.compile(r"\b(compared with|versus|vs\.?|than|in contrast)\b", re.I)
POPULATION_PATTERNS = [
    re.compile(r"\b(?:CD11b|CD45|CD31|F4/80|LYVE-?1|HNF4α|Desmin|ALB)\+?\s*(?:positive\s*)?cells?\b", re.I),
    re.compile(r"\b(?:Kupffer cells?|hepatocytes?|LSECs?|HSCs?|BMDMs?|macrophages?|JS-1 cells?|LX-2 cells?)\b", re.I),
]
SPLIT_RESULT = re.compile(r"\s*(?:;|\bwhile\b|\bwhereas\b|\bin contrast\b)\s*", re.I)


def _candidate_id(clause_id: str, index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"RC-{clause_id}-{index:02d}-{digest}"


def _population(text: str) -> str | None:
    matches = [
        match.group(0)
        for pattern in POPULATION_PATTERNS
        for match in pattern.finditer(text)
    ]
    return matches[-1] if matches else None


def _qualitative_value(text: str) -> str:
    lowered = text.lower()
    for phrase in (
        "no obvious", "no detectable", "few", "solely", "exclusively", "exclusive", "absent",
        "significantly eliminated", "eliminated", "colocalized",
        "significantly reduced", "significantly increased",
        "improved", "ameliorated",
    ):
        if phrase in lowered:
            return phrase
    return text.strip()


def split_result_candidates(clauses: list[SourceClauseV4]) -> list[ResultCandidateV41]:
    candidates: list[ResultCandidateV41] = []
    for clause in clauses:
        if not RESULT_CUE.search(clause.text) and not NUMERIC_VALUE.search(clause.text):
            continue
        segments = [value.strip(" ,.") for value in SPLIT_RESULT.split(clause.text) if value.strip()]
        for segment_number, segment in enumerate(segments, 1):
            numeric_values = [match.group(0) for match in NUMERIC_VALUE.finditer(segment)]
            values = numeric_values or ([_qualitative_value(segment)] if RESULT_CUE.search(segment) else [])
            for value_number, value in enumerate(values, 1):
                polarity = "negative" if NEGATIVE.search(segment) else "positive"
                detection = (
                    "below_detection" if BELOW_DETECTION.search(segment)
                    else "not_detected" if re.search(r"\b(no|none|absent|did not)\b", segment, re.I)
                    else "detected"
                )
                value_type = (
                    "numeric" if numeric_values
                    else "comparative" if COMPARISON.search(segment)
                    else "qualitative"
                )
                candidate_index = len(candidates) + 1
                candidates.append(ResultCandidateV41(
                    candidate_id=_candidate_id(clause.clause_id, candidate_index, segment + value),
                    clause_id=clause.clause_id,
                    raw_text=segment,
                    population=_population(segment),
                    endpoint_hint=RESULT_CUE.search(segment).group(0) if RESULT_CUE.search(segment) else None,
                    value_text=value,
                    value_type=value_type,
                    polarity=polarity,
                    detection_status=detection,
                    comparison=COMPARISON.search(segment).group(0) if COMPARISON.search(segment) else None,
                    evidence=[{"clause_id": clause.clause_id, "quote": clause.text}],
                ))
    return candidates


def validate_candidate_cardinality(
    clauses: list[SourceClauseV4],
    candidates: list[ResultCandidateV41],
) -> list[dict[str, str]]:
    """Ensure every explicit numerical result has its own candidate."""
    by_clause = Counter(row.clause_id for row in candidates if row.value_type == "numeric")
    findings = []
    for clause in clauses:
        expected = len(NUMERIC_VALUE.findall(clause.text))
        if expected and by_clause[clause.clause_id] < expected:
            findings.append({
                "owner": clause.clause_id,
                "issue": "result_candidate_cardinality_mismatch",
                "detail": f"expected {expected} numeric candidates, found {by_clause[clause.clause_id]}",
            })
    return findings


def validate_sidecar_against_graph(
    sidecar: OutcomeSidecarV41,
    graph: EvidenceGraphV4,
) -> list[dict[str, str]]:
    claims = {row.claim_id: row for row in graph.claims}
    findings = []
    for disposition in sidecar.dispositions:
        if disposition.status != "retained":
            continue
        claim = claims.get(disposition.claim_id or "")
        if claim is None:
            findings.append({
                "owner": disposition.candidate_id,
                "issue": "retained_candidate_missing_claim",
                "detail": f"claim {disposition.claim_id!r} does not exist",
            })
        elif claim.predicate != "has_outcome_value":
            findings.append({
                "owner": disposition.candidate_id,
                "issue": "retained_candidate_wrong_predicate",
                "detail": f"claim {claim.claim_id} uses {claim.predicate}",
            })
    return findings


def pending_sidecar(paper_id: str, clauses: list[SourceClauseV4]) -> OutcomeSidecarV41:
    candidates = split_result_candidates(clauses)
    return OutcomeSidecarV41(
        paper_id=paper_id,
        candidates=candidates,
        dispositions=[
            CandidateDispositionV41(
                candidate_id=row.candidate_id,
                status="ambiguous",
                reason="Pending extractor/verifier disposition.",
            )
            for row in candidates
        ],
    )
