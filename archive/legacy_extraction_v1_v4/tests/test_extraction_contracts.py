import pytest
from pydantic import ValidationError

from src.extraction.contracts import EvidenceBoundValue, EvidenceExtraction


def test_reported_value_requires_evidence():
    with pytest.raises(ValidationError, match="require at least one evidence_id"):
        EvidenceBoundValue[str](
            value="reported text",
            value_status="reported",
            evidence_ids=[],
            missing_reason=None,
        )


def test_missing_value_is_explicit_and_explained():
    field = EvidenceBoundValue[str](
        value=None,
        value_status="missing",
        evidence_ids=[],
        missing_reason="Not stated in the abstract.",
    )
    assert field.value is None


@pytest.mark.parametrize("forbidden_status", ["inferred", "derived", "normalized"])
def test_inferred_or_transformed_statuses_are_prohibited(forbidden_status):
    with pytest.raises(ValidationError):
        EvidenceBoundValue[str](
            value="guessed",
            value_status=forbidden_status,
            evidence_ids=["E1"],
            missing_reason=None,
        )


def test_evidence_coordinates_are_required_even_when_null():
    payload = {
        "evidence_id": "E1",
        "paper_id": "P1",
        "evidence_text": "A directly reported statement.",
        "evidence_location_type": "abstract",
        "section_name": None,
        "page_number": None,
        "table_number": None,
        "figure_number": None,
        "supplement_identifier": None,
        "extraction_method": "text_extraction",
        "extraction_confidence": "high",
    }
    EvidenceExtraction.model_validate(payload)
    del payload["page_number"]
    with pytest.raises(ValidationError, match="page_number"):
        EvidenceExtraction.model_validate(payload)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EvidenceBoundValue[str](
            value=None,
            value_status="missing",
            evidence_ids=[],
            missing_reason="Not reported.",
            inferred_ratio=50,
        )
