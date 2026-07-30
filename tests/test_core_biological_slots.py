from copy import deepcopy

import pytest
from openai.lib._pydantic import to_strict_json_schema

from src.extraction import core_biological_slots as core_slots
from src.extraction.compact_contracts import CompactExtractionResponse
from src.extraction.core_biological_slots import build_np001_core_slots


SLOT_IDS = [
    "CORE-HEPG2-TRANSFECTION",
    "CORE-DC24-TRANSFECTION",
    "CORE-DC24-IMMUNE",
    "CORE-HPBMC-TRANSFECTION",
    "CORE-HPBMC-IMMUNE",
    "CORE-MOUSE-BIODISTRIBUTION",
]


def evidence(evidence_id, text):
    return {"evidence_id": evidence_id, "text": text}


def qualifying_packet():
    return {
        "paper_id": "NP-001",
        "evidence": [
            evidence(
                "E-FORM",
                "The DX-loaded LNP formulation contained ALC-0315, "
                "DSPC or DOPE, cholesterol/DX, and ALC-0159.",
            ),
            evidence(
                "E-PAYLOAD",
                "The lipid nanoparticles encapsulated EGFP mRNA payload.",
            ),
            evidence(
                "E-HEPG2-TX",
                "HepG2 cells were transfected and showed EGFP expression.",
            ),
            evidence(
                "E-DC24-TX",
                "DC2.4 dendritic cells were transfected and expressed EGFP.",
            ),
            evidence(
                "E-DC24-IMM",
                "DC2.4 dendritic cells released IL-6 cytokine after delivery.",
            ),
            evidence(
                "E-HPBMC-TX",
                "hPBMCs were transfected and showed reporter expression.",
            ),
            evidence(
                "E-HPBMC-IMM",
                "Human PBMCs mounted a TNF-alpha immune cytokine response.",
            ),
            evidence(
                "E-MOUSE-BIO",
                "In vivo mouse biodistribution showed liver accumulation.",
            ),
        ],
    }


def test_builder_qualifies_all_six_closed_np001_slots_in_order():
    report = build_np001_core_slots(qualifying_packet())

    assert report["paper_id"] == "NP-001"
    assert [
        row["slot_id"] for row in report["evaluated_slots"]
    ] == SLOT_IDS
    assert [
        row["slot_id"] for row in report["qualified_slots"]
    ] == SLOT_IDS
    for row in report["evaluated_slots"]:
        assert row["qualified"] is True
        assert row["evidence_ids"]
        assert row["model_family"]
        assert row["outcome_family"]
        assert row["exclusion_reason"] is None
        assert row["formulation_evidence_ids"]
        assert row["payload_evidence_ids"]
        assert row["model_evidence_ids"]
        assert row["outcome_evidence_ids"]


def test_builder_reports_the_missing_required_category_explicitly():
    packet = qualifying_packet()
    packet["evidence"] = [
        row
        for row in packet["evidence"]
        if row["evidence_id"] != "E-DC24-IMM"
    ]

    report = build_np001_core_slots(packet)
    immune = next(
        row
        for row in report["evaluated_slots"]
        if row["slot_id"] == "CORE-DC24-IMMUNE"
    )

    assert immune["qualified"] is False
    assert immune["model_evidence_ids"] == ["E-DC24-TX"]
    assert immune["outcome_evidence_ids"] == []
    assert immune["exclusion_reason"] == (
        "missing_required_evidence:outcome"
    )
    assert immune not in report["qualified_slots"]


@pytest.mark.parametrize(
    ("slot_id", "evidence_id", "text"),
    [
        (
            "CORE-HEPG2-TRANSFECTION",
            "E-HEPG2-TX",
            "HepG2 gene expression increased after delivery.",
        ),
        (
            "CORE-MOUSE-BIODISTRIBUTION",
            "E-MOUSE-BIO",
            "Mouse hepatic expression increased in vivo.",
        ),
    ],
)
def test_expression_aliases_qualify_their_declared_outcome_families(
    slot_id,
    evidence_id,
    text,
):
    packet = qualifying_packet()
    next(
        row for row in packet["evidence"]
        if row["evidence_id"] == evidence_id
    )["text"] = text

    report = build_np001_core_slots(packet)

    slot = next(
        row
        for row in report["evaluated_slots"]
        if row["slot_id"] == slot_id
    )
    assert slot["qualified"] is True


