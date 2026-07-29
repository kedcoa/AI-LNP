from src.extraction.freeze_g1_v3_boundaries import freeze


def test_all_human_boundary_decisions_freeze():
    report = freeze()
    assert len(report["papers"]) == 4
    assert sum(row["experiments"] for row in report["papers"]) > 4
    assert report["status"] == "ready_for_experiment_scoped_extraction"
