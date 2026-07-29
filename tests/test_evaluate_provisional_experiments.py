from src.extraction.evaluate_provisional_experiments import match_score
from src.extraction.v12_structure_contracts import ProvisionalExperimentV12


def provisional(payload: str, context: str):
    return ProvisionalExperimentV12(
        provisional_experiment_id=f"PEX-{payload}-{context}",
        label=f"{payload} / {context}",
        anchors=[
            {
                "anchor_type": "payload",
                "value": payload,
                "evidence_ids": ["E1"],
            },
            {
                "anchor_type": "model",
                "value": context,
                "evidence_ids": ["E1"],
            },
        ],
        boundary_status="inferred",
        boundary_reason="test",
        confidence="medium",
    )


def test_gold_reporter_matches_reporter_inventory_not_editing():
    gold = {
        "payload_type": "mRNA",
        "payload_name": "eGFP mRNA",
        "reporter": "eGFP",
        "in_vitro_in_vivo": "in_vivo",
        "cell_type": "lsec",
        "delivery_recipient_cell": "lsec",
        "therapeutic_target_cell": "",
        "cell_source": "mouse liver",
        "assay": "GFP_LYVE1_immunostaining",
    }
    reporter_score, _ = match_score(gold, provisional("egfp_gfp", "in_vivo"))
    editing_score, _ = match_score(gold, provisional("cas9_sgrna", "in_vivo"))
    assert reporter_score >= 8
    assert editing_score < 8


def test_same_payload_context_distinguishes_in_vitro_from_in_vivo():
    gold = {
        "payload_type": "mRNA",
        "payload_name": "FAPCAR mRNA",
        "reporter": "FAPCAR",
        "in_vitro_in_vivo": "in_vitro",
        "cell_type": "hsc",
        "delivery_recipient_cell": "CD163_positive_macrophage",
        "therapeutic_target_cell": "FAP_positive_activated_HSC",
        "cell_source": "BMDM and JS-1",
        "assay": "flow_cytometry_phagocytosis_cytotoxicity",
    }
    correct, _ = match_score(gold, provisional("fapcar", "in_vitro"))
    wrong_context, _ = match_score(gold, provisional("fapcar", "in_vivo"))
    assert correct >= 8
    assert wrong_context < 8
