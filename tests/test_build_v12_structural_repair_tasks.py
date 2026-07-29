import json

from src.extraction.build_v12_structural_repair_tasks import build_for_run
from tests.test_deterministic_coverage_v12 import (
    candidate,
    experiment,
    outcome,
    provisional,
)


def test_tasks_are_grouped_by_provisional_experiment_not_shared_source(tmp_path):
    run_dir = tmp_path / "GP-X"
    run_dir.mkdir()
    first = candidate(
        candidate_id="AOC-1",
        claim_ids=["ACL-1"],
        provisional_experiment_id="PEX-EGFP",
        evidence_ids=["E-SHARED"],
    )
    second = candidate(
        candidate_id="AOC-2",
        claim_ids=["ACL-2"],
        provisional_experiment_id="PEX-OTHER",
        evidence_ids=["E-SHARED"],
    )
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [
            first.model_dump(mode="json"),
            second.model_dump(mode="json"),
        ],
        "provisional_experiments": [
            provisional(),
            provisional("PEX-OTHER", "hgf_egf"),
        ],
        "local_evidence": [],
    }
    request = {
        "request_payload": {
            "evidence_packet": {
                "evidence": [
                    {
                        "evidence_id": "E-SHARED",
                        "text": "Direct result.",
                        "source_ids": ["S1"],
                    }
                ]
            },
            "outcome_recall_support": support,
        }
    }
    result = {
        "formulations": [{"formulation_id": "F1"}],
        "experiments": [experiment()],
        "outcomes": [outcome()],
    }
    coverage = {
        "candidates": [
            {
                "candidate_id": "AOC-1",
                "verdict": "unconfirmed",
                "route": "bounded_repair_task",
            },
            {
                "candidate_id": "AOC-2",
                "verdict": "unconfirmed",
                "route": "bounded_repair_task",
            },
        ],
        "experiment_associations": {
            "EXP1": {
                "status": "associated",
                "provisional_experiment_id": "PEX-EGFP",
            }
        },
    }
    (run_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (run_dir / "v12_structural_coverage.json").write_text(
        json.dumps(coverage), encoding="utf-8"
    )
    manifest = build_for_run(run_dir)
    assert manifest["task_count"] == 2
    by_experiment = {
        row["provisional_experiment_id"]: row for row in manifest["tasks"]
    }
    assert by_experiment["PEX-EGFP"]["permitted_new_experiments"] == 0
    assert by_experiment["PEX-OTHER"]["permitted_new_experiments"] == 1
    assert manifest["paid_api_requests"] == 0


def test_human_review_candidates_never_enter_paid_repair_queue(tmp_path):
    run_dir = tmp_path / "GP-X"
    run_dir.mkdir()
    row = candidate()
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [row.model_dump(mode="json")],
        "provisional_experiments": [provisional()],
        "local_evidence": [],
    }
    request = {
        "request_payload": {
            "evidence_packet": {"evidence": []},
            "outcome_recall_support": support,
        }
    }
    result = {
        "formulations": [{"formulation_id": "F1"}],
        "experiments": [],
        "outcomes": [],
    }
    coverage = {
        "candidates": [
            {
                "candidate_id": row.candidate_id,
                "verdict": "contradicted",
                "route": "human_review",
            }
        ],
        "experiment_associations": {},
    }
    (run_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (run_dir / "v12_structural_coverage.json").write_text(
        json.dumps(coverage), encoding="utf-8"
    )
    manifest = build_for_run(run_dir)
    assert manifest["task_count"] == 0
    assert manifest["human_review_candidate_ids"] == [row.candidate_id]
