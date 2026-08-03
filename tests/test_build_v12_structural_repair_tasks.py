import hashlib
import json

import src.extraction.audit_v12_structural_tasks as auditor
import src.extraction.build_v12_structural_repair_tasks as builder
from src.extraction.build_v12_structural_repair_tasks import build_for_run
from src.extraction.missing_record_contracts import MissingRecordTask
from tests.test_deterministic_coverage_v12 import (
    candidate,
    experiment,
    outcome,
    provisional,
)


def _write_run(
    tmp_path,
    *,
    candidates,
    experiments=None,
    outcomes=None,
    coverage_candidates=None,
    experiment_associations=None,
    accepted_visual_claims=None,
    extra_evidence=None,
):
    run_dir = tmp_path / "GP-X"
    run_dir.mkdir()
    candidates = list(candidates)
    evidence = {
        evidence_id: {
            "evidence_id": evidence_id,
            "text": f"Direct support for {evidence_id}.",
            "source_ids": ["S1"],
        }
        for row in candidates
        for evidence_id in row.evidence_ids
    }
    evidence["E-ANCHOR"] = {
        "evidence_id": "E-ANCHOR",
        "text": "Experiment anchor.",
        "source_ids": ["S1"],
    }
    evidence.update(extra_evidence or {})
    provisional_ids = sorted(
        {
            row.provisional_experiment_id
            for row in candidates
            if row.provisional_experiment_id
        }
    )
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [
            row.model_dump(mode="json") for row in candidates
        ],
        "provisional_experiments": [
            provisional(identifier, identifier.lower())
            for identifier in provisional_ids
        ],
        "accepted_visual_claims": accepted_visual_claims or [],
        "local_evidence": [],
    }
    request = {
        "request_payload": {
            "evidence_packet": {"evidence": list(evidence.values())},
            "outcome_recall_support": support,
        }
    }
    result = {
        "formulations": [{"formulation_id": "F1"}],
        "experiments": experiments or [experiment()],
        "outcomes": outcomes or [outcome()],
    }
    coverage = {
        "candidates": coverage_candidates
        or [
            {
                "candidate_id": row.candidate_id,
                "verdict": "unconfirmed",
                "route": "bounded_repair_task",
            }
            for row in candidates
        ],
        "experiment_associations": experiment_associations or {},
    }
    (run_dir / "request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    (run_dir / "result.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    (run_dir / "v12_structural_coverage.json").write_text(
        json.dumps(coverage), encoding="utf-8"
    )
    return run_dir


def _load_tasks(run_dir):
    return [
        MissingRecordTask.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(
            (run_dir / "structural_repair_tasks").glob("task_*.json")
        )
    ]


def _all_paid_candidate_ids(manifest):
    return {
        candidate_id
        for row in manifest["tasks"]
        for candidate_id in row["candidate_ids"]
    }


def _semantic_run(tmp_path):
    experiments = [
        experiment("EXP-EGFP", "eGFP mRNA"),
        experiment("EXP-HGF-EGF-1", "HGF mRNA"),
        experiment("EXP-HGF-EGF-2", "EGF mRNA"),
    ]
    outcomes = [
        outcome(
            identifier="OUT-EGFP",
            experiment_id="EXP-EGFP",
            endpoint="eGFP expression",
        ),
        outcome(
            identifier="OUT-HGF",
            experiment_id="EXP-HGF-EGF-1",
            endpoint="HGF concentration",
        ),
        outcome(
            identifier="OUT-EGF",
            experiment_id="EXP-HGF-EGF-2",
            endpoint="EGF concentration",
        ),
    ]
    return _write_run(
        tmp_path,
        candidates=[candidate()],
        experiments=experiments,
        outcomes=outcomes,
    )


def _associated_run(tmp_path, candidates):
    return _write_run(
        tmp_path,
        candidates=candidates,
        experiment_associations={
            "EXP1": {
                "status": "associated",
                "provisional_experiment_id": "PEX-EGFP",
            }
        },
    )


def _build_associated_task(tmp_path):
    run_dir = _associated_run(tmp_path, [candidate()])
    build_for_run(run_dir)
    return _load_tasks(run_dir)[0]


def test_task_contains_semantic_summaries_for_every_existing_experiment(
    tmp_path,
):
    run_dir = _semantic_run(tmp_path)
    build_for_run(run_dir)
    task = _load_tasks(run_dir)[0]
    assert {
        row.experiment_id for row in task.existing_experiment_summaries
    } == {
        "EXP-EGFP",
        "EXP-HGF-EGF-1",
        "EXP-HGF-EGF-2",
    }
    assert task.existing_experiment_summaries[0].payload_name is not None
    assert {
        row.outcome_id for row in task.existing_outcome_summaries
    } == {"OUT-EGFP", "OUT-HGF", "OUT-EGF"}


def test_associated_provisional_experiment_still_permits_bounded_new_experiment(
    tmp_path,
):
    task = _build_associated_task(tmp_path)

    assert task.permitted_new_experiments == 1


def test_repacking_accounts_for_new_experiment_output_allowance(tmp_path):
    candidates = [
        candidate(
            candidate_id=f"AOC-{index}",
            claim_ids=[f"ACL-{index}"],
            evidence_ids=[f"E-{index}"],
        )
        for index in range(1, 6)
    ]

    manifest = build_for_run(_associated_run(tmp_path, candidates))

    assert all(
        row["estimated_worst_case_output_tokens"] <= 4_000
        for row in manifest["tasks"]
    )
    assert sum(row["candidate_count"] for row in manifest["tasks"]) == 5


def test_dynamic_packing_spills_before_measured_token_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        builder,
        "estimate_input_tokens",
        lambda task, model: (
            5_900 if len(task.candidate_ids) <= 2 else 6_100
        ),
    )
    candidates = [
        candidate(
            candidate_id=f"AOC-{index}",
            claim_ids=[f"ACL-{index}"],
            evidence_ids=[f"E-{index}"],
        )
        for index in range(1, 5)
    ]
    manifest = build_for_run(_write_run(tmp_path, candidates=candidates))
    assert [row["candidate_count"] for row in manifest["tasks"]] == [2, 2]
    assert [
        row["estimated_input_tokens"] for row in manifest["tasks"]
    ] == [5_900, 5_900]