@pytest.mark.parametrize(
    "physical_term",
    [
        "SAXS structure",
        "morphology",
        "particle size",
        "PDI",
        "zeta potential",
        "storage stability",
        "release kinetics",
    ],
)
def test_physical_characterization_only_never_qualifies_a_slot(
    physical_term,
):
    packet = {
        "paper_id": "NP-001",
        "evidence": [
            evidence("E-FORM", "The LNP formulation used four lipids."),
            evidence("E-PAYLOAD", "The LNP encapsulated EGFP mRNA payload."),
            evidence(
                "E-PHYS-HEP",
                f"HepG2 sample {physical_term} was measured.",
            ),
            evidence(
                "E-PHYS-DC",
                f"DC2.4 sample {physical_term} was measured.",
            ),
            evidence(
                "E-PHYS-PBMC",
                f"hPBMC sample {physical_term} was measured.",
            ),
            evidence(
                "E-PHYS-MOUSE",
                f"Mouse sample {physical_term} was measured.",
            ),
        ],
    }

    report = build_np001_core_slots(packet)

    assert report["qualified_slots"] == []
    assert all(
        row["exclusion_reason"]
        == "missing_required_evidence:outcome"
        for row in report["evaluated_slots"]
    )


@pytest.mark.parametrize(
    "false_payload_text",
    [
        "HepG2 internalization and expression increased.",
        "HepG2 DNAse activity and reporter expression increased.",
        "Background discussion: RNA delivery can change expression.",
    ],
)
def test_payload_matching_rejects_substrings_and_background_mentions(
    false_payload_text,
):
    packet = {
        "paper_id": "NP-001",
        "evidence": [
            evidence("E-FORM", "The NP-001 LNP formulation was used."),
            evidence("E-OUTCOME", false_payload_text),
        ],
    }

    report = build_np001_core_slots(packet)
    hep = next(
        row
        for row in report["evaluated_slots"]
        if row["slot_id"] == "CORE-HEPG2-TRANSFECTION"
    )

    assert hep["qualified"] is False
    assert hep["payload_evidence_ids"] == []
    assert "payload" in hep["exclusion_reason"]


def test_builder_refuses_to_infer_slots_for_an_arbitrary_paper():
    packet = deepcopy(qualifying_packet())
    packet["paper_id"] = "GP-008"

    with pytest.raises(ValueError, match="NP-001"):
        build_np001_core_slots(packet)


def test_dynamic_schema_preserves_core_and_requires_exact_qualified_slots():
    compact_schema = to_strict_json_schema(CompactExtractionResponse)
    original = deepcopy(compact_schema)
    qualified = build_np001_core_slots(
        qualifying_packet()
    )["qualified_slots"][:2]

    schema = core_slots.build_core_slot_schema(
        compact_schema,
        qualified,
    )

    assert compact_schema == original
    assert set(original["properties"]) < set(schema["properties"])
    assert {
        key: schema["properties"][key]
        for key in original["properties"]
    } == original["properties"]
    assert schema["properties"]["core_slot_contract_version"] == {
        "type": "string",
        "const": "compact-core-slot-trial-1.0.0",
    }
    assert {
        "core_slot_contract_version",
        "core_slot_accounting",
    } <= set(schema["required"])
    accounting = schema["properties"]["core_slot_accounting"]
    expected_slot_ids = [row["slot_id"] for row in qualified]
    assert accounting["additionalProperties"] is False
    assert list(accounting["properties"]) == expected_slot_ids
    assert accounting["required"] == expected_slot_ids


