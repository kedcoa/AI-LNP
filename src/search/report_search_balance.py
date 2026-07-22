from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


INPUT_PATH = Path(
    "data/staging/searches/"
    "deduplicated_papers.jsonl"
)

OUTPUT_PATH = Path(
    "data/staging/searches/"
    "search_balance.json"
)


def main() -> None:
    records = []

    with INPUT_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line in file:
            if line.strip():
                records.append(
                    json.loads(line)
                )

    counts = Counter()

    for record in records:
        for cell in record[
            "matched_cell_types"
        ]:
            counts[cell] += 1

    report = {
        "unique_candidate_papers": len(records),
        "unique_candidates_by_cell": {
            cell: counts[cell]
            for cell in (
                "hepatocyte",
                "kupffer",
                "lsec",
                "hsc",
            )
        },
        "multi_cell_candidates": sum(
            1
            for record in records
            if len(
                record["matched_cell_types"]
            ) > 1
        ),
        "interpretation": (
            "Equal retrieval caps provide equal "
            "search opportunity; they do not guarantee "
            "equal numbers of eligible or unique papers."
        ),
    }

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()