import json

import pytest

from src.extraction.g1_review_app import apply_decision, evidence_sentence, load_records, save_records, structured_value_rows


def test_decision_and_reason_round_trip(tmp_path):
    path = tmp_path / "review.jsonl"
    records = [{"review_id": "G1-0001", "human_decision": "pending"}]
    apply_decision(records, review_id="G1-0001", decision="incorrect", reason="Payload is not an LNP component.", reviewer="tester")
    save_records(records, path)
    saved = load_records(path)
    assert saved[0]["human_decision"] == "incorrect"
    assert saved[0]["reviewer_reason"] == "Payload is not an LNP component."
    assert saved[0]["reviewer"] == "tester"
    assert saved[0]["reviewed_at"]


@pytest.mark.parametrize("reason", ["", "   "])
def test_reason_is_required(reason):
    with pytest.raises(ValueError, match="reason"):
        apply_decision([{"review_id": "G1-0001"}], review_id="G1-0001", decision="correct", reason=reason, reviewer="tester")


def test_structured_value_rows_only_show_reported_source_values():
    rows = structured_value_rows(
        {
            "lnp_experiment_id": "E1",
            "payload_type_reported": {"value": "mRNA", "status": "reported", "evidence_quote": "mRNA", "confidence": "high", "missing_reason": None},
            "dose_value_reported": {"value": None, "status": "missing", "evidence_quote": None, "confidence": "low", "missing_reason": "Not stated"},
        }
    )
    assert rows == [
        {"Field": "lnp_experiment_id", "Extracted value": "E1", "Evidence": "Record/link identifier"},
        {"Field": "payload_type_reported", "Extracted value": "mRNA", "Evidence": "mRNA"},
    ]


def test_short_evidence_is_expanded_to_complete_sentence():
    abstract = "First sentence. Intravenous delivery transfected hepatocytes in mice. Final sentence."
    assert evidence_sentence("transfected hepatocytes", abstract) == "Intravenous delivery transfected hepatocytes in mice."
