"""Deterministic first-pass screening for a newly discovered paper batch."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable

from src.search.build_candidate_index import (
    normalize_doi,
    normalize_pmcid,
    normalize_title,
)


CELL_ORDER = ("hepatocyte", "kupffer", "lsec", "hsc")
LNP = re.compile(r"\b(?:lipid nanoparticles?|lnps?|ionizable lipid)\b", re.I)
PAYLOAD = re.compile(r"\b(?:mRNA|siRNA|saRNA|circRNA)\b", re.I)
ORIGINAL = re.compile(
    r"\b(?:we (?:show|report|developed|administered|tested|evaluated)|"
    r"this study|in vivo|in vitro|mice|rats|cells? (?:were|received))\b",
    re.I,
)
OUTCOME = re.compile(
    r"\b(?:expression|uptake|delivery|transfection|knockdown|silencing|"
    r"biodistribution|efficacy|reduced|increased|measured|assessed)\b",
    re.I,
)
REVIEW_TYPE = re.compile(r"\b(?:review|editorial|comment|meta-analysis)\b", re.I)
NON_LNP_TITLE = re.compile(r"\b(?:polymeric micelles?|liposomes?|solid lipid nanoparticles?)\b", re.I)
CELL_TERMS = {
    "hepatocyte": re.compile(r"\bhepatocytes?\b|hepatic parenchymal", re.I),
    "kupffer": re.compile(r"\bkupffer\b|liver (?:resident )?macrophage", re.I),
    "lsec": re.compile(r"\blsecs?\b|sinusoidal endothelial", re.I),
    "hsc": re.compile(r"hepatic stellate|liver stellate|\bIto cells?\b", re.I),
}


def _identity_keys(record: dict[str, object]) -> set[str]:
    keys: set[str] = set()
    pmid = str(record.get("pmid") or "").strip()
    pmcid = normalize_pmcid(str(record.get("pmcid") or ""))
    doi = normalize_doi(str(record.get("doi") or ""))
    title = normalize_title(str(record.get("title") or ""))
    if pmid:
        keys.add(f"pmid:{pmid}")
    if pmcid:
        keys.add(f"pmcid:{pmcid}")
    if doi:
        keys.add(f"doi:{doi}")
    if title:
        keys.add(f"title:{title}")
    return keys


def deduplicate_against_database(
    candidates: Iterable[dict[str, object]],
    database_path: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Separate novel records from papers already represented in SQLite."""

    existing: dict[str, str] = {}
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute(
            "SELECT source_paper_id,pmid,pmcid,doi,title FROM paper"
        ):
            source_id = str(row["source_paper_id"])
            for key in _identity_keys(dict(row)):
                existing.setdefault(key, source_id)

    novel: list[dict[str, object]] = []
    duplicates: list[dict[str, object]] = []
    for candidate in candidates:
        matching = sorted(_identity_keys(candidate) & existing.keys())
        if matching:
            duplicate_of = sorted({existing[key] for key in matching})
            duplicates.append(
                {
                    **candidate,
                    "duplicate_of": ",".join(duplicate_of),
                    "matching_keys": matching,
                }
            )
        else:
            novel.append(candidate)
    return novel, duplicates