def test_dynamic_schema_has_one_strict_no_escape_entry_contract():
    compact_schema = to_strict_json_schema(CompactExtractionResponse)
    qualified = build_np001_core_slots(
        qualifying_packet()
    )["qualified_slots"]

    schema = core_slots.build_core_slot_schema(
        compact_schema,
        qualified,
    )

    entry = schema["$defs"]["CoreSlotAccountingEntry"]
    assert entry["type"] == "object"
    assert entry["additionalProperties"] is False
    assert set(entry["properties"]) == {
        "disposition",
        "linked_experiment_id",
        "linked_outcome_ids",
        "evidence_ids",
    }
    assert entry["required"] == [
        "disposition",
        "linked_experiment_id",
        "linked_outcome_ids",
        "evidence_ids",
    ]
    assert entry["properties"]["disposition"]["enum"] == [
        "extracted",
        "duplicate",
    ]
    assert entry["properties"]["linked_experiment_id"]["minLength"] == 1
    assert entry["properties"]["linked_outcome_ids"]["minItems"] == 1
    assert entry["properties"]["evidence_ids"]["minItems"] == 1
    assert all(
        value == {"$ref": "#/$defs/CoreSlotAccountingEntry"}
        for value in schema["properties"]["core_slot_accounting"][
            "properties"
        ].values()
    )


def reported(value, *evidence_ids):
    return {
        "value": value,
        "status": "reported",
        "evidence_ids": list(evidence_ids),
        "missing_reason": None,
    }


def missing(reason="not reported"):
    return {
        "value": None,
        "status": "missing",
        "evidence_ids": [],
        "missing_reason": reason,
    }


def experiment(
    experiment_id,
    *,
    model,
    model_evidence_id,
    context="in_vitro",
    species=None,
    formulation_id="F-1",
    payload_evidence_id="E-PAYLOAD",
):
    return {
        "experiment_id": experiment_id,
        "formulation_id": formulation_id,
        "payload_type": reported("mRNA", payload_evidence_id),
        "payload_name": reported("EGFP mRNA", payload_evidence_id),
        "encoded_product": reported("EGFP", payload_evidence_id),
        "molecular_target": missing(),
        "delivery_recipient_cell": reported(
            model,
            model_evidence_id,
        ),
        "therapeutic_target_cell": missing(),
        "tissue_or_organ": (
            reported("liver", model_evidence_id)
            if context == "in_vivo"
            else missing()
        ),
        "species": (
            reported(species, model_evidence_id)
            if species
            else missing()
        ),
        "disease_model": missing(),
        "experimental_context": reported(
            context,
            model_evidence_id,
        ),
        "dose": missing(),
        "dose_unit": missing(),
        "route": missing(),
        "timepoint": missing(),
        "timepoint_unit": missing(),
    }


def outcome(outcome_id, experiment_id, endpoint, evidence_id):
    return {
        "outcome_id": outcome_id,
        "experiment_id": experiment_id,
        "assay": reported("flow cytometry", evidence_id),
        "endpoint": reported(endpoint, evidence_id),
        "comparator": missing(),
        "outcome_value": missing(),
        "outcome_unit": missing(),
        "qualitative_outcome": reported(endpoint, evidence_id),
    }