def test_rebuild_removes_stale_task_files_after_batch_count_shrinks(
    tmp_path, monkeypatch
):
    candidates = [
        candidate(
            candidate_id=f"AOC-{index}",
            claim_ids=[f"ACL-{index}"],
            evidence_ids=[f"E-{index}"],
        )
        for index in range(1, 5)
    ]
    run_dir = _write_run(tmp_path, candidates=candidates)
    monkeypatch.setattr(
        builder,
        "estimate_input_tokens",
        lambda task, model: (
            5_900 if len(task.candidate_ids) <= 2 else 6_100
        ),
    )
    build_for_run(run_dir)
    assert len(_load_tasks(run_dir)) == 2

    monkeypatch.setattr(
        builder, "estimate_input_tokens", lambda task, model: 2_000
    )
    manifest = build_for_run(run_dir)
    assert manifest["task_count"] == 1
    assert [
        path.name
        for path in sorted(
            (run_dir / "structural_repair_tasks").glob("task_*.json")
        )
    ] == ["task_01.json"]


def test_text_and_visual_candidates_never_share_a_task(tmp_path, monkeypatch):
    monkeypatch.setattr(
        builder, "estimate_input_tokens", lambda task, model: 2_000
    )
    text = candidate(
        candidate_id="AOC-TEXT",
        claim_ids=["ACL-TEXT"],
        evidence_ids=["E-TEXT"],
    )
    visual = candidate(
        candidate_id="AOC-VISUAL",
        claim_ids=["ACL-VISUAL"],
        evidence_ids=["E-VISUAL"],
        source_ids=["FIGURE-1"],
        route_hint="vision",
    )
    manifest = build_for_run(
        _write_run(tmp_path, candidates=[text, visual])
    )
    assert {row["repair_route"] for row in manifest["tasks"]} == {
        "text",
        "vision",
    }
    assert all(
        not (
            set(row["candidate_ids"])
            & set(manifest["visual_candidate_ids"])
        )
        for row in manifest["tasks"]
        if row["repair_route"] == "text"
    )
    vision_row = next(
        row for row in manifest["tasks"] if row["repair_route"] == "vision"
    )
    assert vision_row["visual_object_id"] == "FIGURE-1"


