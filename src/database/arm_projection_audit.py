"""Account for source experiment identities in the canonical SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


ArmProjectionDisposition = Literal[
    "projected", "incomplete", "quarantined", "rejected", "screening_only"
]


@dataclass(frozen=True)
class GraphExperimentIdentity:
    paper_id: str
    experiment_id: str
    label: str | None
    boundary_status: str | None
    boundary_reason: str | None
    json_path: str


def _graph_experiments(root: Path) -> dict[str, tuple[GraphExperimentIdentity, ...]]:
    graph_root = root / "data/staging/extraction/g1_fulltext_rag"
    result: dict[str, tuple[GraphExperimentIdentity, ...]] = {}
    if not graph_root.is_dir():
        return result
    for path in sorted(graph_root.glob("*/accepted_graph.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        paper_id = str(payload.get("paper_id") or path.parent.name)
        rows = tuple(
            GraphExperimentIdentity(
                paper_id=paper_id,
                experiment_id=str(row["experiment_id"]),
                label=row.get("label"),
                boundary_status=row.get("boundary_status"),
                boundary_reason=row.get("boundary_reason"),
                json_path=f"$.experiments[{index}]",
            )
            for index, row in enumerate(payload.get("experiments", []))
        )
        result[paper_id] = rows
    return result


def _paper_rows(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(paper)").fetchall()
    }
    optional = [
        name for name in ("screening_status", "import_status") if name in columns
    ]
    selected = ", ".join(["paper_id", "source_paper_id", *optional])
    return {
        str(row["source_paper_id"]): row
        for row in connection.execute(f"SELECT {selected} FROM paper")
    }


def _arm_record_ids(
    connection: sqlite3.Connection, paper_id: int
) -> tuple[tuple[int, str], ...]:
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='import_record_identity'"
    ).fetchone() is None:
        return ()
    rows = connection.execute(
        """
        SELECT entity_id, content_json
        FROM import_record_identity
        WHERE paper_id = ? AND entity_type = 'experiment'
        ORDER BY entity_id
        """,
        (paper_id,),
    ).fetchall()
    result: list[tuple[int, str]] = []
    for row in rows:
        try:
            content = json.loads(row[1])
            record_id = str(content["record"]["record_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        result.append((int(row[0]), record_id))
    return tuple(result)


def _reviews(connection: sqlite3.Connection, paper_id: int) -> tuple[sqlite3.Row, ...]:
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='import_review'"
    ).fetchone() is None:
        return ()
    return tuple(
        connection.execute(
            """
            SELECT natural_key, reason_code, review_status, notes
            FROM import_review
            WHERE paper_id = ?
            ORDER BY import_review_id
            """,
            (paper_id,),
        ).fetchall()
    )


def _review_disposition(status: str) -> ArmProjectionDisposition:
    if status == "incomplete":
        return "incomplete"
    if status in {"conflict", "quarantined"}:
        return "quarantined"
    return "rejected"


def audit_arm_projection(root: Path, database: Path) -> dict[str, object]:
    """Compare explicit graph experiment identities with canonical arm identities."""

    root = Path(root).resolve()
    database = Path(database).resolve()
    graphs = _graph_experiments(root)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        papers = _paper_rows(connection)
        report_papers: dict[str, object] = {}
        totals = {
            "graph_experiments": 0,
            "accounted_experiments": 0,
            "projected_experiments": 0,
            "unexplained_experiments": 0,
            "multi_arm_projection_extras": 0,
        }
        for source_paper_id, source_experiments in sorted(graphs.items()):
            paper = papers.get(source_paper_id)
            paper_id = int(paper["paper_id"]) if paper is not None else None
            arms = _arm_record_ids(connection, paper_id) if paper_id is not None else ()
            reviews = _reviews(connection, paper_id) if paper_id is not None else ()
            screening_only = bool(
                paper is not None
                and (
                    ("import_status" in paper.keys() and paper["import_status"] == "screening_only")
                    or ("screening_status" in paper.keys() and paper["screening_status"] == "exclude")
                )
            )
            experiment_rows: dict[str, object] = {}
            unexplained: list[str] = []
            projected_count = 0
            duplicate_count = 0
            for experiment in source_experiments:
                matched_arms = [
                    {"entity_id": entity_id, "record_id": record_id}
                    for entity_id, record_id in arms
                    if experiment.experiment_id in record_id
                ]
                matched_reviews = [
                    row for row in reviews if experiment.experiment_id in str(row["natural_key"])
                ]
                disposition: ArmProjectionDisposition | None = None
                reason: str | None = None
                if matched_arms:
                    disposition = "projected"
                    projected_count += 1
                    if len(matched_arms) > 1:
                        duplicate_count += len(matched_arms) - 1
                elif matched_reviews:
                    disposition = _review_disposition(str(matched_reviews[-1]["review_status"]))
                    reason = str(matched_reviews[-1]["reason_code"])
                elif screening_only:
                    disposition = "screening_only"
                    reason = "paper_is_screening_only"
                else:
                    unexplained.append(experiment.experiment_id)
                experiment_rows[experiment.experiment_id] = {
                    **asdict(experiment),
                    "disposition": disposition,
                    "reason": reason,
                    "sqlite_arms": matched_arms,
                    "review_records": [
                        {
                            "natural_key": str(row["natural_key"]),
                            "reason_code": str(row["reason_code"]),
                            "review_status": str(row["review_status"]),
                            "notes": row["notes"],
                        }
                        for row in matched_reviews
                    ],
                }
            accounted = len(source_experiments) - len(unexplained)
            report_papers[source_paper_id] = {
                "graph_experiment_count": len(source_experiments),
                "sqlite_arm_count": len(arms),
                "accounted_count": accounted,
                "projected_count": projected_count,
                "duplicate_projection_count": duplicate_count,
                "unexplained_experiment_ids": unexplained,
                "experiments": experiment_rows,
            }
            totals["graph_experiments"] += len(source_experiments)
            totals["accounted_experiments"] += accounted
            totals["projected_experiments"] += projected_count
            totals["unexplained_experiments"] += len(unexplained)
            totals["multi_arm_projection_extras"] += duplicate_count
        return {
            "database": str(database),
            "root": str(root),
            "summary": totals,
            "papers": report_papers,
        }
    finally:
        connection.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = audit_arm_projection(args.root, args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if report["summary"]["unexplained_experiments"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