def valid_trial_response():
    qualified = build_np001_core_slots(
        qualifying_packet()
    )["qualified_slots"]
    experiment_by_slot = {
        "CORE-HEPG2-TRANSFECTION": "X-HEP",
        "CORE-DC24-TRANSFECTION": "X-DC",
        "CORE-DC24-IMMUNE": "X-DC",
        "CORE-HPBMC-TRANSFECTION": "X-HPBMC",
        "CORE-HPBMC-IMMUNE": "X-HPBMC",
        "CORE-MOUSE-BIODISTRIBUTION": "X-MOUSE",
    }
    outcome_by_slot = {
        "CORE-HEPG2-TRANSFECTION": "O-HEP-TX",
        "CORE-DC24-TRANSFECTION": "O-DC-TX",
        "CORE-DC24-IMMUNE": "O-DC-IMM",
        "CORE-HPBMC-TRANSFECTION": "O-HPBMC-TX",
        "CORE-HPBMC-IMMUNE": "O-HPBMC-IMM",
        "CORE-MOUSE-BIODISTRIBUTION": "O-MOUSE-BIO",
    }
    response = {
        "contract_version": "compact-1.1.0",
        "paper_id": "NP-001",
        "eligibility": {
            "decision": "eligible",
            "reason_codes": [
                "ORIGINAL_EXPERIMENT",
                "IDENTIFIABLE_LNP",
                "SUPPORTED_PAYLOAD",
                "TARGET_CELL_EVIDENCE",
                "USABLE_FORMULATION_OUTCOME_LINKAGE",
            ],
            "evidence_ids": ["E-FORM"],
            "explanation": "The synthetic fixture contains linked evidence.",
        },
        "formulations": [
            {
                "formulation_id": "F-1",
                "formulation_name": reported("DX-loaded LNP", "E-FORM"),
                "composition": reported(
                    "ALC-0315/DSPC/cholesterol/DX/ALC-0159",
                    "E-FORM",
                ),
                "composition_basis": missing(),
                "np_ratio": missing(),
            }
        ],
        "components": [],
        "experiments": [
            experiment(
                "X-HEP",
                model="HepG2",
                model_evidence_id="E-HEPG2-TX",
            ),
            experiment(
                "X-DC",
                model="DC2.4 dendritic cells",
                model_evidence_id="E-DC24-TX",
            ),
            experiment(
                "X-HPBMC",
                model="hPBMCs",
                model_evidence_id="E-HPBMC-TX",
            ),
            experiment(
                "X-MOUSE",
                model="mouse in vivo",
                model_evidence_id="E-MOUSE-BIO",
                context="in_vivo",
                species="mouse",
            ),
        ],
        "outcomes": [
            outcome(
                "O-HEP-TX",
                "X-HEP",
                "EGFP expression after transfection",
                "E-HEPG2-TX",
            ),
            outcome(
                "O-DC-TX",
                "X-DC",
                "EGFP expression after transfection",
                "E-DC24-TX",
            ),
            outcome(
                "O-DC-IMM",
                "X-DC",
                "IL-6 cytokine immune response",
                "E-DC24-IMM",
            ),
            outcome(
                "O-HPBMC-TX",
                "X-HPBMC",
                "Reporter expression after transfection",
                "E-HPBMC-TX",
            ),
            outcome(
                "O-HPBMC-IMM",
                "X-HPBMC",
                "TNF-alpha cytokine immune response",
                "E-HPBMC-IMM",
            ),
            outcome(
                "O-MOUSE-BIO",
                "X-MOUSE",
                "In vivo mouse biodistribution and liver accumulation",
                "E-MOUSE-BIO",
            ),
        ],
        "unresolved_items": [],
        "core_slot_contract_version": (
            "compact-core-slot-trial-1.0.0"
        ),
        "core_slot_accounting": {
            row["slot_id"]: {
                "disposition": "extracted",
                "linked_experiment_id": experiment_by_slot[
                    row["slot_id"]
                ],
                "linked_outcome_ids": [
                    outcome_by_slot[row["slot_id"]]
                ],
                "evidence_ids": list(row["evidence_ids"]),
            }
            for row in qualified
        },
    }
    return qualified, response


def error_codes(report):
    return {row["code"] for row in report["errors"]}


def rejection_reasons(report):
    return {row["reason"] for row in report["rejected_links"]}


def validate(response, qualified=None, envelope=None):
    default_qualified, _default_response = valid_trial_response()
    return core_slots.validate_core_slot_response(
        response,
        qualified if qualified is not None else default_qualified,
        (
            envelope
            if envelope is not None
            else {
                row["evidence_id"]
                for row in qualifying_packet()["evidence"]
            }
        ),
    )


