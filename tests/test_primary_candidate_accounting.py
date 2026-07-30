import copy

import src.extraction.primary_candidate_accounting as accounting
from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.primary_candidate_accounting import (
    DISPOSITIONS,
    REASON_CODES,
    build_candidate_accounting_schema,
    parse_accounting_response,
)


def _candidate(candidate_id: str, evidence_id: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "evidence_ids": [evidence_id],
        "route_hint": "text",
        "source_ids": ["SRC-1"],
        "review_reasons": [],
    }


def _reported(value, evidence_id="E-1"):
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": [evidence_id],
        "missing_reason": None,
    }


def _eligible_response() -> dict:
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": "NP-TEST",
        "eligibility": {
            "decision": "eligible",
            "reason_codes": [
                "ORIGINAL_EXPERIMENT",
                "IDENTIFIABLE_LNP",
                "SUPPORTED_PAYLOAD",
                "TARGET_CELL_EVIDENCE",
                "USABLE_FORMULATION_OUTCOME_LINKAGE",
            ],
            "evidence_ids": ["E-1"],
            "explanation": "A directly supported eligible test extraction.",
        },
        "formulations": [
            {
                "formulation_id": "F-1",
                "formulation_name": _reported("Test LNP"),
                "composition": _reported("lipids"),
                "composition_basis": _reported("reported composition"),
                "np_ratio": _reported(6.0),
            }
        ],
        "components": [],
        "experiments": [
            {
                "experiment_id": "EXP-1",
                "formulation_id": "F-1",
                "payload_type": _reported("mRNA"),
                "payload_name": _reported("test mRNA"),
                "encoded_product": _reported("test protein"),
                "molecular_target": _reported("target"),
                "delivery_recipient_cell": _reported("hepatocytes"),
                "therapeutic_target_cell": _reported("hepatocytes"),
                "tissue_or_organ": _reported("liver"),
                "species": _reported("mouse"),
                "disease_model": _reported("test model"),
                "experimental_context": _reported("in_vivo"),
                "dose": _reported(1.0),
                "dose_unit": _reported("mg/kg"),
                "route": _reported("intravenous"),
                "timepoint": _reported(24.0),
                "timepoint_unit": _reported("hours"),
            }
        ],
        "outcomes": [
            {
                "outcome_id": "OUT-1",
                "experiment_id": "EXP-1",
                "assay": _reported("assay"),
                "endpoint": _reported("endpoint"),
                "comparator": _reported("control"),
                "outcome_value": _reported(1.0),
                "outcome_unit": _reported("units"),
                "qualitative_outcome": _reported("reported response"),
            }
        ],
        "unresolved_items": [],
    }


def _unresolved_response() -> dict:
    return {
        "contract_version": "compact-1.1.0",
        "paper_id": "NP-TEST",
        "eligibility": {
            "decision": "uncertain",
            "reason_codes": ["FULL_TEXT_REQUIRED"],
            "evidence_ids": [],
            "explanation": "The test candidates require an explicit disposition.",
        },
        "formulations": [],
        "components": [],
        "experiments": [],
        "outcomes": [],
        "unresolved_items": [],
    }


def _entry(disposition, reason_code, *, evidence_id="E-1", outcome_ids=None):
    return {
        "disposition": disposition,
        "linked_outcome_ids": outcome_ids or [],
        "evidence_ids": [evidence_id],
        "reason_code": reason_code,
    }


def _trial_response(body, entries):
    return {
        **body,
        "accounting_contract_version": "compact-accounting-trial-1.0.0",
        "candidate_accounting": entries,
    }


