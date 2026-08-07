"""Evidence-first re-screening of target scope in canonical experiments."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.database.target_scope import classify_target_statement


@dataclass(frozen=True)
class TargetScopeCandidate:
    paper_id: str
    experiment_id: int
    evidence_id: int
    evidence_text: str
    page_number: str | None
    source_path: str | None
    intended_target_cell: str | None = None
    target_or_recipient_organ: str | None = None
    observed_transfected_cell: str | None = None
    disposition: str = "resolved"
    reason: str | None = None


@dataclass(frozen=True)
class PaperTargetScopeResult:
    paper_id: str
    candidates: tuple[TargetScopeCandidate, ...]
    unresolved: tuple[TargetScopeCandidate, ...]
    remaining_missing_delivery_destinations: tuple[int, ...]


def _source_pdf(connection: sqlite3.Connection, paper_id: int) -> str | None:
    row = connection.execute(
        """SELECT logical_path FROM source_artifact
           WHERE paper_id=? AND lower(logical_path) LIKE '%.pdf'
           ORDER BY contributes_evidence DESC, source_artifact_id LIMIT 1""",
        (paper_id,),
    ).fetchone()
    return None if row is None else str(row[0])


def _matching_cells(text: str) -> set[str]:
    patterns = {
        "hepatocyte": r"\bhepatocytes?\b",
        "kupffer_cell": r"\bkupffer cells?\b",
        "lsec": r"\b(?:lsecs?|liver sinusoidal endothelial cells?|liver endothelial cells?)\b",
        "hsc": r"\b(?:hscs?|hepatic stellate cells?)\b",
    }
    return {
        name for name, pattern in patterns.items()
        if re.search(pattern, text, re.IGNORECASE)
    }


def rescreen_paper(
    connection: sqlite3.Connection, source_paper_id: str
) -> PaperTargetScopeResult:
    paper = connection.execute(
        "SELECT paper_id FROM paper WHERE source_paper_id=?", (source_paper_id,)
    ).fetchone()
    if paper is None:
        raise KeyError(f"Unknown paper: {source_paper_id}")
    paper_id = int(paper[0])
    source_path = _source_pdf(connection, paper_id)
    rows = connection.execute(
        """SELECT evidence_id,experiment_id,evidence_text,page_number
           FROM evidence
           WHERE paper_id=? AND experiment_id IS NOT NULL
             AND evidence_review_status NOT IN ('rejected','conflict')
           ORDER BY experiment_id,evidence_id""",
        (paper_id,),
    ).fetchall()
    candidates: list[TargetScopeCandidate] = []
    unresolved: list[TargetScopeCandidate] = []
    for evidence_id, experiment_id, text, page_number in rows:
        statement = classify_target_statement(str(text))
        matching_cells = _matching_cells(str(text))
        if len(matching_cells) > 1:
            if statement.target_or_recipient_organ:
                candidates.append(TargetScopeCandidate(
                    paper_id=source_paper_id,
                    experiment_id=int(experiment_id),
                    evidence_id=int(evidence_id),
                    evidence_text=str(text),
                    page_number=page_number,
                    source_path=source_path,
                    target_or_recipient_organ=statement.target_or_recipient_organ,
                ))
            unresolved.append(TargetScopeCandidate(
                paper_id=source_paper_id,
                experiment_id=int(experiment_id),
                evidence_id=int(evidence_id),
                evidence_text=str(text),
                page_number=page_number,
                source_path=source_path,
                disposition="unresolved",
                reason="multiple cell types named; quote does not identify one arm-specific cell",
            ))
            continue
        if statement.ambiguous:
            continue
        candidates.append(TargetScopeCandidate(
            paper_id=source_paper_id,
            experiment_id=int(experiment_id),
            evidence_id=int(evidence_id),
            evidence_text=str(text),
            page_number=page_number,
            source_path=source_path,
            intended_target_cell=statement.intended_target_cell,
            target_or_recipient_organ=statement.target_or_recipient_organ,
            observed_transfected_cell=statement.observed_transfected_cell,
        ))

    resolved_experiments = {
        row.experiment_id for row in candidates
        if row.intended_target_cell or row.target_or_recipient_organ
    }
    experiment_ids = {
        int(row[0]) for row in connection.execute(
            "SELECT experiment_id FROM experiment WHERE paper_id=?", (paper_id,)
        )
    }
    return PaperTargetScopeResult(
        paper_id=source_paper_id,
        candidates=tuple(candidates),
        unresolved=tuple(unresolved),
        remaining_missing_delivery_destinations=tuple(
            sorted(experiment_ids - resolved_experiments)
        ),
    )


def apply_target_scope_candidates(
    connection: sqlite3.Connection,
    results: tuple[PaperTargetScopeResult, ...],
) -> int:
    """Apply only non-conflicting evidence-linked semantic candidates."""

    applied = 0
    for result in results:
        grouped: dict[tuple[int, str], list[tuple[str, int]]] = {}
        for row in result.candidates:
            for field_name in (
                "intended_target_cell",
                "target_or_recipient_organ",
                "observed_transfected_cell",
            ):
                value = getattr(row, field_name)
                if value:
                    grouped.setdefault((row.experiment_id, field_name), []).append(
                        (value, row.evidence_id)
                    )
        for (experiment_id, field_name), values in grouped.items():
            distinct = {value for value, _ in values}
            if len(distinct) != 1:
                continue
            value = next(iter(distinct))
            evidence_id = values[0][1]
            connection.execute(
                f"UPDATE experiment SET {field_name}=? WHERE experiment_id=?",
                (value, experiment_id),
            )
            connection.execute(
                """INSERT INTO field_verification (
                       experiment_id,field_name,evidence_id,verification_status,
                       notes,verified_at
                   ) VALUES (?,?,?,'automatically_validated',?,?)""",
                (
                    experiment_id,
                    field_name,
                    evidence_id,
                    "deterministic target-scope classification",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            applied += 1
    return applied


def write_rescreen_report(
    results: tuple[PaperTargetScopeResult, ...], json_path: Path
) -> None:
    payload = {
        "schema_version": "target-scope-rescreen/v1",
        "papers": [
            {
                "paper_id": result.paper_id,
                "candidates": [asdict(row) for row in result.candidates],
                "unresolved": [asdict(row) for row in result.unresolved],
                "remaining_missing_delivery_destinations": list(
                    result.remaining_missing_delivery_destinations
                ),
            }
            for result in results
        ],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "PaperTargetScopeResult",
    "TargetScopeCandidate",
    "apply_target_scope_candidates",
    "rescreen_paper",
    "write_rescreen_report",
]