def test_valid_extracted_records_are_scientifically_confirmed():
    qualified, response = valid_trial_response()

    report = validate(response, qualified)

    assert report["slots_sent"] == 6
    assert report["slots_accounted_for"] == 6
    assert report["scientifically_confirmed"] == 6
    assert report["valid_duplicates"] == 0
    assert report["confirmed_slot_ids"] == SLOT_IDS
    assert report["rejected_links"] == []
    assert report["errors"] == []


def test_validator_requires_exact_slot_key_equality():
    qualified, response = valid_trial_response()
    response["core_slot_accounting"].pop(
        "CORE-HEPG2-TRANSFECTION"
    )
    response["core_slot_accounting"]["CORE-UNKNOWN"] = {
        "disposition": "extracted",
        "linked_experiment_id": "X-HEP",
        "linked_outcome_ids": ["O-HEP-TX"],
        "evidence_ids": ["E-HEPG2-TX"],
    }

    report = validate(response, qualified)

    assert "missing_slot_keys" in error_codes(report)
    assert "unknown_slot_keys" in error_codes(report)
    assert report["slots_accounted_for"] == 5
    assert "CORE-HEPG2-TRANSFECTION" not in report[
        "confirmed_slot_ids"
    ]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("linked_experiment_id", "X-NOT-THERE", "unknown_experiment_id"),
        ("linked_outcome_ids", ["O-NOT-THERE"], "unknown_outcome_id"),
    ],
)
def test_nonexistent_record_links_are_rejected(field, value, reason):
    qualified, response = valid_trial_response()
    entry = response["core_slot_accounting"][
        "CORE-HEPG2-TRANSFECTION"
    ]
    entry[field] = value

    report = validate(response, qualified)

    assert reason in rejection_reasons(report)
    assert "CORE-HEPG2-TRANSFECTION" not in report[
        "confirmed_slot_ids"
    ]


def test_duplicate_outcome_ids_in_compact_response_confirm_nothing():
    qualified, response = valid_trial_response()
    response["outcomes"].append(deepcopy(response["outcomes"][0]))

    report = validate(response, qualified)

    assert "duplicate_outcome_ids" in error_codes(report)
    assert report["scientifically_confirmed"] == 0
    assert report["confirmed_slot_ids"] == []


def test_outcome_linked_to_a_different_experiment_is_rejected():
    qualified, response = valid_trial_response()
    response["core_slot_accounting"]["CORE-DC24-TRANSFECTION"][
        "linked_outcome_ids"
    ] = ["O-HEP-TX"]

    report = validate(response, qualified)

    assert "outcome_experiment_mismatch" in rejection_reasons(report)
    assert "CORE-DC24-TRANSFECTION" not in report[
        "confirmed_slot_ids"
    ]


@pytest.mark.parametrize(
    ("slot_id", "experiment_id", "outcome_id"),
    [
        ("CORE-HEPG2-TRANSFECTION", "X-DC", "O-DC-TX"),
        ("CORE-DC24-IMMUNE", "X-HPBMC", "O-HPBMC-IMM"),
        ("CORE-HPBMC-TRANSFECTION", "X-HEP", "O-HEP-TX"),
        ("CORE-MOUSE-BIODISTRIBUTION", "X-HEP", "O-HEP-TX"),
    ],
)
def test_cross_model_links_are_rejected(
    slot_id,
    experiment_id,
    outcome_id,
):
    qualified, response = valid_trial_response()
    entry = response["core_slot_accounting"][slot_id]
    entry["linked_experiment_id"] = experiment_id
    entry["linked_outcome_ids"] = [outcome_id]

    report = validate(response, qualified)

    assert "model_family_mismatch" in rejection_reasons(report)
    assert slot_id not in report["confirmed_slot_ids"]


