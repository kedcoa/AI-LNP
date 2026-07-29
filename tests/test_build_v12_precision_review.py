import csv
import json

from src.extraction.build_v12_precision_review import run


def test_review_joins_local_evidence_and_requires_human_decisions(tmp_path):
    result_root = tmp_path / "results"
    paper_root = result_root / "GP-X"
    paper_root.mkdir(parents=True)
    (paper_root / "result.json").write_text(json.dumps({
        "paper_id": "GP-X",
        "experiments": [{
            "experiment_id": "E1",
            "payload_name": {"value": "reporter mRNA"},
            "delivery_recipient_cell": {"value": "macrophages"},
            "therapeutic_target_cell": {"value": None},
            "experimental_context": {"value": "in_vivo"},
        }],
        "outcomes": [{
            "outcome_id": "O1",
            "experiment_id": "E1",
            "assay": {"value": "IF", "evidence_ids": ["VLM-1"]},
            "endpoint": {"value": "localization", "evidence_ids": ["VLM-1"]},
            "outcome_value": {"value": None, "evidence_ids": []},
            "outcome_unit": {"value": None, "evidence_ids": []},
            "qualitative_outcome": {
                "value": "localized to macrophages",
                "evidence_ids": ["VLM-1"],
            },
        }],
    }))
    (paper_root / "request.json").write_text(json.dumps({
        "request_payload": {
            "evidence_packet": {"evidence": []},
            "outcome_recall_support": {
                "local_evidence": [{
                    "evidence_id": "VLM-1",
                    "text": "ZsGreen overlaps F4/80 rather than Desmin.",
                }]
            },
        }
    }))
    output = tmp_path / "review"
    manifest = run(result_root=result_root, output_root=output)
    assert manifest["status"] == "pending_human_review"
    with (output / "outcome_review.csv").open() as handle:
        row = next(csv.DictReader(handle))
    assert "ZsGreen overlaps F4/80" in row["evidence_text"]
    assert row["human_supported"] == ""
