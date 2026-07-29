from unittest.mock import patch

import pytest

from src.extraction.contracts_v4 import EvidenceGraphV4, SourceClauseV4
from src.rag.run_experiment_extraction import (
    audit_rag_graph,
    is_confirmed_negative_control,
    outcome_candidate_clauses,
    provider_configuration,
    prune_unsupported_relations,
    repair_non_verbatim_quotes,
)


def test_openai_provider_uses_openai_credentials():
    values = {
        "RAG_LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "test-openai-key",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "RAG_EXTRACTION_MODEL": "extractor-test",
        "RAG_VERIFIER_MODEL": "verifier-test",
    }
    with patch.dict("os.environ", values, clear=True):
        provider, extractor, verifier, client = provider_configuration()
    assert provider == "openai"
    assert extractor == "extractor-test"
    assert verifier == "verifier-test"
    assert str(client.base_url) == "https://api.openai.com/v1/"


def test_unknown_provider_is_rejected():
    with patch.dict("os.environ", {"RAG_LLM_PROVIDER": "unknown"}, clear=True):
        with pytest.raises(ValueError, match="Unsupported RAG_LLM_PROVIDER"):
            provider_configuration()


def test_negative_control_requires_empty_graph_and_empty_human_inventory():
    graph = EvidenceGraphV4.model_validate({
        "contract_version": "4.0.0",
        "paper_id": "GP-X",
        "source_scope": "full_text",
        "original_lnp_experiments_present": False,
        "entities": [],
        "claims": [],
        "experiments": [],
    })
    assert is_confirmed_negative_control(graph, {"experiments": []})
    assert not is_confirmed_negative_control(
        graph, {"experiments": [{"experiment_id": "human-approved"}]}
    )


def test_non_verbatim_quote_is_replaced_by_exact_cited_clause():
    graph = EvidenceGraphV4.model_validate({
        "contract_version": "4.0.0",
        "paper_id": "GP-X",
        "source_scope": "full_text",
        "original_lnp_experiments_present": False,
        "entities": [{
            "entity_id": "P1", "entity_type": "payload",
            "reported_name": "Cas9 mRNA", "normalization_status": "exact",
            "evidence": [{"clause_id": "C1", "quote": "Cas9 mRNA"}],
        }],
        "claims": [],
        "experiments": [],
    })
    repaired = repair_non_verbatim_quotes(
        graph,
        [SourceClauseV4(
            clause_id="C1",
            sentence_id="S1",
            text="The payload was Cas9\u00a0mRNA.",
        )],
    )
    assert repaired.entities[0].evidence[0].quote == "The payload was Cas9\u00a0mRNA."


def test_rag_audit_accepts_relation_evidence_within_same_source_block():
    graph = EvidenceGraphV4.model_validate({
        "contract_version": "4.0.0",
        "paper_id": "GP-X",
        "source_scope": "full_text",
        "original_lnp_experiments_present": True,
        "entities": [
            {
                "entity_id": "F1", "entity_type": "lnp_formulation",
                "reported_name": "test LNP", "normalization_status": "exact",
                "evidence": [{"clause_id": "C2", "quote": "test LNP"}],
            },
            {
                "entity_id": "C1", "entity_type": "lnp_component",
                "reported_name": "cholesterol", "normalization_status": "exact",
                "evidence": [{"clause_id": "C1", "quote": "cholesterol"}],
            },
        ],
        "claims": [{
            "claim_id": "CL1", "experiment_id": "E1",
            "subject_entity_id": "F1", "predicate": "has_component",
            "object_entity_id": "C1",
            "evidence": [{"clause_id": "C1", "quote": "cholesterol"}],
        }],
        "experiments": [{
            "experiment_id": "E1", "label": "test", "claim_ids": ["CL1"],
            "shared_claim_ids": [], "source_scope_clause_ids": ["C1", "C2"],
            "boundary_status": "explicit", "boundary_reason": "test",
        }],
    })
    clauses = [
        SourceClauseV4(clause_id="C1", sentence_id="S1", text="cholesterol"),
        SourceClauseV4(clause_id="C2", sentence_id="S2", text="test LNP"),
    ]
    provenance = {
        "C1": {"block_id": "B1"},
        "C2": {"block_id": "B1"},
    }
    assert audit_rag_graph(graph, clauses, provenance) == []