@pytest.mark.parametrize(
    ("slot_id", "outcome_id"),
    [
        ("CORE-DC24-TRANSFECTION", "O-DC-IMM"),
        ("CORE-DC24-IMMUNE", "O-DC-TX"),
        ("CORE-HPBMC-TRANSFECTION", "O-HPBMC-IMM"),
        ("CORE-HPBMC-IMMUNE", "O-HPBMC-TX"),
    ],
)
def test_cross_outcome_family_links_are_rejected(slot_id, outcome_id):
    qualified, response = valid_trial_response()
    response["core_slot_accounting"][slot_id][
        "linked_outcome_ids"
    ] = [outcome_id]

    report = validate(response, qualified)

    assert "outcome_family_mismatch" in rejection_reasons(report)
    assert slot_id not in report["confirmed_slot_ids"]


def test_biodistribution_cross_family_link_is_rejected():
    qualified, response = valid_trial_response()
    mouse_outcome = next(
        row
        for row in response["outcomes"]
        if row["outcome_id"] == "O-MOUSE-BIO"
    )
    mouse_outcome["endpoint"] = reported(
        "IL-6 cytokine immune response",
        "E-MOUSE-BIO",
    )
    mouse_outcome["qualitative_outcome"] = reported(
        "IL-6 cytokine immune response",
        "E-MOUSE-BIO",
    )

    report = validate(response, qualified)

    assert "outcome_family_mismatch" in rejection_reasons(report)
    assert "CORE-MOUSE-BIODISTRIBUTION" not in report[
        "confirmed_slot_ids"
    ]


def test_mouse_slot_requires_an_explicit_in_vivo_experiment():
    qualified, response = valid_trial_response()
    mouse_experiment = next(
        row
        for row in response["experiments"]
        if row["experiment_id"] == "X-MOUSE"
    )
    mouse_experiment["experimental_context"] = reported(
        "in_vitro",
        "E-MOUSE-BIO",
    )

    report = validate(response, qualified)

    assert "model_family_mismatch" in rejection_reasons(report)
    assert "CORE-MOUSE-BIODISTRIBUTION" not in report[
        "confirmed_slot_ids"
    ]


def test_evidence_outside_slot_or_request_envelope_is_rejected():
    qualified, response = valid_trial_response()
    entry = response["core_slot_accounting"][
        "CORE-HEPG2-TRANSFECTION"
    ]
    entry["evidence_ids"].append("E-OTHER")

    outside_slot = validate(
        response,
        qualified,
        envelope={
            row["evidence_id"]
            for row in qualifying_packet()["evidence"]
        }
        | {"E-OTHER"},
    )
    outside_request = validate(
        response,
        qualified,
        envelope={"E-FORM", "E-PAYLOAD", "E-HEPG2-TX"},
    )

    assert "evidence_outside_slot" in error_codes(outside_slot)
    assert "evidence_outside_request_envelope" in error_codes(
        outside_request
    )
    assert "CORE-HEPG2-TRANSFECTION" not in outside_slot[
        "confirmed_slot_ids"
    ]
    assert outside_request["scientifically_confirmed"] == 0


def test_linked_record_claim_evidence_must_stay_inside_slot_and_request():
    qualified, response = valid_trial_response()
    hep_outcome = next(
        row
        for row in response["outcomes"]
        if row["outcome_id"] == "O-HEP-TX"
    )
    for field in ("assay", "endpoint", "qualitative_outcome"):
        hep_outcome[field]["evidence_ids"].append("E-OTHER")

    report = validate(
        response,
        qualified,
        envelope={
            row["evidence_id"]
            for row in qualifying_packet()["evidence"]
        },
    )

    assert "evidence_outside_slot" in error_codes(report)
    assert "evidence_outside_request_envelope" in error_codes(report)
    assert "CORE-HEPG2-TRANSFECTION" not in report[
        "confirmed_slot_ids"
    ]


