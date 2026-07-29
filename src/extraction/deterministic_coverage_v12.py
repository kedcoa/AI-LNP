"""Deterministic, fact-level coverage checks for v1.2 outcome candidates.

This module does not accept model-authored coverage labels.  It independently
joins extracted experiments to provisional experiments, compares atomic facts,
and derives a route.  Contradictions are never sent to the additive
missing-record repair path.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Literal

from src.extraction.build_provisional_experiments import (
    CELL_PATTERNS,
    _payload_signature,
)
from src.extraction.check_atomic_coverage_v12 import PREDICATE_SIGNALS
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


FieldResult = Literal[
    "exact_or_synonym_match",
    "contradiction",
    "unconfirmed",
    "not_applicable",
]
Verdict = Literal["confirmed", "contradicted", "unconfirmed"]
Route = Literal["none", "bounded_repair_task", "human_review"]

SPECULATIVE = re.compile(
    r"\b(?:could|may|might|would|potential(?:ly)?|hypothesi[sz]|"
    r"propos(?:e|ed)|expect(?:ed)?|suggesting that)\b",
    re.I,
)
METHOD_ONLY = re.compile(
    r"\b(?:to (?:identify|evaluate|assess|determine)|we performed|"
    r"(?:was|were) (?:analy[sz]ed|assessed|measured|determined)|"
    r"(?:quantified|measured) by|representative images?)\b",
    re.I,
)
CITATION_FRAGMENT = re.compile(
    r"(?:^|[\s(])(?:supplementary\s+)?fig(?:ure)?\.?\s*$",
    re.I,
)
MALFORMED_SUBJECT = re.compile(
    r"^(?:a|an|the)?\s*(?:pronounced|marked|obvious|significant(?:ly)?)\s*$",
    re.I,
)
DIRECT_RESULT = re.compile(
    r"\b(?:few|absent|no obvious|virtually all|solely|exclusively|"
    r"higher|lower|increased|decreased|reduced|significant(?:ly)?|"
    r"observed|showed|found|expressed|localized|colocali[sz]ed|"
    r"reached|maintained|sustained|recognized|phagocytosed|eliminated|"
    r"obvious|pronounced)\b",
    re.I,
)
NEGATED_RESULT = re.compile(
    r"\b(?:no|not|none|absent|without|undetectable|no obvious|"
    r"below (?:visual )?detection)\b",
    re.I,
)
PARENCHYMAL_HEPATOCYTE = re.compile(
    r"\b(?:liver parenchymal cells?|parenchyma of the liver)\b",
    re.I,
)
BROAD_LIVER_CELL = re.compile(r"\b(?:hepatic cells?|liver cells?)\b", re.I)
BROAD_ENDOTHELIAL = re.compile(r"\bendothelial cells?\b", re.I)
BROAD_HEMATOPOIETIC = re.compile(r"\bhematopoietic cells?\b", re.I)

ENDPOINT_PATTERNS = {
    "expression": re.compile(
        r"\b(?:express(?:ed|ion|ing)?|reporter|e?GFP|luciferase)\b",
        re.I,
    ),
    "uptake": re.compile(r"\b(?:uptake|internaliz(?:ed|ation))\b", re.I),
    "insertion": re.compile(r"\binsertion(?: frequency)?\b", re.I),
    "deletion": re.compile(r"\bdeletion(?: frequency)?\b", re.I),
    "editing": re.compile(r"\b(?:gene edit(?:ing|ed)|indel)\b", re.I),
    "activity": re.compile(r"\b(?:activity|aPTT|FVIII|factor VIII)\b", re.I),
    "colocalization": re.compile(r"\bco-?locali[sz]\w*\b", re.I),
    "localization": re.compile(r"\blocali[sz]\w*\b", re.I),
    "phagocytosis": re.compile(r"\bphagocyt\w*\b", re.I),
    "elimination": re.compile(
        r"\b(?:eliminat\w*|eradicate\w*|killing|cytotoxic\w*)\b",
        re.I,
    ),
    "fibrosis": re.compile(r"\bfibros\w*\b", re.I),
    "steatosis": re.compile(r"\b(?:steatosis|lipid accumulation)\b", re.I),
    "alt": re.compile(r"\b(?:ALT|alanine aminotransferase)\b", re.I),
    "damage": re.compile(
        r"\b(?:damage|defenestration|calcium accumulation)\b",
        re.I,
    ),
}


def _value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _reported_text(record: dict[str, Any], *fields: str) -> str:
    return " ".join(
        str(value)
        for field in fields
        if (value := _value(record.get(field))) is not None
    )


def _nested_evidence_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value.get("evidence_ids", []))
        for child in value.values():
            found |= _nested_evidence_ids(child)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found |= _nested_evidence_ids(child)
        return found
    return set()


def _candidate_text(candidate: AtomicOutcomeCandidateV12) -> str:
    return " ".join(
        str(value)
        for value in (
            candidate.subject_text,
            candidate.predicate,
            candidate.object_text,
            candidate.endpoint_text,
            candidate.qualitative_result,
            candidate.value_text,
        )
        if value is not None
    )


def assess_candidate_eligibility(
    candidate: AtomicOutcomeCandidateV12,
) -> dict[str, Any]:
    """Fail noisy or interpretive candidates closed to human review."""

    text = _candidate_text(candidate)
    asserted_text = " ".join(
        str(value)
        for value in (
            candidate.subject_text,
            candidate.object_text,
            candidate.endpoint_text,
            candidate.qualitative_result,
            candidate.value_text,
        )
        if value is not None
    )
    reasons: list[str] = []
    if candidate.confidence != "high":
        reasons.append("candidate_not_high_confidence")
    if candidate.provisional_experiment_id is None:
        reasons.append("missing_provisional_experiment")
    if candidate.review_reasons:
        reasons.append("candidate_has_review_reasons")
    if SPECULATIVE.search(text):
        reasons.append("speculative_or_interpretive_language")
    if MALFORMED_SUBJECT.search(candidate.subject_text.strip()):
        reasons.append("malformed_candidate_subject")
    if any(
        CITATION_FRAGMENT.search(str(value).strip())
        for value in (
            candidate.object_text,
            candidate.endpoint_text,
            candidate.qualitative_result,
            candidate.value_text,
        )
        if value
    ):
        reasons.append("dangling_figure_citation_fragment")
    if (
        METHOD_ONLY.search(asserted_text)
        and candidate.numeric_value is None
        and not DIRECT_RESULT.search(asserted_text)
    ):
        reasons.append("method_without_direct_result")
    return {
        "eligible": not reasons,
        "reasons": reasons,
    }


def _canonical_cells(text: str) -> set[str]:
    cells = {
        value
        for value, pattern in CELL_PATTERNS.items()
        if pattern.search(text)
    }
    if PARENCHYMAL_HEPATOCYTE.search(text):
        cells.add("hepatocyte")
    if BROAD_LIVER_CELL.search(text):
        cells.add("liver_unspecified")
    if BROAD_ENDOTHELIAL.search(text) and "lsec" not in cells:
        cells.add("endothelial_unspecified")
    if BROAD_HEMATOPOIETIC.search(text):
        cells.add("hematopoietic_unspecified")
    return cells


def _endpoint_keys(text: str) -> set[str]:
    return {
        key for key, pattern in ENDPOINT_PATTERNS.items() if pattern.search(text)
    }


def _predicate_compatible(predicate: str, output_text: str) -> bool:
    return bool(re.search(PREDICATE_SIGNALS[predicate], output_text, re.I))


def _field(
    name: str,
    result: FieldResult,
    *,
    expected: Any = None,
    observed: Any = None,
    reason: str,
) -> dict[str, Any]:
    return {
        "field_name": name,
        "result": result,
        "expected": expected,
        "observed": observed,
        "reason": reason,
    }


def _anchor_values(experiment: dict[str, Any], anchor_type: str) -> set[str]:
    return {
        str(anchor["value"])
        for anchor in experiment.get("anchors", [])
        if anchor.get("anchor_type") == anchor_type and anchor.get("value")
    }


def _output_payloads(experiment: dict[str, Any]) -> set[str]:
    text = _reported_text(
        experiment,
        "payload_type",
        "payload_name",
        "encoded_product",
        "molecular_target",
    )
    signature = _payload_signature(text)
    return {signature} if signature else set()


def _output_models(experiment: dict[str, Any]) -> set[str]:
    context = _value(experiment.get("experimental_context"))
    return {str(context)} if context else set()


def associate_output_experiments(
    provisional_experiments: list[dict[str, Any]],
    output_experiments: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Independently associate outputs; zero or multiple joins fail closed."""

    associations: dict[str, dict[str, Any]] = {}
    for output in output_experiments:
        output_id = str(output.get("experiment_id", ""))
        output_payloads = _output_payloads(output)
        output_models = _output_models(output)
        compatible: list[str] = []
        diagnostics: dict[str, list[str]] = {}
        for provisional in provisional_experiments:
            provisional_id = provisional["provisional_experiment_id"]
            expected_payloads = _anchor_values(provisional, "payload")
            expected_models = _anchor_values(provisional, "model")
            reasons: list[str] = []
            if not expected_payloads or not output_payloads:
                reasons.append("payload_unconfirmed")
            elif expected_payloads.isdisjoint(output_payloads):
                reasons.append("payload_contradiction")
            else:
                reasons.append("payload_match")
            if expected_models and output_models:
                if expected_models.isdisjoint(output_models):
                    reasons.append("model_contradiction")
                else:
                    reasons.append("model_match")
            elif expected_models:
                reasons.append("model_unconfirmed")
            diagnostics[provisional_id] = reasons
            if (
                "payload_match" in reasons
                and "payload_contradiction" not in reasons
                and "model_contradiction" not in reasons
                and "model_unconfirmed" not in reasons
            ):
                compatible.append(provisional_id)
        associations[output_id] = {
            "status": (
                "associated"
                if len(compatible) == 1
                else ("ambiguous" if compatible else "unconfirmed")
            ),
            "provisional_experiment_id": (
                compatible[0] if len(compatible) == 1 else None
            ),
            "compatible_provisional_experiment_ids": compatible,
            "diagnostics": diagnostics,
        }
    return associations


