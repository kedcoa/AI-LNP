"""Classify post-import gaps and build a bounded paid-rerun queue."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
from typing import Iterable


ALLOWED_PAPERS = frozenset({
    "GP-002", "GP-004", "GP-005", "GP-006", "GP-008", "NP-001",
    "NP-002", "PILOT-001", "PILOT-002", "PILOT-003",
})

GAP_KINDS = frozenset({
    "source_not_reported", "source_asset_missing", "extraction_missed",
    "projection_missed", "scientific_conflict",
})
RERUNNABLE_GAP_KINDS = frozenset({"source_asset_missing", "extraction_missed"})


@dataclass(frozen=True)
class GapRecord:
    paper_id: str
    experiment_id: int | None
    record_id: str
    field_name: str
    gap_kind: str
    reason: str
    recoverable: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _graph_claim_predicates(
    corpus_root: Path | None, paper_id: str, source_experiment_id: str
) -> set[str]:
    if corpus_root is None:
        return set()
    path = (
        corpus_root / "data/staging/extraction/g1_fulltext_rag"
        / paper_id / "accepted_graph.json"
    )
    if not path.exists():
        return set()
    graph = json.loads(path.read_text(encoding="utf-8"))
    experiment = next(
        (row for row in graph.get("experiments", [])
         if row.get("experiment_id") == source_experiment_id),
        None,
    )
    if experiment is None:
        return set()
    claim_ids = set(experiment.get("claim_ids", [])) | set(
        experiment.get("shared_claim_ids", [])
    )
    return {
        str(claim.get("predicate"))
        for claim in graph.get("claims", [])
        if claim.get("claim_id") in claim_ids and claim.get("predicate")
    }


def _classify_field_gap(
    *,
    field_name: str,
    status: str,
    review_reasons: set[str],
    record_id: str,
    predicates: set[str],
) -> tuple[str, str]:
    if status == "conflict" or any("conflict" in reason for reason in review_reasons):
        return "scientific_conflict", "conflicting scientific evidence requires adjudication"
    if any(reason in {"outcome_link_unclear", "experiment_link_unclear"}
           for reason in review_reasons):
        return "projection_missed", "extracted records exist but their arm relationship is unresolved"
    if ":map-arm::" in record_id:
        return "projection_missed", "completed pilot map exists; outcome-to-arm linking remains unresolved"
    supporting_predicates = {
        "outcome": {"has_outcome_value", "measures_endpoint"},
        "payload_type": {"carries_payload", "encodes_product"},
        "encoded_product": {"encodes_product"},
        "biological_model": {"has_biological_model", "has_species"},
        "molecular_target": {"has_molecular_target", "therapeutic_target_cell"},
    }.get(field_name, set())
    if supporting_predicates and predicates & supporting_predicates:
        return "projection_missed", "source graph contains the field, but canonical arm projection did not attach it"
    return "source_not_reported", "available arm-scoped source claims do not report this field"


def audit_database_gaps(
    connection: sqlite3.Connection, *, corpus_root: Path | None = None
) -> tuple[GapRecord, ...]:
    """Return every canonical arm gap with an explicit non-overlapping cause."""

    rows = connection.execute(
        """
        SELECT p.source_paper_id,e.experiment_id,
               coalesce(json_extract(i.content_json,'$.record.record_id'),''),
               a.completeness_status,a.missing_fields_json
        FROM experiment e JOIN paper p USING(paper_id)
        JOIN arm_assessment a USING(experiment_id)
        LEFT JOIN import_record_identity i
          ON i.entity_type='experiment' AND i.entity_id=e.experiment_id
        WHERE json_array_length(a.missing_fields_json)>0
        ORDER BY p.source_paper_id,e.experiment_id
        """
    ).fetchall()
    gaps: list[GapRecord] = []
    for paper_id, experiment_id, record_id, status, missing_json in rows:
        review_reasons = {
            str(row[0]) for row in connection.execute(
                "SELECT reason_code FROM import_review WHERE arm_id=?",
                (experiment_id,),
            )
        }
        source_experiment_id = ""
        if ":ARM:" in record_id:
            source_experiment_id = record_id.split(":ARM:", 1)[1].split(":", 1)[0]
        predicates = _graph_claim_predicates(
            corpus_root, str(paper_id), source_experiment_id
        )
        try:
            missing_fields = json.loads(missing_json or "[]")
        except json.JSONDecodeError:
            missing_fields = ["arm_completeness"]
        for field_name in missing_fields:
            gap_kind, reason = _classify_field_gap(
                field_name=str(field_name), status=str(status),
                review_reasons=review_reasons, record_id=str(record_id),
                predicates=predicates,
            )
            gaps.append(GapRecord(
                paper_id=str(paper_id), experiment_id=int(experiment_id),
                record_id=str(record_id), field_name=str(field_name),
                gap_kind=gap_kind, reason=reason,
            ))
    return tuple(gaps)


def build_requests(gaps: Iterable[GapRecord]) -> tuple[dict[str, object], ...]:
    """Aggregate only gaps for which another extraction can add information."""

    fields: dict[str, set[str]] = {}
    for gap in gaps:
        rerunnable = gap.gap_kind == "extraction_missed" or (
            gap.gap_kind == "source_asset_missing" and gap.recoverable
        )
        if rerunnable:
            fields.setdefault(gap.paper_id, set()).add(gap.field_name)
    return tuple({
        "paper_id": paper_id,
        "fields": sorted(paper_fields),
        "reason": "recoverable post-projection extraction gap",
    } for paper_id, paper_fields in sorted(fields.items()))


def build_rerun_queue(
    connection: sqlite3.Connection, *, corpus_root: Path | None = None
) -> list[dict[str, object]]:
    return list(build_requests(audit_database_gaps(connection, corpus_root=corpus_root)))


def write_gap_audit(
    connection: sqlite3.Connection, output_path: Path, *, corpus_root: Path
) -> dict[str, object]:
    gaps = audit_database_gaps(connection, corpus_root=corpus_root)
    report = {
        "schema_version": "post-projection-gap-audit/v1",
        "gap_kinds": sorted(GAP_KINDS),
        "counts_by_kind": {
            kind: sum(gap.gap_kind == kind for gap in gaps)
            for kind in sorted(GAP_KINDS)
        },
        "records": [gap.to_dict() for gap in gaps],
        "paid_rerun_requests": list(build_requests(gaps)),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "ALLOWED_PAPERS", "GAP_KINDS", "GapRecord", "audit_database_gaps",
    "build_requests", "build_rerun_queue", "write_gap_audit",
]
