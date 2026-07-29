import json

from src.extraction.run_compact_one_call import load_packet
from src.extraction.v12_main_route import (
    _atomic_claim_evidence,
    _visual_candidates,
    allowed_v12_evidence_ids,
    build_v12_route_support,
    evaluate_v12_result_coverage,
    evaluate_v12_structural_result_coverage,
)


def test_development_support_is_gold_blind_and_carries_omitted_evidence():
    support = build_v12_route_support(load_packet("GP-004"))
    serialized = json.dumps(support)
    assert "GO-" not in serialized
    assert "GX-" not in serialized
    assert support["atomic_outcome_candidates"]
    assert support["local_evidence"]
    assert any(
        "ALT" in " ".join(
            str(row.get(field) or "")
            for field in (
                "subject_text",
                "object_text",
                "endpoint_text",
                "qualitative_result",
            )
        )
        for row in support["atomic_outcome_candidates"]
    )
    assert allowed_v12_evidence_ids(support) == {
        row["evidence_id"] for row in support["local_evidence"]
    }


def test_result_coverage_requires_promoted_visual_evidence_citation():
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [],
        "accepted_visual_claims": [{"evidence_id": "VLM-1"}],
    }
    missing = evaluate_v12_result_coverage(support, {"outcomes": []})
    assert missing["status"] == "review_unmatched_support"
    found = evaluate_v12_result_coverage(support, {
        "outcomes": [{
            "qualitative_outcome": {
                "value": "localized",
                "status": "reported",
                "evidence_ids": ["VLM-1"],
                "missing_reason": None,
            }
        }]
    })
    assert found["status"] == "complete"


def test_structural_coverage_fails_closed_without_an_experiment_join():
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [
            {
                "candidate_id": "AOC-1",
                "paper_id": "GP-X",
                "claim_ids": ["ACL-1"],
                "provisional_experiment_id": "PEX-1",
                "subject_text": "F4/80-positive Kupffer cells",
                "predicate": "expressed",
                "object_text": "eGFP",
                "endpoint_text": "eGFP expression",
                "qualitative_result": "few",
                "numeric_value": None,
                "value_text": None,
                "unit": None,
                "polarity": "positive",
                "evidence_ids": ["E1"],
                "source_ids": ["S1"],
                "route_hint": "text",
                "confidence": "high",
                "review_reasons": [],
                "structural_signature": "x",
            }
        ],
        "provisional_experiments": [
            {
                "provisional_experiment_id": "PEX-1",
                "anchors": [
                    {
                        "anchor_type": "payload",
                        "value": "egfp_gfp",
                        "evidence_ids": ["E1"],
                    }
                ],
            }
        ],
    }
    report = evaluate_v12_structural_result_coverage(
        support,
        {"experiments": [], "outcomes": []},
    )
    assert report["status"] == "review_unconfirmed_or_contradicted_facts"
    assert report["routes"]["bounded_repair_task"] == 1
    assert report["paid_api_requests"] == 0


def test_shared_source_evidence_preserves_every_atomic_clause(
    tmp_path, monkeypatch
):
    atomic_root = tmp_path / "atomic"
    paper_root = atomic_root / "GP-X"
    paper_root.mkdir(parents=True)
    (paper_root / "claims.json").write_text(
        json.dumps(
            [
                {
                    "evidence": [
                        {
                            "evidence_id": "E-SHARED",
                            "source_id": "S1",
                            "quote": "PCNA expression increased in HSCs.",
                        }
                    ]
                },
                {
                    "evidence": [
                        {
                            "evidence_id": "E-SHARED",
                            "source_id": "S1",
                            "quote": "PCNA expression was absent in hepatocytes.",
                        }
                    ]
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.extraction.v12_main_route.ATOMIC_ROOT", atomic_root
    )

    row = _atomic_claim_evidence("GP-X")["E-SHARED"]
    assert row["quotes"] == [
        "PCNA expression increased in HSCs.",
        "PCNA expression was absent in hepatocytes.",
    ]


def test_accepted_visual_claim_becomes_a_structurally_graded_candidate(
    tmp_path, monkeypatch
):
    experiment_root = tmp_path / "experiments"
    paper_root = experiment_root / "GP-X"
    paper_root.mkdir(parents=True)
    inventory = {
        "inventory_version": "provisional-experiments-1.2.0",
        "paper_id": "GP-X",
        "source_packet_checksum": "a" * 64,
        "experiments": [
            {
                "provisional_experiment_id": "PEX-GP-X-zsgreen",
                "label": "luciferase_zsgreen / in_vivo",
                "anchors": [
                    {
                        "anchor_type": "payload",
                        "value": "luciferase_zsgreen",
                        "evidence_ids": ["E1"],
                    },
                    {
                        "anchor_type": "model",
                        "value": "in_vivo",
                        "evidence_ids": ["E1"],
                    },
                ],
                "claim_ids": [],
                "shared_context_claim_ids": [],
                "boundary_status": "inferred",
                "boundary_reason": "distinct payload and model",
                "confidence": "medium",
            }
        ],
        "unassigned_claim_ids": [],
        "validation_notes": [],
    }
    (paper_root / "inventory.json").write_text(
        json.dumps(inventory), encoding="utf-8"
    )
    monkeypatch.setattr(
        "src.extraction.v12_main_route.EXPERIMENT_ROOT",
        experiment_root,
    )
    rows = _visual_candidates(
        "GP-X",
        [
            {
                "evidence_id": "VLM-1",
                "object_id": "FIG-1",
                "claim": {
                    "claim_id": "VCL-1",
                    "subject": "αCD163/LNP-ZsGreen",
                    "predicate": "co-staining with F4/80+ macrophages",
                    "endpoint": None,
                    "value": (
                        "F4/80+ cells show higher ZsGreen-positive percentage "
                        "than Desmin+ cells"
                    ),
                    "unit": None,
                    "confidence": "high",
                },
            }
        ],
    )
    assert len(rows) == 1
    assert rows[0].predicate == "colocalized_with"
    assert rows[0].provisional_experiment_id == "PEX-GP-X-zsgreen"
    assert rows[0].evidence_ids == ["VLM-1"]
    assert rows[0].confidence == "high"
    assert rows[0].review_reasons == []


def test_ambiguous_or_unknown_visual_claim_fails_closed(
    tmp_path, monkeypatch
):
    experiment_root = tmp_path / "experiments"
    paper_root = experiment_root / "GP-X"
    paper_root.mkdir(parents=True)
    inventory = {
        "inventory_version": "provisional-experiments-1.2.0",
        "paper_id": "GP-X",
        "source_packet_checksum": "a" * 64,
        "experiments": [],
        "unassigned_claim_ids": [],
        "validation_notes": [],
    }
    (paper_root / "inventory.json").write_text(
        json.dumps(inventory), encoding="utf-8"
    )
    monkeypatch.setattr(
        "src.extraction.v12_main_route.EXPERIMENT_ROOT",
        experiment_root,
    )
    rows = _visual_candidates(
        "GP-X",
        [
            {
                "evidence_id": "VLM-2",
                "object_id": "FIG-2",
                "claim": {
                    "claim_id": "VCL-2",
                    "subject": "unclear treatment",
                    "predicate": "looked different",
                    "endpoint": None,
                    "value": "uncertain",
                    "unit": None,
                    "confidence": "high",
                },
            }
        ],
    )
    assert rows[0].confidence == "medium"
    assert rows[0].provisional_experiment_id is None
    assert set(rows[0].review_reasons) == {
        "visual_payload_unresolved",
        "visual_predicate_not_safely_mapped",
    }
