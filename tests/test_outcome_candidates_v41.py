import pytest
from pydantic import ValidationError

from src.extraction.contracts_v4 import EvidenceGraphV4, SourceClauseV4
from src.extraction.outcome_contracts_v41 import (
    CandidateDispositionV41,
    GraphPatchV41,
    MechanismStepV41,
    OutcomeSidecarV41,
    apply_graph_patch,
)
from src.rag.result_candidates import (
    pending_sidecar,
    split_result_candidates,
    validate_candidate_cardinality,
    validate_sidecar_against_graph,
)


def clause(text):
    return SourceClauseV4(clause_id="B001C001", sentence_id="B001S001", text=text)


def graph():
    return EvidenceGraphV4.model_validate({
        "contract_version": "4.0.0",
        "paper_id": "GP-T",
        "source_scope": "full_text",
        "original_lnp_experiments_present": True,
        "entities": [
            {"entity_id": "A", "entity_type": "assay", "reported_name": "assay",
             "normalization_status": "exact", "evidence": [{"clause_id": "B001C001", "quote": "assay result"}]},
            {"entity_id": "E", "entity_type": "endpoint", "reported_name": "expression",
             "normalization_status": "exact", "evidence": [{"clause_id": "B001C001", "quote": "assay result"}]},
        ],
        "claims": [{"claim_id": "C1", "experiment_id": "X1", "subject_entity_id": "A",
                    "predicate": "measures_endpoint", "object_entity_id": "E",
                    "evidence": [{"clause_id": "B001C001", "quote": "assay result"}]}],
        "experiments": [{"experiment_id": "X1", "label": "test", "claim_ids": ["C1"],
                         "shared_claim_ids": [], "source_scope_clause_ids": ["B001C001"],
                         "boundary_status": "explicit", "boundary_reason": "test"}],
    })


def test_splits_numeric_and_population_specific_qualitative_results():
    rows = split_result_candidates([clause(
        "41.5% of CD11b+ cells expressed eGFP, while few F4/80+ Kupffer cells expressed eGFP."
    )])
    assert [row.value_text for row in rows] == ["41.5%", "few"]
    assert rows[0].population == "CD11b+ cells"
    assert "Kupffer" in rows[1].population


def test_preserves_negative_detection_and_hepatocyte_contrast():
    rows = split_result_candidates([clause(
        "No obvious EGFP-positive Kupffer cells were observed, whereas expression was observed solely in hepatocytes."
    )])
    assert len(rows) == 2
    assert rows[0].polarity == "negative"
    assert rows[0].detection_status == "below_detection"
    assert rows[1].population == "hepatocytes"


def test_numeric_cardinality_is_complete():
    source = [clause("Expression was 41.5% in CD11b+ cells and 7.2% in hepatocytes.")]
    rows = split_result_candidates(source)
    assert validate_candidate_cardinality(source, rows) == []
    assert len(rows) == 2


def test_every_candidate_requires_exactly_one_disposition():
    sidecar = pending_sidecar("GP-T", [clause("Few Kupffer cells expressed eGFP.")])
    with pytest.raises(ValidationError):
        OutcomeSidecarV41(paper_id="GP-T", candidates=sidecar.candidates, dispositions=[])


def test_retained_disposition_requires_outcome_claim():
    sidecar = pending_sidecar("GP-T", [clause("Few Kupffer cells expressed eGFP.")])
    sidecar = sidecar.model_copy(update={"dispositions": [
        CandidateDispositionV41(candidate_id=sidecar.candidates[0].candidate_id,
                                status="retained", claim_id="C1", reason="mapped")
    ]})
    findings = validate_sidecar_against_graph(sidecar, graph())
    assert findings[0]["issue"] == "retained_candidate_wrong_predicate"


def test_atomic_patch_adds_valid_outcome_and_experiment_link():
    patch = GraphPatchV41.model_validate({
        "paper_id": "GP-T",
        "add_entities": [{"entity_id": "V", "entity_type": "outcome_value",
                          "reported_name": "few positive cells", "normalization_status": "exact",
                          "evidence": [{"clause_id": "B001C001", "quote": "assay result"}]}],
        "add_claims": [{"claim_id": "C2", "experiment_id": "X1",
                        "subject_entity_id": "E", "predicate": "has_outcome_value",
                        "object_entity_id": "V",
                        "evidence": [{"clause_id": "B001C001", "quote": "assay result"}]}],
        "experiment_claim_additions": [{"experiment_id": "X1", "claim_ids": ["C2"]}],
    })
    updated = apply_graph_patch(graph(), patch)
    assert updated.experiments[0].claim_ids == ["C1", "C2"]


def test_atomic_patch_rejects_dangling_experiment_claim():
    patch = GraphPatchV41.model_validate({
        "paper_id": "GP-T",
        "experiment_claim_additions": [{"experiment_id": "X1", "claim_ids": ["missing"]}],
    })
    with pytest.raises(ValueError, match="unknown claim_id"):
        apply_graph_patch(graph(), patch)


def test_multi_step_mechanism_keeps_effector_and_target_distinct():
    steps = [
        MechanismStepV41(step_number=1, subject="LNP", action="delivers FAPCAR to",
                         object="macrophage", subject_role="formulation",
                         object_role="recipient_cell",
                         evidence=[{"clause_id": "B001C001", "quote": "assay result"}]),
        MechanismStepV41(step_number=2, subject="FAPCAR macrophage", action="eliminates",
                         object="activated HSC", subject_role="effector_cell",
                         object_role="therapeutic_target",
                         evidence=[{"clause_id": "B001C001", "quote": "assay result"}]),
    ]
    assert steps[0].object_role != steps[1].object_role
