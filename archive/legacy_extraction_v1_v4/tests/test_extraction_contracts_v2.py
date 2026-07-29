import pytest
from pydantic import ValidationError

from src.extraction.contracts_v2 import AbstractExtractionV2


def missing(reason="Not stated in abstract"):
    return {"value": None, "status": "missing", "evidence_quote": None, "confidence": "high", "missing_reason": reason}


def reported(value, quote="The abstract explicitly reports this value."):
    return {"value": value, "status": "reported", "evidence_quote": quote, "confidence": "high", "missing_reason": None}


def base_payload():
    return {
        "contract_version": "2.0.0",
        "paper_id": "GP-X",
        "lnp_formulations": [{
            "lnp_formulation_id": "F1",
            "lnp_formulation_name_reported": reported("LNP-X"),
            "lnp_composition_raw_reported": missing(),
            "lnp_composition_basis_reported": missing(),
            "lnp_np_ratio_reported": missing(),
            "lnp_formulation_description_reported": reported("mRNA-LNP"),
        }],
        "lnp_components": [],
        "lnp_experiments": [],
        "lnp_outcomes": [],
    }


def test_v2_uses_specific_lnp_field_names():
    model = AbstractExtractionV2.model_validate(base_payload())
    assert model.lnp_formulations[0].lnp_composition_raw_reported.status == "missing"


def test_v2_rejects_payload_as_lnp_component():
    payload = base_payload()
    payload["lnp_components"].append({
        "lnp_component_id": "C1",
        "lnp_formulation_id": "F1",
        "lnp_component_name_reported": reported("HGF mRNA"),
        "lnp_component_role": reported("other_lnp_material"),
        "lnp_component_amount_reported": missing(),
        "lnp_component_amount_unit_reported": missing(),
        "lnp_component_identity_reported": missing(),
    })
    with pytest.raises(ValidationError, match="RNA payload cannot be stored"):
        AbstractExtractionV2.model_validate(payload)
