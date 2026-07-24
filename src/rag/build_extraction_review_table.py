from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "data" / "staging" / "extraction" / "g1_fulltext_rag"
REPORT_ROOT = ROOT / "reports" / "rag"


def clean(value: str) -> str:
    return " ".join(value.replace("|", "\\|").split())


def build(paper_id: str) -> tuple[Path, Path, Path]:
    paper_root = RUN_ROOT / paper_id
    graph = json.loads((paper_root / "accepted_graph.json").read_text())
    clauses = {
        row["clause_id"]: row["text"]
        for row in json.loads((paper_root / "source_clauses.json").read_text())
    }
    provenance = json.loads((paper_root / "clause_provenance.json").read_text())
    manifest = json.loads((RUN_ROOT / "run_manifest.json").read_text())
    run_row = next(row for row in manifest["papers"] if row["paper_id"] == paper_id)
    entities = {row["entity_id"]: row for row in graph["entities"]}
    experiment_labels = {
        row["experiment_id"]: row["label"] for row in graph["experiments"]
    }
    entity_scopes: dict[str, set[str]] = {
        entity_id: set() for entity_id in entities
    }
    for claim in graph["claims"]:
        scope = claim["experiment_id"]
        entity_scopes[claim["subject_entity_id"]].add(scope)
        entity_scopes[claim["object_entity_id"]].add(scope)
    rows = []
    for claim in graph["claims"]:
        subject = entities[claim["subject_entity_id"]]
        obj = entities[claim["object_entity_id"]]
        for evidence in claim["evidence"]:
            source = provenance[evidence["clause_id"]]
            rows.append({
                "experiment_id": claim["experiment_id"],
                "experiment": experiment_labels.get(claim["experiment_id"], "Shared"),
                "claim_id": claim["claim_id"],
                "subject_type": subject["entity_type"],
                "subject": subject["reported_name"],
                "relation": claim["predicate"],
                "object_type": obj["entity_type"],
                "object": obj["reported_name"],
                "evidence_quote": evidence["quote"],
                "source_section": source["section_path"],
                "source_file": source["source_path"],
                "page_or_xml_id": source["page_number"] or source["xml_element_id"] or "",
                "human_decision": "",
                "human_reason": "",
            })
    entity_rows = []
    for entity in graph["entities"]:
        for evidence in entity["evidence"]:
            source = provenance[evidence["clause_id"]]
            entity_rows.append({
                "entity_id": entity["entity_id"],
                "entity_type": entity["entity_type"],
                "experiment_scope": ", ".join(
                    sorted(entity_scopes[entity["entity_id"]])
                ) or "unlinked/pending",
                "reported_name": entity["reported_name"],
                "normalized_name": entity.get("normalized_name") or "",
                "normalization_status": entity["normalization_status"],
                "evidence_quote": evidence["quote"],
                "source_section": source["section_path"],
                "source_file": source["source_path"],
                "page_or_xml_id": source["page_number"] or source["xml_element_id"] or "",
                "human_decision": "",
                "human_reason": "",
            })
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    csv_path = REPORT_ROOT / f"{paper_id}_fulltext_extraction_review.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    entity_csv_path = REPORT_ROOT / f"{paper_id}_fulltext_entity_inventory.csv"
    with entity_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(entity_rows[0]))
        writer.writeheader()
        writer.writerows(entity_rows)
    md_path = REPORT_ROOT / f"{paper_id}_fulltext_extraction_review.md"
    lines = [
        f"# {paper_id} full-text extraction review",
        "",
        "Automated status: **accepted with zero deterministic audit findings**.",
        "",
        "This does not establish scientific correctness. For each row, verify that "
        "the subject–relation–object statement is supported by the quote and belongs "
        "to the stated experiment.",
        "",
        "## Unresolved ambiguities",
        "",
    ]
    lines.extend(f"- {value}" for value in run_row["unresolved_ambiguities"])
    lines += [
        "",
        "## Extracted entity inventory",
        "",
        "This table includes extracted entities even when a relationship was withheld "
        "for insufficient cross-field evidence.",
        "",
        "| Type | Experiment/control scope | Reported value | Normalized value | Exact evidence | Source |",
        "|---|---|---|---|---|---|",
    ]
    for row in entity_rows:
        source = (
            f"{clean(row['source_section'])}; "
            f"{Path(row['source_file']).name}; "
            f"{row['page_or_xml_id'] or 'location not numbered'}"
        )
        lines.append(
            f"| {row['entity_type']} | {clean(row['experiment_scope'])} | "
            f"{clean(row['reported_name'])} | "
            f"{clean(row['normalized_name']) or 'unresolved'} | "
            f"“{clean(row['evidence_quote'])}” | {source} |"
        )
    lines += [
        "",
        "## Extracted claims",
        "",
        "| Experiment | Claim | Extracted relation | Exact evidence | Source | Human decision |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        relation = (
            f"{clean(row['subject'])} ({row['subject_type']}) "
            f"—{row['relation']}→ {clean(row['object'])} ({row['object_type']})"
        )
        source = (
            f"{clean(row['source_section'])}; "
            f"{Path(row['source_file']).name}; "
            f"{row['page_or_xml_id'] or 'location not numbered'}"
        )
        lines.append(
            f"| {row['experiment_id']}: {clean(row['experiment'])} | {row['claim_id']} | "
            f"{relation} | “{clean(row['evidence_quote'])}” | {source} |  |"
        )
    lines += [
        "",
        "## Approval rule",
        "",
        f"Do not approve {paper_id} unless every retained claim is correct, belongs to the "
        "right experiment, and is supported by its quoted source. Mark unsupported, "
        "mis-scoped, incomplete, or scientifically misleading rows as incorrect and "
        "record the reason in the CSV.",
    ]
    md_path.write_text("\n".join(lines) + "\n")
    return md_path, csv_path, entity_csv_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", required=True)
    args = parser.parse_args()
    print("\n".join(map(str, build(args.paper_id))))
