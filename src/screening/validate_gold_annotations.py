"""Validate the frozen Day 4 field-level gold annotation package."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data" / "annotations" / "gold_v1"


def load(name: str) -> list[dict[str, str]]:
    with (GOLD / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def duplicate_ids(rows: list[dict[str, str]], key: str) -> list[str]:
    counts = Counter(row[key] for row in rows)
    return sorted(value for value, count in counts.items() if count > 1)


def validate() -> list[str]:
    errors: list[str] = []
    papers = load("papers.csv")
    formulations = load("formulations.csv")
    components = load("components.csv")
    experiments = load("experiments.csv")
    outcomes = load("outcomes.csv")
    evidence = load("evidence.csv")
    issues = load("issues.csv")

    tables = [
        (papers, "gold_paper_id", "papers"),
        (formulations, "gold_formulation_id", "formulations"),
        (components, "gold_component_id", "components"),
        (experiments, "gold_experiment_id", "experiments"),
        (outcomes, "gold_outcome_id", "outcomes"),
        (evidence, "evidence_id", "evidence"),
        (issues, "issue_id", "issues"),
    ]
    for rows, key, label in tables:
        duplicates = duplicate_ids(rows, key)
        if duplicates:
            errors.append(f"duplicate {label} IDs: {duplicates}")

    paper_ids = {row["gold_paper_id"] for row in papers}
    formulation_ids = {row["gold_formulation_id"] for row in formulations}
    experiment_ids = {row["gold_experiment_id"] for row in experiments}
    evidence_ids = {row["evidence_id"] for row in evidence}

    for row in formulations:
        if row["gold_paper_id"] not in paper_ids:
            errors.append(f"{row['gold_formulation_id']} references a missing paper")
        if row["evidence_id"] not in evidence_ids:
            errors.append(f"{row['gold_formulation_id']} references missing evidence")
    for row in components:
        if row["gold_formulation_id"] not in formulation_ids:
            errors.append(f"{row['gold_component_id']} references a missing formulation")
        if row["evidence_id"] not in evidence_ids:
            errors.append(f"{row['gold_component_id']} references missing evidence")
    for row in experiments:
        if row["gold_paper_id"] not in paper_ids:
            errors.append(f"{row['gold_experiment_id']} references a missing paper")
        if row["gold_formulation_id"] not in formulation_ids:
            errors.append(f"{row['gold_experiment_id']} references a missing formulation")
        if row["evidence_id"] not in evidence_ids:
            errors.append(f"{row['gold_experiment_id']} references missing evidence")
    for row in outcomes:
        if row["gold_experiment_id"] not in experiment_ids:
            errors.append(f"{row['gold_outcome_id']} references a missing experiment")
        if row["evidence_id"] not in evidence_ids:
            errors.append(f"{row['gold_outcome_id']} references missing evidence")

    pending = [row["gold_paper_id"] for row in papers if row["annotation_status"] == "pending"]
    if pending:
        errors.append(f"pending paper annotations: {pending}")
    if len(papers) < 8 or len(papers) > 12:
        errors.append(f"expected 8-12 gold papers, found {len(papers)}")
    if {row["screening_cell_type"] for row in papers} != {"hepatocyte", "kupffer_cell", "lsec", "hsc"}:
        errors.append("gold papers do not cover all four configured liver cell types")

    complete_ids = {row["gold_formulation_id"] for row in formulations if row["formulation_complete"] == "true"}
    for formulation_id in complete_ids:
        values = [
            float(row["molar_percentage"])
            for row in components
            if row["gold_formulation_id"] == formulation_id and row["molar_percentage"]
        ]
        if values and abs(sum(values) - 100.0) > 1e-6:
            errors.append(f"{formulation_id} component percentages sum to {sum(values)}")

    required_locations = {"xml_structured_table", "supplement_pdf_table", "supplement_pdf_figure"}
    actual_locations = {row["evidence_location_type"] for row in evidence}
    missing_locations = required_locations - actual_locations
    if missing_locations:
        errors.append(f"missing required evidence-location cases: {sorted(missing_locations)}")

    issue_types = {row["issue_type"] for row in issues}
    required_issues = {
        "incomplete_proprietary_formulation",
        "incomplete_ambiguous_chemistry",
        "irrelevant_acronym_hit",
        "ambiguous_chemistry",
        "delivery_recipient_vs_therapeutic_target",
    }
    missing_issues = required_issues - issue_types
    if missing_issues:
        errors.append(f"missing required edge cases: {sorted(missing_issues)}")

    experiment_fields = set(experiments[0]) if experiments else set()
    for field in ("delivery_recipient_cell", "therapeutic_target_cell"):
        if field not in experiment_fields:
            errors.append(f"experiments.csv lacks {field}")

    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("Day 4 gold validation: FAIL")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("Day 4 gold validation: PASS")


if __name__ == "__main__":
    main()
