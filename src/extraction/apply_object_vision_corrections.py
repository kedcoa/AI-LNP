"""Apply traceable human corrections without overwriting model output."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .reconstruct_pdf_objects import OUTPUT


OBJECT_ID = "GP-008-pnas.2534673123.sapp-p018-figure-01"


def apply_gp008_s5(source: dict) -> tuple[dict, dict]:
    corrected = deepcopy(source)
    changes: list[dict] = []

    for row in corrected["raw_panel_labels"]:
        if row["panel"] == "H" and row["group"] == "LNP-ZsGreen" and row["label"] == "Q2":
            before = row["value"]
            row["value"] = "9.92"
            changes.append({
                "field": "raw_panel_labels/H/LNP-ZsGreen/Q2/value",
                "before": before,
                "after": "9.92",
                "reason": "High-resolution source figure visibly reads 9.92, not 9.02.",
            })

    for row in corrected["printed_facts"]:
        if row["panel"] == "H" and row["intervention"] == "LNP-ZsGreen" and "Q2" in row["endpoint"]:
            before = {"value": row["value"], "visible_support": row["visible_support"]}
            row["value"] = "9.92"
            row["visible_support"] = "LNP-ZsGreen: Q2 9.92"
            changes.append({
                "field": f"printed_facts/{row['fact_id']}",
                "before": before,
                "after": {"value": "9.92", "visible_support": "LNP-ZsGreen: Q2 9.92"},
                "reason": "High-resolution source figure visibly reads 9.92, not 9.02.",
            })

    old_g = [
        row for row in corrected["raw_panel_labels"]
        if row["panel"] == "G" and row["label_id"] == "G-3"
    ]
    corrected["raw_panel_labels"] = [
        row for row in corrected["raw_panel_labels"]
        if not (row["panel"] == "G" and row["label_id"] == "G-3")
    ]
    channel_rows = []
    for group_index, group in enumerate(("LNP-ZsGreen", "αCD163/LNP-ZsGreen"), 1):
        for channel_index, channel in enumerate(("ZsGreen", "CD163", "DAPI", "Merge"), 1):
            channel_rows.append({
                "label_id": f"G-{group_index}-channel-{channel_index}",
                "panel": "G",
                "group": group,
                "label": channel,
                "value": channel,
                "unit": None,
                "label_type": "legend",
                "visibly_printed": True,
            })
    insert_at = next(
        index for index, row in enumerate(corrected["raw_panel_labels"])
        if row["panel"] == "H"
    )
    corrected["raw_panel_labels"][insert_at:insert_at] = channel_rows
    changes.append({
        "field": "raw_panel_labels/G/channel_assignment",
        "before": old_g,
        "after": channel_rows,
        "reason": (
            "Panel G contains two treatment blocks; each block has ZsGreen, CD163, "
            "DAPI, and Merge views. The model transcribed the channels but left "
            "them unassigned to either group."
        ),
    })

    ledger = {
        "object_id": OBJECT_ID,
        "source_result": f"results/{OBJECT_ID}.validated.json",
        "corrected_result": f"results/{OBJECT_ID}.human_corrected.json",
        "correction_kind": "human_verified_source_read",
        "corrected_at": datetime.now(timezone.utc).isoformat(),
        "changes": changes,
    }
    return corrected, ledger


def run(object_id: str = OBJECT_ID) -> dict:
    if object_id != OBJECT_ID:
        raise ValueError(f"No registered correction for {object_id}")
    result_dir = OUTPUT / "results"
    source_path = result_dir / f"{object_id}.validated.json"
    corrected, ledger = apply_gp008_s5(json.loads(source_path.read_text()))
    corrected_path = result_dir / f"{object_id}.human_corrected.json"
    ledger_path = result_dir / f"{object_id}.corrections.json"
    corrected_path.write_text(json.dumps(corrected, indent=2, ensure_ascii=False) + "\n")
    ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
    return {
        "source_preserved": str(source_path),
        "corrected_result": str(corrected_path),
        "correction_ledger": str(ledger_path),
        "changes": len(ledger["changes"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", default=OBJECT_ID)
    args = parser.parse_args()
    print(json.dumps(run(args.object_id), indent=2))
