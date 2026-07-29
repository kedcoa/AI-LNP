from src.extraction.contracts_v2 import AbstractExtractionV2
from src.extraction.run_g1_v2 import deterministic_audit
from tests.test_extraction_contracts_v2 import base_payload


def test_deterministic_audit_accepts_verbatim_quote():
    payload = base_payload()
    payload["lnp_formulations"][0]["lnp_formulation_name_reported"]["evidence_quote"] = "An LNP-X was tested."
    payload["lnp_formulations"][0]["lnp_formulation_description_reported"]["evidence_quote"] = "An LNP-X was tested."
    model = AbstractExtractionV2.model_validate(payload)
    assert deterministic_audit(model, "An LNP-X was tested.") == []


def test_deterministic_audit_rejects_paraphrased_quote():
    model = AbstractExtractionV2.model_validate(base_payload())
    issues = deterministic_audit(model, "Different source text.")
    assert {issue["issue_type"] for issue in issues} == {"evidence_quote_not_in_abstract"}
