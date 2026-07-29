import json
from pathlib import Path

from src.extraction.deterministic_coverage_v12 import (
    assess_candidate_eligibility,
    associate_output_experiments,
    evaluate_structural_coverage,
)
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12


def candidate(**changes):
    values = {
        "candidate_id": "AOC-1",
        "paper_id": "GP-X",
        "claim_ids": ["ACL-1"],
        "provisional_experiment_id": "PEX-EGFP",
        "subject_text": "F4/80-positive Kupffer cells",
        "predicate": "expressed",
        "object_text": "eGFP",
        "endpoint_text": "eGFP expression",
        "qualitative_result": "few",
        "numeric_value": None,
        "value_text": None,
        "unit": None,
        "polarity": "positive",
        "evidence_ids": ["E-KUPFFER"],
        "source_ids": ["S1"],
        "route_hint": "text",
        "confidence": "high",
        "review_reasons": [],
        "structural_signature": "kupffer-expression",
    }
    values.update(changes)
    return AtomicOutcomeCandidateV12(**values)


def provisional(identifier="PEX-EGFP", payload="egfp_gfp", model="in_vivo"):
    return {
        "provisional_experiment_id": identifier,
        "anchors": [
            {
                "anchor_type": "payload",
                "value": payload,
                "evidence_ids": ["E-ANCHOR"],
            },
            {
                "anchor_type": "model",
                "value": model,
                "evidence_ids": ["E-ANCHOR"],
            },
        ],
    }


def reported(value, *evidence_ids):
    return {
        "value": value,
        "status": "reported" if value is not None else "missing",
        "evidence_ids": list(evidence_ids) if value is not None else [],
        "missing_reason": None if value is not None else "Not reported.",
    }


def experiment(identifier="EXP1", payload="eGFP mRNA"):
    return {
        "experiment_id": identifier,
        "formulation_id": "F1",
        "payload_type": reported("mRNA", "E-ANCHOR"),
        "payload_name": reported(payload, "E-ANCHOR"),
        "encoded_product": reported("eGFP", "E-ANCHOR"),
        "molecular_target": reported(None),
        "delivery_recipient_cell": reported("Kupffer cells", "E-KUPFFER"),
        "therapeutic_target_cell": reported(None),
        "tissue_or_organ": reported("liver", "E-ANCHOR"),
        "species": reported("mouse", "E-ANCHOR"),
        "disease_model": reported(None),
        "experimental_context": reported("in_vivo", "E-ANCHOR"),
        "dose": reported(None),
        "dose_unit": reported(None),
        "route": reported("intravenous", "E-ANCHOR"),
        "timepoint": reported(5, "E-ANCHOR"),
        "timepoint_unit": reported("hours", "E-ANCHOR"),
    }


def outcome(
    *,
    identifier="OUT1",
    experiment_id="EXP1",
    endpoint="eGFP expression in F4/80-positive Kupffer cells",
    qualitative="Few F4/80-positive Kupffer cells expressed eGFP.",
    value=None,
    unit=None,
    evidence_id="E-KUPFFER",
):
    return {
        "outcome_id": identifier,
        "experiment_id": experiment_id,
        "assay": reported("immunostaining", evidence_id),
        "endpoint": reported(endpoint, evidence_id),
        "comparator": reported(None),
        "outcome_value": reported(value, evidence_id),
        "outcome_unit": reported(unit, evidence_id),
        "qualitative_outcome": reported(qualitative, evidence_id),
    }


def evaluate(candidates, *, experiments=None, outcomes=None, provisionals=None):
    return evaluate_structural_coverage(
        candidates=candidates,
        provisional_experiments=provisionals or [provisional()],
        result={
            "experiments": experiments or [experiment()],
            "outcomes": outcomes or [outcome()],
        },
    )


def test_speculative_candidate_is_not_eligible_for_paid_repair():
    row = candidate(
        object_text=(
            "mRNA-LNP encoded mitogens would also be beneficial in adjacent "
            "hepatocytes"
        )
    )
    eligibility = assess_candidate_eligibility(row)
    assert not eligibility["eligible"]
    assert "speculative_or_interpretive_language" in eligibility["reasons"]


