"""Exact coverage audit for the immutable source-fact ledger."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFactCoverage:
    artifact_id: int
    source_count: int
    projected_count: int
    unresolved_count: int
    quarantined_count: int
    rejected_count: int
    accounted_count: int
    silent_omissions: tuple[int, ...]
    unresolved_evidence: tuple[int, ...]


def audit_source_fact_coverage(
    connection: sqlite3.Connection, artifact_id: int
) -> SourceFactCoverage:
    rows = connection.execute(
        """
        SELECT source_fact_id, import_disposition, disposition_reason
        FROM source_fact
        WHERE source_artifact_id = ?
        ORDER BY source_fact_id
        """,
        (artifact_id,),
    ).fetchall()
    counts = {
        disposition: sum(row[1] == disposition for row in rows)
        for disposition in ("projected", "unresolved", "quarantined", "rejected")
    }
    silent: list[int] = []
    for fact_id, disposition, reason in rows:
        if disposition == "projected":
            active = connection.execute(
                """
                SELECT 1 FROM fact_projection
                WHERE source_fact_id = ? AND projection_status = 'active'
                LIMIT 1
                """,
                (fact_id,),
            ).fetchone()
            if active is None:
                silent.append(int(fact_id))
        elif not (reason or "").strip():
            silent.append(int(fact_id))
    unresolved_evidence = tuple(
        int(row[0])
        for row in connection.execute(
            """
            SELECT source_fact_evidence_id
            FROM source_fact_evidence
            WHERE source_fact_id IN (
                SELECT source_fact_id FROM source_fact
                WHERE source_artifact_id = ?
            )
              AND (
                  (resolution_status = 'resolved' AND evidence_id IS NULL)
                  OR (
                      resolution_status != 'resolved'
                      AND length(trim(coalesce(resolution_reason, ''))) = 0
                  )
              )
            ORDER BY source_fact_evidence_id
            """,
            (artifact_id,),
        )
    )
    accounted = sum(counts.values())
    if len(rows) != accounted or silent or unresolved_evidence:
        raise ValueError(
            "silent source-fact omission: "
            f"artifact={artifact_id}, facts={silent}, evidence={list(unresolved_evidence)}"
        )
    return SourceFactCoverage(
        artifact_id=artifact_id,
        source_count=len(rows),
        projected_count=counts["projected"],
        unresolved_count=counts["unresolved"],
        quarantined_count=counts["quarantined"],
        rejected_count=counts["rejected"],
        accounted_count=accounted,
        silent_omissions=tuple(silent),
        unresolved_evidence=unresolved_evidence,
    )
