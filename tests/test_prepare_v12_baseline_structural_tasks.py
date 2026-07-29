import json

from src.extraction.prepare_v12_baseline_structural_tasks import run


def test_prepares_three_frozen_baselines_without_paid_calls(tmp_path):
    output_root = tmp_path / "prepared"
    report = run(
        ["GP-004", "GP-006", "GP-008"],
        output_root=output_root,
        report_path=tmp_path / "summary.json",
    )

    assert report["paid_api_requests"] == 0
    assert report["generation_requests"] == 0
    assert not report["ready_for_paid_calls"]
    for paper_id in ("GP-004", "GP-006", "GP-008"):
        run_dir = output_root / paper_id
        assert (run_dir / "request.json").exists()
        assert (run_dir / "result.json").exists()
        assert (run_dir / "v12_structural_coverage.json").exists()
        manifest = json.loads(
            (run_dir / "structural_repair_tasks/manifest.json").read_text()
        )
        assert manifest["paid_api_requests"] == 0
        for index in range(1, manifest["task_count"] + 1):
            task = json.loads(
                (
                    run_dir
                    / "structural_repair_tasks"
                    / f"task_{index:02d}.json"
                ).read_text()
            )
            assert task["task_version"] == "missing-record-task-1.1.0"
            assert task["experiment_context"]
            assert {row["candidate_id"] for row in task["candidate_facts"]} == set(
                task["candidate_ids"]
            )
        assert not any(
            value.startswith(("GO-", "GX-"))
            for task in manifest["tasks"]
            for value in task["candidate_ids"]
        )
