import pytest
from pydantic import ValidationError

from src.extraction.compact_contracts import (
    CompactExtractionResponse,
    ReportedField,
)


def reported(value, evidence_id="E1"):
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": [evidence_id],
        "missing_reason": None,
    }


def missing(reason="Not supported by the supplied evidence."):
    return {
        "value": None,
        "status": "missing",
        "evidence_ids": [],
        "missing_reason": reason,
    }


def valid_response():
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": "P1",
        "eligibility": {
            "decision": "eligible",
            "reason_codes": [
                "ORIGINAL_EXPERIMENT",
                "IDENTIFIABLE_LNP",
                "SUPPORTED_PAYLOAD",
                "TARGET_CELL_EVIDENCE",
                "USABLE_FORMULATION_OUTCOME_LINKAGE",
            ],
            "evidence_ids": ["E1"],
            "explanation": "The packet supports an original RNA-LNP experiment.",
        },
        "formulations": [
            {
                "formulation_id": "F1",
                "formulation_name": reported("LNP-1"),
                "composition": reported("lipid A:DSPC:cholesterol:PEG-lipid"),
                "composition_basis": reported("molar ratio"),
                "np_ratio": missing(),
            }
        ],
        "components": [
            {
                "component_id": "C1",
                "formulation_id": "F1",
                "identity": reported("lipid A"),
                "role": reported("ionizable_lipid"),
                "amount": reported(50.0),
                "amount_unit": reported("mol%"),
            }
        ],
        "experiments": [
            {
                "experiment_id": "X1",
                "formulation_id": "F1",
                "payload_type": reported("mRNA"),
                "payload_name": reported("Luc mRNA"),
                "encoded_product": reported("luciferase"),
                "molecular_target": missing(),
                "delivery_recipient_cell": reported("hepatocyte"),
                "therapeutic_target_cell": missing(),
                "tissue_or_organ": reported("liver"),
                "species": reported("mouse"),
                "disease_model": missing(),
                "experimental_context": reported("in_vivo"),
                "dose": reported(1.0),
                "dose_unit": reported("mg/kg"),
                "route": reported("intravenous"),
                "timepoint": reported(24.0),
                "timepoint_unit": reported("hours"),
            }
        ],
        "outcomes": [
            {
                "outcome_id": "O1",
                "experiment_id": "X1",
                "assay": reported("bioluminescence"),
                "endpoint": reported("luciferase expression"),
                "comparator": missing(),
                "outcome_value": missing(),
                "outcome_unit": missing(),
                "qualitative_outcome": reported("liver expression was observed"),
            }
        ],
        "unresolved_items": [],
    }


def test_reported_field_requires_evidence_id():
    with pytest.raises(ValidationError, match="require at least one evidence_id"):
        ReportedField[str](
            value="hepatocyte",
            status="reported",
            evidence_ids=[],
            missing_reason=None,
        )


def test_unsupported_field_must_be_missing():
    field = ReportedField[str](**missing())
    assert field.status == "missing"
    assert field.value is None


def test_response_contains_evidence_ids_but_no_evidence_text():
    response = CompactExtractionResponse.model_validate(valid_response())
    dumped = response.model_dump()
    assert dumped["experiments"][0]["delivery_recipient_cell"]["evidence_ids"] == ["E1"]
    assert "evidence" not in dumped
    assert "evidence_text" not in str(dumped)


def test_response_rejects_evidence_id_not_in_local_packet():
    response = CompactExtractionResponse.model_validate(valid_response())
    with pytest.raises(ValueError, match="unknown evidence IDs"):
        response.validate_evidence_ids({"E2"})


def test_response_accepts_evidence_ids_from_local_packet():
    response = CompactExtractionResponse.model_validate(valid_response())
    response.validate_evidence_ids({"E1"})


def test_ineligible_response_requires_empty_records():
    payload = valid_response()
    payload["eligibility"] = {
        "decision": "ineligible",
        "reason_codes": ["UNSUPPORTED_PAYLOAD"],
        "evidence_ids": ["E1"],
        "explanation": "Only a small-molecule payload was tested.",
    }
    with pytest.raises(ValidationError, match="empty extraction lists"):
        CompactExtractionResponse.model_validate(payload)


def test_ineligible_response_with_empty_records_is_valid():
    payload = valid_response()
    payload["eligibility"] = {
        "decision": "ineligible",
        "reason_codes": ["NOT_ORIGINAL_RESEARCH"],
        "evidence_ids": ["E1"],
        "explanation": "The publication is a review.",
    }
    for key in ("formulations", "components", "experiments", "outcomes"):
        payload[key] = []
    response = CompactExtractionResponse.model_validate(payload)
    assert response.eligibility.decision == "ineligible"


def test_ineligible_can_record_passed_and_failed_criteria():
    payload = valid_response()
    payload["eligibility"] = {
        "decision": "ineligible",
        "reason_codes": [
            "ORIGINAL_EXPERIMENT",
            "IDENTIFIABLE_LNP",
            "UNSUPPORTED_PAYLOAD",
        ],
        "evidence_ids": ["E1"],
        "explanation": "The original LNP experiment used an unsupported payload.",
    }
    for key in ("formulations", "components", "experiments", "outcomes"):
        payload[key] = []
    response = CompactExtractionResponse.model_validate(payload)
    assert response.eligibility.decision == "ineligible"


def test_eligible_can_also_record_non_excluding_incompleteness():
    payload = valid_response()
    payload["eligibility"]["reason_codes"].append("FORMULATION_INCOMPLETE")
    response = CompactExtractionResponse.model_validate(payload)
    assert response.eligibility.decision == "eligible"


def test_eligibility_evidence_id_must_exist_in_packet():
    response = CompactExtractionResponse.model_validate(valid_response())
    with pytest.raises(ValueError, match="EligibilityRecord"):
        response.validate_evidence_ids({"E2"})


def test_payload_is_not_a_formulation_component_role():
    payload = valid_response()
    payload["components"][0]["role"] = reported("payload")
    with pytest.raises(ValidationError):
        CompactExtractionResponse.model_validate(payload)


def test_cross_record_links_must_resolve():
    payload = valid_response()
    payload["outcomes"][0]["experiment_id"] = "UNKNOWN"
    with pytest.raises(ValidationError, match="unknown experiment_id"):
        CompactExtractionResponse.model_validate(payload)