def test_visual_table_cells_pack_by_shared_object_id(tmp_path, monkeypatch):
    monkeypatch.setattr(
        builder, "estimate_input_tokens", lambda task, model: 2_000
    )
    rows = [
        candidate(
            candidate_id=f"AOC-VISUAL-{index}",
            claim_ids=[f"ACL-VISUAL-{index}"],
            evidence_ids=[f"E-VISUAL-{index}"],
            source_ids=[
                f"TABLE-OBJECT:table-0:r1:c{index}"
            ],
            route_hint="vision",
        )
        for index in (1, 2)
    ]
    manifest = build_for_run(_write_run(tmp_path, candidates=rows))
    assert manifest["task_count"] == 1
    assert manifest["tasks"][0]["candidate_count"] == 2
    assert manifest["tasks"][0]["visual_object_id"] == "TABLE-OBJECT"


def test_candidate_that_cannot_fit_alone_goes_to_human_review(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        builder, "estimate_input_tokens", lambda task, model: 6_001
    )
    oversized = candidate(
        candidate_id="AOC-OVERSIZED",
        claim_ids=["ACL-OVERSIZED"],
    )
    manifest = build_for_run(
        _write_run(tmp_path, candidates=[oversized])
    )
    assert manifest["oversized_candidate_ids"] == ["AOC-OVERSIZED"]
    assert "AOC-OVERSIZED" not in _all_paid_candidate_ids(manifest)


def test_audit_conserves_text_visual_oversized_human_and_confirmed_scope(
    tmp_path, monkeypatch
):
    rows = [
        candidate(
            candidate_id="AOC-TEXT",
            claim_ids=["ACL-TEXT"],
            evidence_ids=["E-TEXT"],
        ),
        candidate(
            candidate_id="AOC-VISUAL",
            claim_ids=["ACL-VISUAL"],
            evidence_ids=["E-VISUAL"],
            source_ids=["FIGURE-1"],
            route_hint="vision",
        ),
        candidate(
            candidate_id="AOC-OVERSIZED",
            claim_ids=["ACL-OVERSIZED"],
            evidence_ids=["E-OVERSIZED"],
        ),
        candidate(
            candidate_id="AOC-HUMAN",
            claim_ids=["ACL-HUMAN"],
            evidence_ids=["E-HUMAN"],
        ),
        candidate(
            candidate_id="AOC-CONFIRMED",
            claim_ids=["ACL-CONFIRMED"],
            evidence_ids=["E-CONFIRMED"],
        ),
    ]
    routes = {
        "AOC-TEXT": ("unconfirmed", "bounded_repair_task"),
        "AOC-VISUAL": ("unconfirmed", "bounded_repair_task"),
        "AOC-OVERSIZED": ("unconfirmed", "bounded_repair_task"),
        "AOC-HUMAN": ("contradicted", "human_review"),
        "AOC-CONFIRMED": ("confirmed", "none"),
    }
    run_dir = _write_run(
        tmp_path,
        candidates=rows,
        coverage_candidates=[
            {
                "candidate_id": row.candidate_id,
                "verdict": routes[row.candidate_id][0],
                "route": routes[row.candidate_id][1],
            }
            for row in rows
        ],
    )
    monkeypatch.setattr(
        builder,
        "estimate_input_tokens",
        lambda task, model: (
            6_001
            if "AOC-OVERSIZED" in task.candidate_ids
            else 2_000
        ),
    )
    build_for_run(run_dir)
    unsigned = {"paper_id": "GP-X", "task_count": 2}
    serialized = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    preparation = {
        **unsigned,
        "manifest_checksum": hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest(),
    }
    (run_dir / "preparation_manifest.json").write_text(
        json.dumps(preparation), encoding="utf-8"
    )
    report = auditor.audit(tmp_path)
    assert report["passed"], report["issues"]
    paper = report["papers"][0]
    assert paper["text_task_candidate_count"] == 1
    assert paper["vision_task_candidate_count"] == 1
    assert paper["oversized_candidate_count"] == 1
    assert paper["human_review_candidate_count"] == 1
    assert paper["confirmed_candidate_count"] == 1


