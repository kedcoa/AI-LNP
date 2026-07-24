from src.rag.finalize_fulltext_g1 import finalize


def test_final_fulltext_g1_separates_eligibility_and_scientific_graphs():
    result = finalize()
    rows = {row["paper_id"]: row for row in result["papers"]}

    assert result["metrics"]["critical_field_precision"] >= 0.90
    assert result["metrics"]["traceable_evidence_coverage"] == 1.0
    assert result["metrics"]["negative_control_false_positive_papers"] == 0
    assert rows["GP-001"]["eligible_claims"] == 0
    assert rows["GP-003"]["eligible_claims"] == 0
    assert rows["GP-009"]["eligible_claims"] == 0
    assert result["decision"]["g1_overall"] == "pass_with_recall_remediation_required"