def test_dynamic_schema_requires_each_sent_candidate_and_preserves_compact_contract():
    schema = build_candidate_accounting_schema(
        CompactExtractionResponse.model_json_schema(),
        [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")],
    )

    assert set(CompactExtractionResponse.model_json_schema()["required"]) <= set(
        schema["required"]
    )
    assert {"accounting_contract_version", "candidate_accounting"} <= set(
        schema["required"]
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["contract_version"] == {
        "const": "compact-1.1.0",
        "title": "Contract Version",
        "type": "string",
    }

    accounting = schema["properties"]["candidate_accounting"]
    assert accounting["required"] == ["AOC-one", "AOC-two"]
    assert set(accounting["properties"]) == {"AOC-one", "AOC-two"}
    assert accounting["additionalProperties"] is False


def test_dynamic_schema_forbids_unknown_entry_fields_and_uses_closed_accounting_enums():
    schema = build_candidate_accounting_schema(
        CompactExtractionResponse.model_json_schema(),
        [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")],
    )

    entry = schema["$defs"]["CandidateAccountingEntry"]
    assert entry["additionalProperties"] is False
    assert entry["required"] == [
        "disposition",
        "linked_outcome_ids",
        "evidence_ids",
        "reason_code",
    ]
    assert entry["properties"]["disposition"]["enum"] == list(DISPOSITIONS)
    assert entry["properties"]["reason_code"]["enum"] == list(REASON_CODES)


def test_validator_reports_missing_extra_and_substituted_candidate_keys():
    candidates = [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")]
    response = _trial_response(
        _unresolved_response(),
        {
            "AOC-one": _entry(
                "insufficient_evidence", "evidence_does_not_support_outcome"
            ),
            "AOC-other": _entry(
                "insufficient_evidence",
                "evidence_does_not_support_outcome",
                evidence_id="E-2",
            ),
        },
    )

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert report["candidates_sent"] == 2
    assert report["candidates_accounted_for"] == 1
    assert report["accounting_completeness"] == 0.5
    assert {error["code"] for error in report["errors"]} == {
        "missing_candidate_keys",
        "unknown_candidate_keys",
    }


def test_validator_rejects_duplicate_or_nonexistent_returned_outcome_ids(monkeypatch):
    candidates = [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")]
    response = _eligible_response()
    response["outcomes"].append(copy.deepcopy(response["outcomes"][0]))
    response = _trial_response(
        response,
        {
            "AOC-one": _entry(
                "extracted", "directly_reported", outcome_ids=["OUT-1"]
            ),
            "AOC-two": _entry(
                "extracted",
                "directly_reported",
                evidence_id="E-2",
                outcome_ids=["OUT-missing"],
            ),
        },
    )
    monkeypatch.setattr(accounting, "candidate_outcome_matches", lambda *_: True)

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert {error["code"] for error in report["errors"]} == {
        "duplicate_returned_outcome_ids",
        "unknown_linked_outcome_id",
    }


def test_validator_rejects_accounting_evidence_outside_candidate_and_request_envelope():
    candidates = [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")]
    response = _trial_response(
        _unresolved_response(),
        {
            "AOC-one": _entry(
                "insufficient_evidence",
                "evidence_does_not_support_outcome",
                evidence_id="E-2",
            ),
            "AOC-two": _entry(
                "insufficient_evidence",
                "evidence_does_not_support_outcome",
                evidence_id="E-outside",
            ),
        },
    )

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert {error["code"] for error in report["errors"]} == {
        "evidence_outside_candidate_allowance",
        "evidence_outside_request_envelope",
    }


def test_validator_counts_only_an_extracted_candidate_with_a_structural_match(monkeypatch):
    candidates = [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")]
    response = _trial_response(
        _eligible_response(),
        {
            "AOC-one": _entry(
                "extracted", "directly_reported", outcome_ids=["OUT-1"]
            ),
            "AOC-two": _entry(
                "insufficient_evidence",
                "evidence_does_not_support_outcome",
                evidence_id="E-2",
            ),
        },
    )
    monkeypatch.setattr(accounting, "candidate_outcome_matches", lambda *_: True)

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert report["valid_extracted"] == 1
    assert report["structurally_confirmed_candidates"] == 1
    assert report["structurally_confirmed_candidate_ids"] == ["AOC-one"]
    assert report["rejected_links"] == []


def test_validator_rejects_an_incompatible_extracted_link(monkeypatch):
    candidates = [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")]
    response = _trial_response(
        _eligible_response(),
        {
            "AOC-one": _entry(
                "extracted", "directly_reported", outcome_ids=["OUT-1"]
            ),
            "AOC-two": _entry(
                "insufficient_evidence",
                "evidence_does_not_support_outcome",
                evidence_id="E-2",
            ),
        },
    )
    monkeypatch.setattr(accounting, "candidate_outcome_matches", lambda *_: False)

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert report["valid_extracted"] == 0
    assert report["structurally_confirmed_candidates"] == 0
    assert report["rejected_links"] == [
        {
            "candidate_id": "AOC-one",
            "outcome_id": "OUT-1",
            "reason": "structural_match_failed",
        }
    ]


def test_validator_requires_a_shared_structurally_valid_link_for_duplicates(monkeypatch):
    candidates = [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")]
    response = _trial_response(
        _eligible_response(),
        {
            "AOC-one": _entry(
                "extracted", "directly_reported", outcome_ids=["OUT-1"]
            ),
            "AOC-two": _entry(
                "duplicate",
                "same_fact_as_linked_outcome",
                evidence_id="E-2",
                outcome_ids=["OUT-1"],
            ),
        },
    )
    monkeypatch.setattr(accounting, "candidate_outcome_matches", lambda *_: True)

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert report["valid_extracted"] == 1
    assert report["valid_duplicates"] == 1
    assert report["structurally_confirmed_candidates"] == 2

    unshared = copy.deepcopy(response)
    unshared["candidate_accounting"]["AOC-one"] = _entry(
        "insufficient_evidence", "evidence_does_not_support_outcome"
    )
    _, report = parse_accounting_response(unshared, candidates, {"E-1", "E-2"})
    assert report["valid_duplicates"] == 0
    assert {error["code"] for error in report["errors"]} == {
        "duplicate_link_not_shared"
    }


def test_validator_requires_visual_provenance_for_requires_visual():
    candidates = [
        {**_candidate("AOC-one", "E-1"), "route_hint": "vision"},
        _candidate("AOC-two", "E-2"),
    ]
    response = _trial_response(
        _unresolved_response(),
        {
            "AOC-one": _entry(
                "requires_visual",
                "visual_value_not_available_as_text",
            ),
            "AOC-two": _entry(
                "requires_visual",
                "visual_value_not_available_as_text",
                evidence_id="E-2",
            ),
        },
    )

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert report["unresolved_disposition_counts"]["requires_visual"] == 2
    assert {error["code"] for error in report["errors"]} == {
        "requires_visual_without_visual_provenance"
    }


def test_validator_requires_existing_diagnostics_for_context_or_malformed_not_outcome():
    candidates = [
        {**_candidate("AOC-one", "E-1"), "review_reasons": ["malformed_candidate"]},
        _candidate("AOC-two", "E-2"),
    ]
    response = _trial_response(
        _unresolved_response(),
        {
            "AOC-one": _entry("not_outcome", "malformed_candidate"),
            "AOC-two": _entry(
                "not_outcome", "context_or_method_only", evidence_id="E-2"
            ),
        },
    )

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert report["unresolved_disposition_counts"]["not_outcome"] == 2
    assert {error["code"] for error in report["errors"]} == {
        "not_outcome_diagnostic_mismatch"
    }


def test_all_unresolved_candidates_are_complete_but_scientifically_unconfirmed():
    candidates = [_candidate("AOC-one", "E-1"), _candidate("AOC-two", "E-2")]
    response = _trial_response(
        _unresolved_response(),
        {
            "AOC-one": _entry(
                "insufficient_evidence", "evidence_does_not_support_outcome"
            ),
            "AOC-two": _entry(
                "ambiguous",
                "experiment_assignment_uncertain",
                evidence_id="E-2",
            ),
        },
    )

    _, report = parse_accounting_response(response, candidates, {"E-1", "E-2"})

    assert report["candidates_sent"] == 2
    assert report["candidates_accounted_for"] == 2
    assert report["accounting_completeness"] == 1.0
    assert report["valid_extracted"] == 0
    assert report["valid_duplicates"] == 0
    assert report["unique_returned_outcomes"] == 0
    assert report["structurally_confirmed_candidates"] == 0
    assert report["unresolved_disposition_counts"] == {
        "not_outcome": 0,
        "insufficient_evidence": 1,
        "requires_visual": 0,
        "ambiguous": 1,
    }
    assert report["errors"] == []