def test_rag_audit_flags_missing_inventory_experiment():
    graph = EvidenceGraphV4.model_validate({
        "contract_version": "4.0.0",
        "paper_id": "GP-X",
        "source_scope": "full_text",
        "original_lnp_experiments_present": False,
        "entities": [],
        "claims": [],
        "experiments": [],
    })
    findings = audit_rag_graph(
        graph,
        [],
        {},
        {"experiments": [{"experiment_id": "GP-X-E01"}]},
    )
    assert findings[0]["issue"] == "missing_inventory_experiment"
    assert findings[0]["owner"] == "GP-X-E01"


def test_outcome_candidate_clauses_cover_the_complete_consumed_packet():
    clauses = [
        SourceClauseV4(
            clause_id="C1", sentence_id="S1",
            text="No obvious EGFP-positive Kupffer cells were detected.",
        ),
        SourceClauseV4(
            clause_id="C2", sentence_id="S2",
            text="The formulation contained cholesterol.",
        ),
    ]
    provenance = {
        "C1": {"retrieval_fields": ["outcomes"]},
        "C2": {"retrieval_fields": ["formulation"]},
    }
    assert outcome_candidate_clauses(clauses, provenance) == [{
        "clause_id": "C1",
        "text": "No obvious EGFP-positive Kupffer cells were detected.",
    }]


def test_prune_unsupported_relation_removes_claim_and_experiment_link():
    graph = EvidenceGraphV4.model_validate({
        "contract_version": "4.0.0",
        "paper_id": "GP-X",
        "source_scope": "full_text",
        "original_lnp_experiments_present": True,
        "entities": [
            {
                "entity_id": "I1", "entity_type": "intervention",
                "reported_name": "intervention", "normalization_status": "exact",
                "evidence": [{"clause_id": "C1", "quote": "intervention"}],
            },
            {
                "entity_id": "F1", "entity_type": "lnp_formulation",
                "reported_name": "LNP", "normalization_status": "exact",
                "evidence": [{"clause_id": "C2", "quote": "LNP"}],
            },
        ],
        "claims": [
            {
                "claim_id": "CL1", "experiment_id": "E1",
                "subject_entity_id": "I1", "predicate": "has_formulation",
                "object_entity_id": "F1",
                "evidence": [{"clause_id": "C1", "quote": "intervention"}],
            },
            {
                "claim_id": "CL2", "experiment_id": "E1",
                "subject_entity_id": "I1", "predicate": "compared_with",
                "object_entity_id": "I1",
                "evidence": [{"clause_id": "C1", "quote": "intervention"}],
            },
        ],
        "experiments": [{
            "experiment_id": "E1", "label": "test", "claim_ids": ["CL1", "CL2"],
            "shared_claim_ids": [], "source_scope_clause_ids": ["C1", "C2"],
            "boundary_status": "explicit", "boundary_reason": "test",
        }],
    })
    pruned, removed = prune_unsupported_relations(graph, [{
        "owner": "CL1", "issue": "relation_entities_not_co_supported",
        "detail": "not co-supported",
    }])
    assert removed == ["CL1"]
    assert [row.claim_id for row in pruned.claims] == ["CL2"]
    assert pruned.experiments[0].claim_ids == ["CL2"]


def test_prune_schema_invalid_relation():
    graph = EvidenceGraphV4.model_validate({
        "contract_version": "4.0.0",
        "paper_id": "GP-X",
        "source_scope": "full_text",
        "original_lnp_experiments_present": True,
        "entities": [
            {
                "entity_id": "A1", "entity_type": "route",
                "reported_name": "route", "normalization_status": "exact",
                "evidence": [{"clause_id": "C1", "quote": "route"}],
            },
            {
                "entity_id": "E1", "entity_type": "endpoint",
                "reported_name": "endpoint", "normalization_status": "exact",
                "evidence": [{"clause_id": "C1", "quote": "endpoint"}],
            },
        ],
        "claims": [{
            "claim_id": "CL1", "experiment_id": "X1",
            "subject_entity_id": "A1", "predicate": "measures_endpoint",
            "object_entity_id": "E1",
            "evidence": [{"clause_id": "C1", "quote": "assay endpoint"}],
        }],
        "experiments": [{
            "experiment_id": "X1", "label": "test", "claim_ids": ["CL1"],
            "shared_claim_ids": [], "source_scope_clause_ids": ["C1"],
            "boundary_status": "explicit", "boundary_reason": "test",
        }],
    })
    pruned, removed = prune_unsupported_relations(graph, [{
        "owner": "CL1", "issue": "predicate_type_violation",
        "detail": "route --measures_endpoint--> endpoint",
    }])
    assert removed == ["CL1"]
    assert pruned.claims == []
    assert pruned.experiments == []
