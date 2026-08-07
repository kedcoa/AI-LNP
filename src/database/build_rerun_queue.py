"""Build a bounded rerun queue only from gaps remaining after local closure."""

from __future__ import annotations

import json
import sqlite3


ALLOWED_PAPERS = frozenset({
    "GP-002", "GP-004", "GP-005", "GP-006", "GP-008", "NP-001",
    "NP-002", "PILOT-001", "PILOT-002", "PILOT-003",
})


def build_rerun_queue(connection: sqlite3.Connection) -> list[dict[str, object]]:
    queue: list[dict[str, object]] = []
    papers = connection.execute(
        "SELECT paper_id, source_paper_id, import_status FROM paper ORDER BY source_paper_id"
    ).fetchall()
    for paper_id, source_id, import_status in papers:
        if source_id not in ALLOWED_PAPERS or import_status == "screening_only":
            continue
        fields: set[str] = set()
        formulation_count = connection.execute(
            "SELECT count(*) FROM formulation WHERE paper_id=?", (paper_id,)
        ).fetchone()[0]
        arm_count = connection.execute(
            "SELECT count(*) FROM experiment WHERE paper_id=?", (paper_id,)
        ).fetchone()[0]
        if formulation_count == 0:
            fields.add("formulation")
        if arm_count == 0:
            fields.add("experimental_arm")
        for status, missing_json in connection.execute(
            """
            SELECT a.completeness_status, a.missing_fields_json
            FROM arm_assessment a JOIN experiment e USING(experiment_id)
            WHERE e.paper_id=? AND a.completeness_status != 'complete'
            """, (paper_id,)
        ):
            try:
                fields.update(json.loads(missing_json or "[]"))
            except json.JSONDecodeError:
                fields.add("arm_completeness")
            if status in {"quarantined", "conflict"}:
                fields.add("human_verification")
        # A review-only state is not an extraction gap and must not spend a
        # provider call. It remains visible in the human review report.
        fields.discard("human_verification")
        if fields:
            queue.append({
                "paper_id": source_id,
                "fields": sorted(fields),
                "reason": "remaining post-local-closure canonical data gap",
            })
    return queue


__all__ = ["ALLOWED_PAPERS", "build_rerun_queue"]