def test_audit_recomputes_exact_request_size_instead_of_trusting_manifest(
    tmp_path, monkeypatch
):
    run_dir = _write_run(tmp_path, candidates=[candidate()])
    monkeypatch.setattr(
        builder, "estimate_input_tokens", lambda task, model: 2_000
    )
    build_for_run(run_dir)
    unsigned = {"paper_id": "GP-X"}
    serialized = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    (run_dir / "preparation_manifest.json").write_text(
        json.dumps(
            {
                **unsigned,
                "manifest_checksum": hashlib.sha256(
                    serialized.encode("utf-8")
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        auditor,
        "estimate_input_tokens",
        lambda task, model: 6_001,
        raising=False,
    )
    report = auditor.audit(tmp_path)
    assert "GP-X:task_01.json:actual_input_token_cap_exceeded" in report[
        "issues"
    ]


def test_audit_rejects_wrong_visual_object_partition_metadata(
    tmp_path, monkeypatch
):
    visual = candidate(
        candidate_id="AOC-VISUAL",
        claim_ids=["ACL-VISUAL"],
        evidence_ids=["E-VISUAL"],
        source_ids=["FIGURE-1"],
        route_hint="vision",
    )
    run_dir = _write_run(tmp_path, candidates=[visual])
    monkeypatch.setattr(
        builder, "estimate_input_tokens", lambda task, model: 2_000
    )
    build_for_run(run_dir)
    manifest_path = run_dir / "structural_repair_tasks/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tasks"][0]["visual_object_id"] = "FIGURE-WRONG"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    unsigned = {"paper_id": "GP-X"}
    serialized = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    (run_dir / "preparation_manifest.json").write_text(
        json.dumps(
            {
                **unsigned,
                "manifest_checksum": hashlib.sha256(
                    serialized.encode("utf-8")
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    report = auditor.audit(tmp_path)
    assert "GP-X:task_01.json:visual_object_scope_mismatch" in report[
        "issues"
    ]


def test_audit_reports_unknown_task_candidate_without_crashing(
    tmp_path, monkeypatch
):
    row = candidate(candidate_id="AOC-UNKNOWN")
    run_dir = _write_run(tmp_path, candidates=[row])
    monkeypatch.setattr(
        builder, "estimate_input_tokens", lambda task, model: 2_000
    )
    build_for_run(run_dir)
    request_path = run_dir / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["request_payload"]["outcome_recall_support"][
        "atomic_outcome_candidates"
    ] = []
    request_path.write_text(json.dumps(request), encoding="utf-8")
    unsigned = {"paper_id": "GP-X"}
    serialized = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    (run_dir / "preparation_manifest.json").write_text(
        json.dumps(
            {
                **unsigned,
                "manifest_checksum": hashlib.sha256(
                    serialized.encode("utf-8")
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    report = auditor.audit(tmp_path)

    assert not report["passed"]
    assert "GP-X:task_01.json:unknown_candidate:AOC-UNKNOWN" in report[
        "issues"
    ]


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
    assert by_experiment["PEX-EGFP"]["permitted_new_experiments"] == 1
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