@pytest.mark.parametrize(
    ("target", "evidence_id", "reason"),
    [
        ("formulation", "E-HEPG2-TX", "formulation_evidence_mismatch"),
        ("payload", "E-FORM", "payload_evidence_mismatch"),
    ],
)
def test_formulation_or_payload_evidence_incompatibility_is_rejected(
    target,
    evidence_id,
    reason,
):
    qualified, response = valid_trial_response()
    if target == "formulation":
        response["formulations"][0]["formulation_name"] = reported(
            "NP-001",
            evidence_id,
        )
        response["formulations"][0]["composition"] = missing()
    else:
        experiment_row = next(
            row
            for row in response["experiments"]
            if row["experiment_id"] == "X-HEP"
        )
        for field in (
            "payload_type",
            "payload_name",
            "encoded_product",
        ):
            experiment_row[field] = reported("mRNA", evidence_id)

    report = validate(response, qualified)

    assert reason in rejection_reasons(report)
    assert "CORE-HEPG2-TRANSFECTION" not in report[
        "confirmed_slot_ids"
    ]


def test_wrong_scientific_values_cannot_reuse_allowed_category_evidence():
    qualified, response = valid_trial_response()
    response["formulations"][0]["formulation_name"] = reported(
        "Completely different formulation",
        "E-FORM",
    )
    for experiment_row in response["experiments"]:
        experiment_row["payload_type"] = reported(
            "siRNA",
            "E-PAYLOAD",
        )
        experiment_row["payload_name"] = reported(
            "unrelated siRNA",
            "E-PAYLOAD",
        )
        experiment_row["encoded_product"] = reported(
            "unrelated silencing cargo",
            "E-PAYLOAD",
        )

    report = validate(response, qualified)

    assert "formulation_semantic_mismatch" in rejection_reasons(report)
    assert "payload_semantic_mismatch" in rejection_reasons(report)
    assert report["scientifically_confirmed"] == 0


def test_generic_lnp_and_one_common_lipid_do_not_match_np001_formulation():
    qualified, response = valid_trial_response()
    response["formulations"][0]["formulation_name"] = reported(
        "Unrelated LNP",
        "E-FORM",
    )
    response["formulations"][0]["composition"] = reported(
        "cholesterol only",
        "E-FORM",
    )

    report = validate(response, qualified)

    assert "formulation_semantic_mismatch" in rejection_reasons(report)
    assert report["scientifically_confirmed"] == 0


def test_generic_lnp_cannot_match_real_dx_lnp_evidence_without_paper_id():
    packet = qualifying_packet()
    next(
        row
        for row in packet["evidence"]
        if row["evidence_id"] == "E-FORM"
    )["text"] = (
        "The DX-loaded LNP formulation used ionizable lipid, "
        "ALC-0315, DSPC or DOPE, cholesterol/DX, and ALC-0159."
    )
    qualified = build_np001_core_slots(packet)["qualified_slots"]
    _default_qualified, response = valid_trial_response()
    response["formulations"][0]["formulation_name"] = reported(
        "Unrelated LNP",
        "E-FORM",
    )
    response["formulations"][0]["composition"] = reported(
        "ionizable lipid and cholesterol",
        "E-FORM",
    )

    report = validate(response, qualified)

    assert "formulation_semantic_mismatch" in rejection_reasons(report)
    assert report["scientifically_confirmed"] == 0


