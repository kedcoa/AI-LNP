"""Gold-aware evaluator for the gold-blind provisional experiment inventory."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from src.extraction.v12_structure_contracts import (
    ProvisionalExperimentInventoryV12,
    ProvisionalExperimentV12,
)


ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = ROOT / "data/annotations/gold_v1/experiments.csv"
INVENTORY_ROOT = ROOT / "data/staging/extraction/v12_provisional_experiments"
OUTPUT_ROOT = ROOT / "reports/extraction/v12_provisional_experiment_eval"
MATCH_THRESHOLD = 8


def _payload_signature(text: str) -> str:
    lowered = text.casefold()
    if "fapcar" in lowered or "car-m" in lowered:
        return "fapcar"
    if "cas9" in lowered or "sgrna" in lowered:
        return "cas9_sgrna"
    if "simicu1" in lowered:
        return "simicu1"
    if re.search(r"\b(?:hgf|egf)\b", lowered):
        return "hgf_egf"
    if "egfp" in lowered or re.search(r"\bgfp\b", lowered):
        return "egfp_gfp"
    if "luciferase" in lowered or "zsgreen" in lowered:
        return "luciferase_zsgreen"
    if "sirna" in lowered:
        return "sirna"
    return "generic_lnp"


def _gold_cells(row: dict[str, str]) -> set[str]:
    text = " ".join(
        row.get(field, "")
        for field in (
            "cell_type",
            "delivery_recipient_cell",
            "therapeutic_target_cell",
            "cell_source",
        )
    ).casefold()
    cells = set()
    if "kupffer" in text or "f4/80" in text:
        cells.add("kupffer_cell")
    if "lsec" in text or "sinusoidal endothelial" in text or "lyve" in text:
        cells.add("lsec")
    if "hepatocyte" in text:
        cells.add("hepatocyte")
    if "macrophage" in text or "bmdm" in text or "cd163" in text:
        cells.add("macrophage")
    if "hsc" in text or "stellate" in text or "js-1" in text:
        cells.add("hsc")
    return cells


def _gold_assays(row: dict[str, str]) -> set[str]:
    text = row.get("assay", "").casefold()
    assays = set()
    if "immun" in text:
        assays.add("immunostaining")
    if "flow" in text:
        assays.add("flow_cytometry")
    if "sequenc" in text or "rna-seq" in text:
        assays.add("sequencing")
    if "imaging" in text:
        assays.add("imaging")
    if "phagocyt" in text or "cytotoxic" in text:
        assays.add("phagocytosis_cytotoxicity")
    if "aptt" in text or "fviii" in text:
        assays.add("coagulation_activity")
    if "histolog" in text:
        assays.add("histology")
    return assays


def _anchors(experiment: ProvisionalExperimentV12, anchor_type: str) -> set[str]:
    return {
        anchor.value
        for anchor in experiment.anchors
        if anchor.anchor_type == anchor_type
    }


def match_score(
    gold: dict[str, str],
    provisional: ProvisionalExperimentV12,
) -> tuple[int, list[str]]:
    reasons = []
    score = 0
    gold_payload = _payload_signature(
        " ".join(
            gold.get(field, "")
            for field in ("payload_type", "payload_name", "reporter")
        )
    )
    if gold_payload in _anchors(provisional, "payload"):
        score += 6
        reasons.append("payload_signature")

    gold_context = gold.get("in_vitro_in_vivo", "").strip()
    if gold_context in _anchors(provisional, "model"):
        score += 4
        reasons.append("experimental_context")

    cell_overlap = _gold_cells(gold) & _anchors(provisional, "cell_context")
    if cell_overlap:
        score += 2
        reasons.append("cell_context")

    assay_overlap = _gold_assays(gold) & _anchors(provisional, "assay")
    if assay_overlap:
        score += 1
        reasons.append("assay")
    return score, reasons


def _best_assignment(
    gold_rows: list[dict[str, str]],
    experiments: list[ProvisionalExperimentV12],
) -> list[tuple[int, int, int, list[str]]]:
    options = []
    for gold_index, gold in enumerate(gold_rows):
        row_options = []
        for experiment_index, experiment in enumerate(experiments):
            score, reasons = match_score(gold, experiment)
            if score >= MATCH_THRESHOLD:
                row_options.append((experiment_index, score, reasons))
        options.append(row_options)

    best: list[tuple[int, int, int, list[str]]] = []

    def visit(
        gold_index: int,
        used: set[int],
        current: list[tuple[int, int, int, list[str]]],
    ) -> None:
        nonlocal best
        if gold_index == len(gold_rows):
            current_key = (len(current), sum(row[2] for row in current))
            best_key = (len(best), sum(row[2] for row in best))
            if current_key > best_key:
                best = list(current)
            return
        visit(gold_index + 1, used, current)
        for experiment_index, score, reasons in options[gold_index]:
            if experiment_index in used:
                continue
            used.add(experiment_index)
            current.append((gold_index, experiment_index, score, reasons))
            visit(gold_index + 1, used, current)
            current.pop()
            used.remove(experiment_index)

    visit(0, set(), [])
    return best


def evaluate(
    *,
    gold_path: Path = GOLD_PATH,
    inventory_root: Path = INVENTORY_ROOT,
) -> dict:
    with gold_path.open(encoding="utf-8", newline="") as handle:
        gold_rows = list(csv.DictReader(handle))
    by_paper: dict[str, list[dict[str, str]]] = {}
    for row in gold_rows:
        by_paper.setdefault(row["gold_paper_id"], []).append(row)

    papers = []
    total_matched = 0
    for paper_id, paper_gold in sorted(by_paper.items()):
        inventory = ProvisionalExperimentInventoryV12.model_validate_json(
            (inventory_root / paper_id / "inventory.json").read_text(
                encoding="utf-8"
            )
        )
        assignment = _best_assignment(paper_gold, inventory.experiments)
        matched_gold_indexes = {row[0] for row in assignment}
        matched_experiment_indexes = {row[1] for row in assignment}
        total_matched += len(assignment)
        papers.append(
            {
                "paper_id": paper_id,
                "gold_experiment_count": len(paper_gold),
                "provisional_experiment_count": len(inventory.experiments),
                "count_relation": (
                    "exact"
                    if len(paper_gold) == len(inventory.experiments)
                    else (
                        "oversegmented_or_partial_gold"
                        if len(inventory.experiments) > len(paper_gold)
                        else "undersegmented"
                    )
                ),
                "matches": [
                    {
                        "gold_experiment_id": paper_gold[gold_index][
                            "gold_experiment_id"
                        ],
                        "provisional_experiment_id": inventory.experiments[
                            experiment_index
                        ].provisional_experiment_id,
                        "provisional_label": inventory.experiments[
                            experiment_index
                        ].label,
                        "score": score,
                        "reasons": reasons,
                    }
                    for gold_index, experiment_index, score, reasons in assignment
                ],
                "missing_gold_experiment_ids": [
                    row["gold_experiment_id"]
                    for index, row in enumerate(paper_gold)
                    if index not in matched_gold_indexes
                ],
                "unmatched_provisional_experiment_ids": [
                    experiment.provisional_experiment_id
                    for index, experiment in enumerate(inventory.experiments)
                    if index not in matched_experiment_indexes
                ],
            }
        )

    report = {
        "evaluation_version": "provisional-experiment-eval-1.2.0",
        "gold_experiments": len(gold_rows),
        "distinct_gold_groups_matched": total_matched,
        "missing_gold_experiment_ids": [
            identifier
            for paper in papers
            for identifier in paper["missing_gold_experiment_ids"]
        ],
        "known_gold_merge_failures": 0,
        "status": "pass" if total_matched == len(gold_rows) else "fail",
        "precision_note": (
            "Gold experiment annotations are partial. Unmatched provisional "
            "experiments require review and are not automatically false positives."
        ),
        "papers": papers,
    }
    return report


def main() -> None:
    report = evaluate()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