def screen_candidate(candidate: dict[str, object]) -> dict[str, object]:
    """Apply a conservative, explainable abstract-level screening decision."""

    title = str(candidate.get("title") or "")
    abstract = str(candidate.get("abstract") or "")
    publication_types = " ".join(
        str(value) for value in candidate.get("publication_types", [])
    )
    text = f"{title}. {abstract}"
    if REVIEW_TYPE.search(title) or REVIEW_TYPE.search(publication_types):
        return {
            "decision": "exclude",
            "screening_scope": "automatic_abstract_screen",
            "reason_codes": ["NOT_ORIGINAL_RESEARCH"],
        }
    if NON_LNP_TITLE.search(title) and not LNP.search(title):
        return {
            "decision": "exclude",
            "screening_scope": "automatic_abstract_screen",
            "reason_codes": ["NOT_ELIGIBLE_LNP"],
        }

    matched_cells = {
        str(value).replace("kupffer_cell", "kupffer")
        for value in candidate.get("matched_cell_types", [])
    }
    target_supported = any(
        cell in CELL_TERMS and CELL_TERMS[cell].search(abstract)
        for cell in matched_cells
    )
    signals = {
        "ORIGINAL_EXPERIMENT": bool(ORIGINAL.search(abstract)),
        "IDENTIFIABLE_LNP": bool(LNP.search(text)),
        "SUPPORTED_PAYLOAD": bool(PAYLOAD.search(text)),
        "TARGET_CELL_EVIDENCE": target_supported
        and bool(ORIGINAL.search(abstract) or OUTCOME.search(abstract)),
        "USABLE_FORMULATION_OUTCOME_LINKAGE": bool(LNP.search(abstract))
        and bool(OUTCOME.search(abstract)),
    }
    if all(signals.values()):
        return {
            "decision": "include",
            "screening_scope": "automatic_abstract_screen",
            "reason_codes": list(signals),
        }
    return {
        "decision": "manual_review",
        "screening_scope": "automatic_abstract_screen",
        "reason_codes": ["FULL_TEXT_REQUIRED"],
        "unresolved_criteria": [
            reason for reason, supported in signals.items() if not supported
        ],
    }


def select_balanced_full_text_batch(
    screened: Iterable[dict[str, object]],
    *,
    per_cell: int,
) -> list[dict[str, object]]:
    """Select a stable, cell-balanced OA queue from abstract includes."""

    rows = list(screened)
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    for cell in CELL_ORDER:
        eligible = [
            row
            for row in rows
            if row.get("decision") == "include"
            and row.get("pmcid")
            and cell in {
                str(value).replace("kupffer_cell", "kupffer")
                for value in row.get("matched_cell_types", [])
            }
        ]
        eligible.sort(key=lambda row: str(row.get("candidate_id") or ""))
        count = 0
        for row in eligible:
            candidate_id = str(row.get("candidate_id") or "")
            if candidate_id in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(candidate_id)
            count += 1
            if count == per_cell:
                break
    return selected


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def start_batch(
    metadata_path: Path,
    database_path: Path,
    output_dir: Path,
    *,
    per_cell: int = 3,
) -> dict[str, object]:
    """Deduplicate, screen, and queue a first balanced full-text batch."""

    candidates = _read_jsonl(metadata_path)
    novel, duplicates = deduplicate_against_database(candidates, database_path)
    screened = [{**row, **screen_candidate(row)} for row in novel]
    selected = select_balanced_full_text_batch(screened, per_cell=per_cell)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "novel_candidates.jsonl", novel)
    _write_jsonl(output_dir / "database_duplicates.jsonl", duplicates)
    _write_jsonl(output_dir / "screening_ledger.jsonl", screened)
    _write_jsonl(output_dir / "full_text_queue.jsonl", selected)
    summary = {
        "schema_version": "new-paper-batch/v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "metadata_path": str(metadata_path.resolve()),
        "database_path": str(database_path.resolve()),
        "discovered_unique_candidates": len(candidates),
        "already_in_database": len(duplicates),
        "novel_candidates": len(novel),
        "screened_papers": len(screened),
        "screening_decisions": {
            decision: sum(row["decision"] == decision for row in screened)
            for decision in ("include", "exclude", "manual_review")
        },
        "full_text_queued": len(selected),
        "full_text_queue_by_cell": {
            cell: sum(
                cell in {
                    str(value).replace("kupffer_cell", "kupffer")
                    for value in row.get("matched_cell_types", [])
                }
                for row in selected
            )
            for cell in CELL_ORDER
        },
        "source_accessible_papers": 0,
        "papers_with_evidence_backed_arms": 0,
        "extracted_imported_arms": 0,
        "stage": "full_text_queued",
    }
    (output_dir / "batch_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-cell", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = start_batch(
        args.metadata,
        args.database,
        args.output_dir,
        per_cell=args.per_cell,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = [
    "deduplicate_against_database",
    "screen_candidate",
    "select_balanced_full_text_batch",
    "start_batch",
]