def _cell_check(
    candidate: AtomicOutcomeCandidateV12,
    outcome: dict[str, Any],
    experiment: dict[str, Any],
) -> dict[str, Any]:
    expected = _canonical_cells(_candidate_text(candidate))
    outcome_text = _reported_text(
        outcome, "assay", "endpoint", "qualitative_outcome"
    )
    observed = _canonical_cells(outcome_text)
    if not observed:
        observed = _canonical_cells(
            _reported_text(
                experiment,
                "delivery_recipient_cell",
                "therapeutic_target_cell",
            )
        )
    if not expected:
        return _field(
            "cell_population",
            "not_applicable",
            expected=[],
            observed=sorted(observed),
            reason="candidate_does_not_assert_a_cell_population",
        )
    if not observed:
        return _field(
            "cell_population",
            "unconfirmed",
            expected=sorted(expected),
            observed=[],
            reason="output_does_not_report_a_confirming_cell_population",
        )
    if expected == observed:
        return _field(
            "cell_population",
            "exact_or_synonym_match",
            expected=sorted(expected),
            observed=sorted(observed),
            reason="canonical_cell_sets_match",
        )
    return _field(
        "cell_population",
        "contradiction",
        expected=sorted(expected),
        observed=sorted(observed),
        reason="canonical_cell_sets_differ_or_output_is_broader",
    )