def test_method_sentence_without_result_is_not_eligible():
    row = candidate(
        predicate="increased",
        subject_text="Sections were analyzed",
        object_text=(
            "to identify enhanced green fluorescent protein-positive cells"
        ),
        endpoint_text=None,
        qualitative_result=None,
    )
    eligibility = assess_candidate_eligibility(row)
    assert not eligibility["eligible"]
    assert "method_without_direct_result" in eligibility["reasons"]


def test_independent_experiment_association_requires_unique_payload_match():
    associations = associate_output_experiments(
        [provisional(), provisional("PEX-SECOND")],
        [experiment()],
    )
    assert associations["EXP1"]["status"] == "ambiguous"
    assert associations["EXP1"]["provisional_experiment_id"] is None


def test_exact_atomic_facts_confirm_without_repair():
    report = evaluate([candidate()])
    row = report["candidates"][0]
    assert row["verdict"] == "confirmed"
    assert row["route"] == "none"
    assert not report["integration_blocked"]


def test_gp004_broad_hepatocyte_record_does_not_cover_kupffer_candidate():
    broad = outcome(
        endpoint="eGFP expression in liver cell types",
        qualitative=(
            "Parenchymal hepatocytes were the main population, with some "
            "endothelial and hematopoietic populations also indicated."
        ),
    )
    broad_experiment = experiment()
    broad_experiment["delivery_recipient_cell"] = reported(
        "parenchymal hepatocytes", "E-KUPFFER"
    )
    report = evaluate(
        [candidate()],
        experiments=[broad_experiment],
        outcomes=[broad],
    )
    row = report["candidates"][0]
    assert row["verdict"] == "unconfirmed"
    assert row["route"] == "bounded_repair_task"
    assert report["integration_blocked"]


def test_opposite_polarity_blocks_integration_instead_of_adding_record():
    negative = candidate(polarity="negative", qualitative_result="no obvious")
    positive_output = outcome(
        qualitative="High F4/80-positive Kupffer-cell eGFP expression."
    )
    report = evaluate([negative], outcomes=[positive_output])
    row = report["candidates"][0]
    assert row["verdict"] == "contradicted"
    assert row["route"] == "human_review"
    assert report["integration_blocked"]


def test_missing_cell_fails_closed_to_unconfirmed():
    vague = outcome(
        endpoint="eGFP expression",
        qualitative="Reporter expression was observed.",
    )
    vague_experiment = experiment()
    vague_experiment["delivery_recipient_cell"] = reported(None)
    report = evaluate(
        [candidate()],
        experiments=[vague_experiment],
        outcomes=[vague],
    )
    assert report["candidates"][0]["verdict"] == "unconfirmed"


def test_numeric_rounding_can_confirm_coverage_but_not_arbitrary_value():
    numeric = candidate(
        numeric_value=41.5,
        value_text="41.5%",
        unit="percent",
    )
    rounded = evaluate(
        [numeric],
        outcomes=[outcome(value=42, unit="percent")],
    )
    assert rounded["candidates"][0]["verdict"] == "confirmed"

    wrong = evaluate(
        [numeric],
        outcomes=[outcome(value=16.5, unit="percent")],
    )
    assert wrong["candidates"][0]["verdict"] == "contradicted"
    assert wrong["candidates"][0]["route"] == "human_review"


def test_one_broad_output_cannot_confirm_two_atomic_candidates():
    first = candidate(candidate_id="AOC-1", claim_ids=["ACL-1"])
    second = candidate(candidate_id="AOC-2", claim_ids=["ACL-2"])
    report = evaluate([first, second])
    assert report["counts"]["confirmed"] == 0
    assert report["routes"]["bounded_repair_task"] == 2


def test_frozen_gp004_broad_outcome_regression():
    path = (
        Path(__file__).parent
        / "fixtures/v12_structural_coverage/gp004_broad_outcome.json"
    )
    fixture = json.loads(path.read_text(encoding="utf-8"))
    report = evaluate_structural_coverage(
        candidates=[
            AtomicOutcomeCandidateV12.model_validate(fixture["candidate"])
        ],
        provisional_experiments=fixture["provisional_experiments"],
        result=fixture["result"],
    )
    row = report["candidates"][0]
    assert row["verdict"] == fixture["expected"]["verdict"]
    assert row["route"] == fixture["expected"]["route"]
    assert (
        report["integration_blocked"]
        == fixture["expected"]["integration_blocked"]
    )
