from src.extraction.contracts_v4 import (
    ClaimV4,
    EntityV4,
    EvidenceGraphV4,
    EvidenceSpanV4,
    ExperimentV4,
)
from src.extraction.run_g1_v4 import audit_graph, split_source


def entity(entity_id, entity_type, name, clause="C001"):
    return EntityV4(
        entity_id=entity_id,
        entity_type=entity_type,
        reported_name=name,
        normalized_name=None,
        normalization_status="unresolved",
        evidence=[EvidenceSpanV4(clause_id=clause, quote=name)],
    )


def test_cell_list_must_be_split():
    clauses = split_source("LNPs transfected hepatocytes, endothelial cells and Kupffer cells.")
    graph = EvidenceGraphV4(
        contract_version="4.0.0",
        paper_id="P1",
        source_scope="abstract_only",
        original_lnp_experiments_present=True,
        entities=[
            entity("F1", "lnp_formulation", "LNPs"),
            entity("C1", "cell", "hepatocytes, endothelial cells and Kupffer cells"),
        ],
        claims=[
            ClaimV4(
                claim_id="K1", experiment_id="E1", subject_entity_id="F1",
                predicate="delivered_to_cell", object_entity_id="C1",
                evidence=[EvidenceSpanV4(clause_id="C001", quote="transfected hepatocytes, endothelial cells and Kupffer cells")],
            )
        ],
        experiments=[
            ExperimentV4(
                experiment_id="E1", label="delivery", claim_ids=["K1"],
                source_scope_clause_ids=["C001"], boundary_status="explicit", boundary_reason="reported",
            )
        ],
    )
    assert any(issue["issue"] == "merged_cell_entity" for issue in audit_graph(graph, clauses))


def test_healthy_cannot_be_disease():
    clauses = split_source("LNPs transfected hepatocytes in healthy liver.")
    graph = EvidenceGraphV4(
        contract_version="4.0.0",
        paper_id="P1",
        source_scope="abstract_only",
        original_lnp_experiments_present=True,
        entities=[
            entity("F1", "lnp_formulation", "LNPs"),
            entity("D1", "disease", "healthy liver"),
        ],
        claims=[
            ClaimV4(
                claim_id="K1", experiment_id="E1", subject_entity_id="F1",
                predicate="has_disease_context", object_entity_id="D1",
                evidence=[EvidenceSpanV4(clause_id="C001", quote="healthy liver")],
            )
        ],
        experiments=[
            ExperimentV4(
                experiment_id="E1", label="healthy liver", claim_ids=["K1"],
                source_scope_clause_ids=["C001"], boundary_status="explicit", boundary_reason="reported",
            )
        ],
    )
    assert any(issue["issue"] == "physiology_as_disease" for issue in audit_graph(graph, clauses))


def test_claim_cannot_leak_outside_experiment_scope():
    clauses = split_source("LNPs transfected hepatocytes. LNPs transfected tumor cells.")
    graph = EvidenceGraphV4(
        contract_version="4.0.0",
        paper_id="P1",
        source_scope="abstract_only",
        original_lnp_experiments_present=True,
        entities=[
            entity("F1", "lnp_formulation", "LNPs"),
            entity("C1", "cell", "tumor cells", "C002"),
        ],
        claims=[
            ClaimV4(
                claim_id="K1", experiment_id="E1", subject_entity_id="F1",
                predicate="delivered_to_cell", object_entity_id="C1",
                evidence=[EvidenceSpanV4(clause_id="C002", quote="tumor cells")],
            )
        ],
        experiments=[
            ExperimentV4(
                experiment_id="E1", label="hepatocyte experiment", claim_ids=["K1"],
                source_scope_clause_ids=["C001"], boundary_status="explicit", boundary_reason="reported",
            )
        ],
    )
    assert any(issue["issue"] == "evidence_outside_experiment_scope" for issue in audit_graph(graph, clauses))


def test_relation_requires_subject_and_object_co_evidence():
    clauses = split_source("siMicu1 LNP improved injury. ACT was tested in LSECs.")
    graph = EvidenceGraphV4(
        contract_version="4.0.0",
        paper_id="P1",
        source_scope="abstract_only",
        original_lnp_experiments_present=True,
        entities=[
            entity("F1", "lnp_formulation", "siMicu1 LNP", "C001"),
            entity("C1", "cell", "LSECs", "C002"),
        ],
        claims=[
            ClaimV4(
                claim_id="K1", experiment_id="E1", subject_entity_id="F1",
                predicate="delivered_to_cell", object_entity_id="C1",
                evidence=[EvidenceSpanV4(clause_id="C002", quote="LSECs")],
            )
        ],
        experiments=[
            ExperimentV4(
                experiment_id="E1", label="incorrectly joined experiment", claim_ids=["K1"],
                source_scope_clause_ids=["C001", "C002"], boundary_status="inferred", boundary_reason="model inference",
            )
        ],
    )
    assert any(issue["issue"] == "relation_entities_not_co_supported" for issue in audit_graph(graph, clauses))