def _relationship_check(
    candidate: AtomicOutcomeCandidateV12,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    output_text = _reported_text(outcome, "endpoint", "qualitative_outcome")
    expected_endpoints = _endpoint_keys(_candidate_text(candidate))
    observed_endpoints = _endpoint_keys(output_text)
    if not _predicate_compatible(candidate.predicate, output_text):
        return _field(
            "endpoint_relationship",
            "contradiction" if output_text else "unconfirmed",
            expected={
                "predicate": candidate.predicate,
                "endpoint_keys": sorted(expected_endpoints),
            },
            observed={"endpoint_keys": sorted(observed_endpoints)},
            reason="output_does_not_assert_the_candidate_relationship",
        )
    if expected_endpoints and not observed_endpoints:
        return _field(
            "endpoint_relationship",
            "unconfirmed",
            expected=sorted(expected_endpoints),
            observed=[],
            reason="output_endpoint_is_missing_or_too_vague",
        )
    if expected_endpoints and expected_endpoints != observed_endpoints:
        return _field(
            "endpoint_relationship",
            "contradiction",
            expected=sorted(expected_endpoints),
            observed=sorted(observed_endpoints),
            reason="endpoint_families_differ_or_output_is_broader",
        )
    return _field(
        "endpoint_relationship",
        "exact_or_synonym_match",
        expected={
            "predicate": candidate.predicate,
            "endpoint_keys": sorted(expected_endpoints),
        },
        observed={"endpoint_keys": sorted(observed_endpoints)},
        reason="predicate_and_endpoint_are_compatible",
    )


def _polarity_check(
    candidate: AtomicOutcomeCandidateV12,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    output_text = _reported_text(outcome, "endpoint", "qualitative_outcome")
    observed = "negative" if NEGATED_RESULT.search(output_text) else "positive"
    if not output_text:
        return _field(
            "polarity",
            "unconfirmed",
            expected=candidate.polarity,
            observed=None,
            reason="output_has_no_text_from_which_to_confirm_polarity",
        )
    if candidate.polarity == "neutral":
        return _field(
            "polarity",
            "unconfirmed",
            expected="neutral",
            observed=observed,
            reason="neutral_candidate_polarity_requires_review",
        )
    return _field(
        "polarity",
        (
            "exact_or_synonym_match"
            if candidate.polarity == observed
            else "contradiction"
        ),
        expected=candidate.polarity,
        observed=observed,
        reason=(
            "assertion_polarity_matches"
            if candidate.polarity == observed
            else "assertion_polarity_differs"
        ),
    )


def _normalized_unit(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return {
        "%": "percent",
        "percentage": "percent",
        "percent": "percent",
        "fold": "fold",
    }.get(normalized, normalized)


def _rounding_tolerance(observed: float) -> float:
    if math.isclose(observed, round(observed), abs_tol=1e-12):
        return 0.5
    decimals = max(0, len(f"{observed:.12f}".rstrip("0").split(".")[-1]))
    return max(0.011, 0.5 * 10 ** (-decimals))


def _numeric_check(
    candidate: AtomicOutcomeCandidateV12,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    expected = candidate.numeric_value
    if expected is None:
        return _field(
            "numeric_value_unit",
            "not_applicable",
            reason="candidate_has_no_numeric_value",
        )
    observed = _value(outcome.get("outcome_value"))
    observed_unit = _value(outcome.get("outcome_unit"))
    if not isinstance(observed, (int, float)):
        return _field(
            "numeric_value_unit",
            "unconfirmed",
            expected={"value": expected, "unit": candidate.unit},
            observed={"value": observed, "unit": observed_unit},
            reason="output_numeric_value_is_missing",
        )
    expected_unit = _normalized_unit(candidate.unit)
    normalized_observed_unit = _normalized_unit(
        str(observed_unit) if observed_unit is not None else None
    )
    if expected_unit and normalized_observed_unit != expected_unit:
        return _field(
            "numeric_value_unit",
            "contradiction" if normalized_observed_unit else "unconfirmed",
            expected={"value": expected, "unit": expected_unit},
            observed={"value": observed, "unit": normalized_observed_unit},
            reason="numeric_units_do_not_match",
        )
    tolerance = _rounding_tolerance(float(observed))
    if abs(float(expected) - float(observed)) > tolerance:
        return _field(
            "numeric_value_unit",
            "contradiction",
            expected={"value": expected, "unit": expected_unit},
            observed={"value": observed, "unit": normalized_observed_unit},
            reason=f"numeric_values_differ_beyond_rounding_tolerance:{tolerance:g}",
        )
    return _field(
        "numeric_value_unit",
        "exact_or_synonym_match",
        expected={"value": expected, "unit": expected_unit},
        observed={"value": observed, "unit": normalized_observed_unit},
        reason=f"numeric_values_agree_within_rounding_tolerance:{tolerance:g}",
    )


def compare_candidate_to_output(
    candidate: AtomicOutcomeCandidateV12,
    outcome: dict[str, Any],
    experiment: dict[str, Any],
    association: dict[str, Any],
) -> dict[str, Any]:
    """Compare one candidate/output pair with mandatory, non-additive gates."""

    candidate_experiment = candidate.provisional_experiment_id
    associated_experiment = association.get("provisional_experiment_id")
    if association.get("status") != "associated":
        intervention = _field(
            "intervention",
            "unconfirmed",
            expected=candidate_experiment,
            observed=associated_experiment,
            reason="output_experiment_has_no_unambiguous_provisional_join",
        )
    elif associated_experiment != candidate_experiment:
        intervention = _field(
            "intervention",
            "contradiction",
            expected=candidate_experiment,
            observed=associated_experiment,
            reason="output_is_associated_with_a_different_experiment",
        )
    else:
        intervention = _field(
            "intervention",
            "exact_or_synonym_match",
            expected=candidate_experiment,
            observed=associated_experiment,
            reason="independently_computed_experiment_association_matches",
        )

    candidate_evidence = set(candidate.evidence_ids)
    output_evidence = _nested_evidence_ids(outcome)
    evidence_overlap = bool(candidate_evidence & output_evidence)
    checks = [
        intervention,
        _cell_check(candidate, outcome, experiment),
        _relationship_check(candidate, outcome),
        _field(
            "comparator",
            "not_applicable",
            reason="candidate_comparator_is_not_structured_yet",
        ),
        _field(
            "timepoint",
            "not_applicable",
            reason="candidate_timepoint_is_not_claim_scoped_yet",
        ),
        _polarity_check(candidate, outcome),
        _numeric_check(candidate, outcome),
    ]
    identity_fields = {
        "intervention",
        "cell_population",
        "endpoint_relationship",
    }
    identity_confirmed = all(
        row["result"] in {"exact_or_synonym_match", "not_applicable"}
        for row in checks
        if row["field_name"] in identity_fields
    )
    value_contradiction = any(
        row["result"] == "contradiction"
        for row in checks
        if row["field_name"] in {"polarity", "numeric_value_unit"}
    )
    if evidence_overlap and identity_confirmed and value_contradiction:
        verdict: Verdict = "contradicted"
    elif not evidence_overlap or any(
        row["result"] == "unconfirmed" for row in checks
    ) or any(
        row["result"] == "contradiction"
        for row in checks
        if row["field_name"] in identity_fields
    ):
        verdict = "unconfirmed"
    else:
        verdict = "confirmed"
    return {
        "candidate_id": candidate.candidate_id,
        "output_outcome_id": outcome.get("outcome_id"),
        "output_experiment_id": outcome.get("experiment_id"),
        "evidence_overlap": evidence_overlap,
        "candidate_evidence_ids": sorted(candidate_evidence),
        "output_evidence_ids": sorted(output_evidence),
        "field_checks": checks,
        "verdict": verdict,
    }


def _route(
    *,
    eligibility: dict[str, Any],
    verdict: Verdict,
    candidate: AtomicOutcomeCandidateV12,
) -> Route:
    if not eligibility["eligible"]:
        return "human_review"
    if verdict == "confirmed":
        return "none"
    if verdict == "contradicted":
        return "human_review"
    return (
        "bounded_repair_task"
        if candidate.confidence == "high"
        else "human_review"
    )


def evaluate_structural_coverage(
    *,
    candidates: list[AtomicOutcomeCandidateV12],
    provisional_experiments: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate every candidate and derive deterministic, safe routes."""

    output_experiments = result.get("experiments", [])
    output_outcomes = result.get("outcomes", [])
    experiments_by_id = {
        str(row.get("experiment_id")): row for row in output_experiments
    }
    associations = associate_output_experiments(
        provisional_experiments, output_experiments
    )
    assessments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        for outcome in output_outcomes:
            experiment_id = str(outcome.get("experiment_id", ""))
            experiment = experiments_by_id.get(experiment_id)
            if experiment is None:
                continue
            assessments[candidate.candidate_id].append(
                compare_candidate_to_output(
                    candidate,
                    outcome,
                    experiment,
                    associations.get(
                        experiment_id,
                        {
                            "status": "unconfirmed",
                            "provisional_experiment_id": None,
                        },
                    ),
                )
            )

    candidate_reports = []
    confirmed_outcomes: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        eligibility = assess_candidate_eligibility(candidate)
        rows = assessments.get(candidate.candidate_id, [])
        confirmed = [row for row in rows if row["verdict"] == "confirmed"]
        if len(confirmed) == 1:
            verdict: Verdict = "confirmed"
            selected = confirmed[0]
            confirmed_outcomes[str(selected["output_outcome_id"])].append(
                candidate.candidate_id
            )
            reason = "one_unambiguous_structural_match"
        elif len(confirmed) > 1:
            verdict = "unconfirmed"
            selected = None
            reason = "multiple_structural_matches"
        else:
            contradicted = [
                row for row in rows if row["verdict"] == "contradicted"
            ]
            if contradicted:
                verdict = "contradicted"
                selected = contradicted[0]
                reason = "structural_contradiction"
            else:
                verdict = "unconfirmed"
                selected = rows[0] if rows else None
                reason = (
                    "no_output_experiment_or_outcome"
                    if not rows
                    else "no_confirmed_structural_match"
                )
        candidate_reports.append(
            {
                "candidate_id": candidate.candidate_id,
                "eligibility": eligibility,
                "verdict": verdict,
                "route": _route(
                    eligibility=eligibility,
                    verdict=verdict,
                    candidate=candidate,
                ),
                "reason": reason,
                "selected_assessment": selected,
                "assessments": rows,
            }
        )

    # Atomic candidates require atomic output records.  One output cannot
    # silently confirm several distinct candidates.
    multiply_claimed = {
        outcome_id: candidate_ids
        for outcome_id, candidate_ids in confirmed_outcomes.items()
        if len(candidate_ids) > 1
    }
    if multiply_claimed:
        for report in candidate_reports:
            selected = report["selected_assessment"]
            if (
                selected
                and str(selected["output_outcome_id"]) in multiply_claimed
            ):
                report["verdict"] = "unconfirmed"
                report["route"] = (
                    "bounded_repair_task"
                    if report["eligibility"]["eligible"]
                    else "human_review"
                )
                report["reason"] = "one_broad_output_matches_multiple_candidates"

    counts = {
        verdict: sum(
            report["verdict"] == verdict for report in candidate_reports
        )
        for verdict in ("confirmed", "contradicted", "unconfirmed")
    }
    routes = {
        route: sum(report["route"] == route for report in candidate_reports)
        for route in ("none", "bounded_repair_task", "human_review")
    }
    return {
        "coverage_version": "deterministic-structural-coverage-1.2.0",
        "experiment_associations": associations,
        "candidates": candidate_reports,
        "counts": counts,
        "routes": routes,
        "integration_blocked": bool(
            routes["bounded_repair_task"] or routes["human_review"]
        ),
        "paid_api_requests": 0,
    }