@pytest.mark.parametrize(
    ("slot_id", "outcome_id", "immune_expression"),
    [
        ("CORE-DC24-TRANSFECTION", "O-DC-TX", "IL-6 expression increased"),
        ("CORE-DC24-TRANSFECTION", "O-DC-TX", "TNF expression increased"),
        (
            "CORE-DC24-TRANSFECTION",
            "O-DC-TX",
            "interferon expression increased",
        ),
        (
            "CORE-HPBMC-TRANSFECTION",
            "O-HPBMC-TX",
            "IL-6 expression increased",
        ),
        (
            "CORE-HPBMC-TRANSFECTION",
            "O-HPBMC-TX",
            "TNF expression increased",
        ),
        (
            "CORE-HPBMC-TRANSFECTION",
            "O-HPBMC-TX",
            "interferon expression increased",
        ),
        (
            "CORE-MOUSE-BIODISTRIBUTION",
            "O-MOUSE-BIO",
            "IL-6 immune expression increased",
        ),
        (
            "CORE-DC24-TRANSFECTION",
            "O-DC-TX",
            "IL-6 expression increased after transfection",
        ),
        (
            "CORE-HPBMC-TRANSFECTION",
            "O-HPBMC-TX",
            "TNF expression increased after transfection",
        ),
    ],
)
def test_immune_marker_expression_cannot_satisfy_other_families(
    slot_id,
    outcome_id,
    immune_expression,
):
    qualified, response = valid_trial_response()
    outcome_row = next(
        row
        for row in response["outcomes"]
        if row["outcome_id"] == outcome_id
    )
    outcome_row["endpoint"] = reported(
        immune_expression,
        outcome_row["endpoint"]["evidence_ids"][0],
    )
    outcome_row["qualitative_outcome"] = reported(
        immune_expression,
        outcome_row["qualitative_outcome"]["evidence_ids"][0],
    )

    report = validate(response, qualified)

    assert "outcome_family_mismatch" in rejection_reasons(report)
    assert slot_id not in report["confirmed_slot_ids"]


@pytest.mark.parametrize(
    ("model_text", "transfection_slot", "immune_slot"),
    [
        (
            "DC2.4 IL-6 expression increased after transfection.",
            "CORE-DC24-TRANSFECTION",
            "CORE-DC24-IMMUNE",
        ),
        (
            "hPBMC interferon expression increased after transfection.",
            "CORE-HPBMC-TRANSFECTION",
            "CORE-HPBMC-IMMUNE",
        ),
    ],
)
def test_procedural_transfection_does_not_qualify_an_immune_endpoint(
    model_text,
    transfection_slot,
    immune_slot,
):
    packet = {
        "paper_id": "NP-001",
        "evidence": [
            evidence(
                "E-FORM",
                "The NP-001 LNP formulation contained ionizable lipid, "
                "helper lipid, cholesterol, and PEG-lipid.",
            ),
            evidence(
                "E-PAYLOAD",
                "The lipid nanoparticles encapsulated EGFP mRNA payload.",
            ),
            evidence("E-IMMUNE", model_text),
        ],
    }

    report = build_np001_core_slots(packet)
    by_id = {
        row["slot_id"]: row for row in report["evaluated_slots"]
    }

    assert by_id[transfection_slot]["qualified"] is False
    assert by_id[immune_slot]["qualified"] is True


def test_duplicate_is_valid_only_when_an_extracted_slot_shares_record():
    qualified, response = valid_trial_response()
    shared_outcome = outcome(
        "O-DC-SHARED",
        "X-DC",
        "EGFP reporter expression and IL-6 cytokine immune response",
        "E-DC24-TX",
    )
    shared_outcome["qualitative_outcome"]["evidence_ids"].append(
        "E-DC24-IMM"
    )
    response["outcomes"].append(shared_outcome)
    for slot_id, disposition in (
        ("CORE-DC24-TRANSFECTION", "extracted"),
        ("CORE-DC24-IMMUNE", "duplicate"),
    ):
        entry = response["core_slot_accounting"][slot_id]
        entry["disposition"] = disposition
        entry["linked_outcome_ids"] = ["O-DC-SHARED"]

    valid_report = validate(response, qualified)

    assert valid_report["valid_duplicates"] == 1
    assert "CORE-DC24-IMMUNE" in valid_report["confirmed_slot_ids"]

    _qualified, unshared_response = valid_trial_response()
    unshared_response["core_slot_accounting"][
        "CORE-HEPG2-TRANSFECTION"
    ]["disposition"] = "duplicate"

    invalid_report = validate(unshared_response, qualified)

    assert "duplicate_not_shared" in error_codes(invalid_report)
    assert "CORE-HEPG2-TRANSFECTION" not in invalid_report[
        "confirmed_slot_ids"
    ]
