"""Combine validity and completeness findings into one mandatory route plan."""

from __future__ import annotations

import hashlib
import re

from src.extraction.compact_routing_contracts import (
    CompactRoutingDecision,
    RouteItem,
)
from src.extraction.compact_validation import ValidationReport
from src.extraction.outcome_coverage_contracts import CoverageReport
from src.extraction.outcome_inventory_contracts import OutcomeInventory


VISUAL = re.compile(r"\b(?:table|fig(?:ure)?|panel|graph)\b", re.I)


def _route_id(paper_id: str, source: str, source_id: str) -> str:
    digest = hashlib.sha256(
        f"{paper_id}:{source}:{source_id}".encode()
    ).hexdigest()[:16]
    return f"RT-{digest}"


def route(
    *,
    paper_id: str,
    complexity_route: str,
    validation: ValidationReport,
    coverage: CoverageReport | None,
    inventory: OutcomeInventory | None,
) -> CompactRoutingDecision:
    routes: list[RouteItem] = []
    for finding in validation.findings:
        if not finding.repairable:
            routes.append(
                RouteItem(
                    route_id=_route_id(
                        paper_id, "ordinary_validation", finding.finding_id
                    ),
                    source="ordinary_validation",
                    source_id=finding.finding_id,
                    route="first_call_required",
                    reason=(
                        "Whole-response/schema failure cannot be repaired as one field; "
                        "a schema-current first extraction is required."
                    ),
                    evidence_ids=finding.cited_evidence_ids,
                )
            )
            continue
        visual = VISUAL.search(" ".join([finding.code, finding.message]))
        selected_route = (
            "selective_vision"
            if visual
            else "narrow_field_repair"
        )
        routes.append(
            RouteItem(
                route_id=_route_id(
                    paper_id, "ordinary_validation", finding.finding_id
                ),
                source="ordinary_validation",
                source_id=finding.finding_id,
                route=selected_route,
                reason=(
                    "Invalid returned field requires visual resolution."
                    if visual
                    else "Invalid returned field requires bounded text repair."
                ),
                evidence_ids=finding.cited_evidence_ids,
            )
        )
    if coverage:
        for candidate in coverage.unmatched_candidates:
            selected_route = (
                "selective_vision"
                if candidate.route_hint == "vision"
                else "missing_record_text"
            )
            routes.append(
                RouteItem(
                    route_id=_route_id(
                        paper_id, "outcome_coverage", candidate.candidate_id
                    ),
                    source="outcome_coverage",
                    source_id=candidate.candidate_id,
                    route=selected_route,
                    reason=(
                        "Credible outcome candidate has no one-to-one extracted record."
                    ),
                    evidence_ids=candidate.evidence_ids,
                )
            )
        for candidate in coverage.review_candidates:
            routes.append(
                RouteItem(
                    route_id=_route_id(
                        paper_id, "outcome_coverage", candidate.candidate_id
                    ),
                    source="outcome_coverage",
                    source_id=candidate.candidate_id,
                    route="human_review",
                    reason=candidate.reason,
                    evidence_ids=candidate.evidence_ids,
                )
            )
    if inventory:
        already_routed = {row.source_id for row in routes}
        for disposition in inventory.unresolved_dispositions:
            if disposition.candidate_id in already_routed:
                continue
            candidate = next(
                row
                for row in inventory.retained_candidates
                if row.candidate_id == disposition.candidate_id
            )
            routes.append(
                RouteItem(
                    route_id=_route_id(
                        paper_id, "inventory", disposition.candidate_id
                    ),
                    source="inventory",
                    source_id=disposition.candidate_id,
                    route="human_review",
                    reason=disposition.reason,
                    evidence_ids=candidate.evidence_ids,
                )
            )
    blockers = []
    if validation.status != "valid":
        blockers.append("ordinary_validation_invalid")
    if complexity_route == "complex" and (
        coverage is None
        or coverage.status not in {"complete", "not_applicable"}
    ):
        blockers.append("complex_outcome_coverage_incomplete")
    if any(row.route == "human_review" for row in routes):
        blockers.append("candidate_adjudication_incomplete")
    if any(
        row.route
        in {
            "narrow_field_repair",
            "first_call_required",
            "missing_record_text",
            "selective_vision",
        }
        for row in routes
    ):
        blockers.append("repair_or_vision_routes_pending")
    return CompactRoutingDecision(
        routing_version="compact-routing-1.0.0",
        paper_id=paper_id,
        complexity_route=complexity_route,
        ordinary_validation_status=validation.status,
        coverage_status=coverage.status if coverage else None,
        routes=routes,
        finalization_allowed=not blockers,
        finalization_blockers=list(dict.fromkeys(blockers)),
    )
