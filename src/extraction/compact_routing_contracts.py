"""Contracts for one authoritative compact extraction routing decision."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteItem(StrictModel):
    route_id: str
    source: Literal["ordinary_validation", "outcome_coverage", "inventory"]
    source_id: str
    route: Literal[
        "narrow_field_repair",
        "first_call_required",
        "missing_record_text",
        "selective_vision",
        "human_review",
    ]
    reason: str
    evidence_ids: list[str]


class CompactRoutingDecision(StrictModel):
    routing_version: Literal["compact-routing-1.0.0"]
    paper_id: str
    complexity_route: Literal["simple", "complex"]
    ordinary_validation_status: Literal["valid", "invalid"]
    coverage_status: (
        Literal["complete", "review_unmatched_groups", "not_applicable"] | None
    )
    routes: list[RouteItem]
    finalization_allowed: bool
    finalization_blockers: list[str]
    paid_api_requests: Literal[0] = 0
