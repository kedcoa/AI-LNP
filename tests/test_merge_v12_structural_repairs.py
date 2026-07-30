import json

import pytest

from src.extraction.merge_v12_structural_repairs import merge
from src.extraction.missing_record_contracts import MissingRecordFragment
from src.extraction.v12_structure_contracts import AtomicOutcomeCandidateV12
from src.rag.compact_api_packet import CompactApiPacket
from tests.test_deterministic_coverage_v12 import (
    candidate,
    experiment,
    outcome,
    provisional,
    reported,
)


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha(value):
    import hashlib

    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _write_inputs(tmp_path, candidates, *, experiments=None):
    result_path = tmp_path / "result.json"
    result_experiments = [experiment()] if experiments is None else experiments
    result = {
        "contract_version": "compact-1.1.0",
        "paper_id": "GP-X",
        "eligibility": {
            "decision": "eligible",
            "reason_codes": [
                "ORIGINAL_EXPERIMENT",
                "IDENTIFIABLE_LNP",
                "SUPPORTED_PAYLOAD",
                "TARGET_CELL_EVIDENCE",
                "USABLE_FORMULATION_OUTCOME_LINKAGE",
            ],
            "evidence_ids": ["E-ANCHOR"],
            "explanation": "The supplied evidence supports an eligible LNP experiment.",
        },
        "formulations": [
            {
                "formulation_id": "F1",
                "formulation_name": reported("LNP", "E-ANCHOR"),
                "composition": reported("ionizable lipid", "E-ANCHOR"),
                "composition_basis": reported(None),
                "np_ratio": reported(None),
            }
        ],
        "components": [],
        "experiments": result_experiments,
        "outcomes": [],
        "unresolved_items": [],
    }
    result_path.write_text(json.dumps(result), encoding="utf-8")
    packet_without_checksum = {
        "packet_version": "compact-api-packet-1.0.0",
        "paper_id": "GP-X",
        "blocked_fields": [],
        "sources": [],
        "evidence": [
            {
                "evidence_id": "E-ANCHOR",
                "text": "eGFP mRNA-LNP in vivo.",
                "source_ids": [],
                "retrieval_field_tags": ["payload"],
                "experiment_candidate_ids": [],
            },
            {
                "evidence_id": "E-KUPFFER",
                "text": "Few F4/80-positive Kupffer cells expressed eGFP.",
                "source_ids": [],
                "retrieval_field_tags": ["outcomes"],
                "experiment_candidate_ids": [],
            },
        ],
    }
    unsigned = CompactApiPacket.model_validate(
        {
            **packet_without_checksum,
            "packet_checksum": "0" * 64,
        }
    ).model_dump(mode="json", exclude={"packet_checksum"}, exclude_none=True)
    packet = {
        **packet_without_checksum,
        "packet_checksum": _sha(_canonical(unsigned)),
    }
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    support = {
        "paper_id": "GP-X",
        "atomic_outcome_candidates": [
            row.model_dump(mode="json") for row in candidates
        ],
        "provisional_experiments": [provisional()],
    }
    support_path = tmp_path / "support.json"
    support_path.write_text(json.dumps(support), encoding="utf-8")
    return result_path, packet_path, support_path, support


def _task(
    tmp_path,
    result_path,
    support,
    candidates,
    *,
    existing_experiment_ids=None,
):
    from src.extraction.missing_record_contracts import MissingRecordTask
    from src.extraction.repair_contracts import RepairEvidence

    unsigned = {
        "task_version": "missing-record-task-1.0.0",
        "paper_id": "GP-X",
        "route_ids": [f"structural:{row.candidate_id}" for row in candidates],
        "candidate_ids": [row.candidate_id for row in candidates],
        "evidence": [
            RepairEvidence(
                evidence_id="E-KUPFFER",
                text="Few F4/80-positive Kupffer cells expressed eGFP.",
                source_ids=[],
            ).model_dump(mode="json")
        ],
        "existing_formulation_ids": ["F1"],
        "existing_experiment_ids": (
            ["EXP1"]
            if existing_experiment_ids is None
            else existing_experiment_ids
        ),
        "existing_outcome_ids": [],
        "permitted_new_experiments": 0,
        "permitted_new_outcomes": 8,
        "source_result_sha256": _sha(result_path.read_bytes()),
        "source_inventory_sha256": _sha(_canonical(support)),
    }
    signed = {**unsigned, "task_checksum": _sha(_canonical(unsigned))}
    MissingRecordTask.model_validate(signed)
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps(signed), encoding="utf-8")
    return task_path


def _resolution(
    candidate_id,
    *,
    status="recovered_existing_experiment",
    outcome_ids=None,
    experiment_ids=None,
    reason=None,
):
    return {
        "candidate_id": candidate_id,
        "status": status,
        "outcome_ids": ["OUT1"] if outcome_ids is None else outcome_ids,
        "experiment_ids": (
            ["EXP1"] if experiment_ids is None else experiment_ids
        ),
        "reason": reason,
    }


def _merge_inputs(
    tmp_path,
    *,
    candidates,
    fragment,
    experiments=None,
):
    result_path, packet_path, support_path, support = _write_inputs(
        tmp_path,
        candidates,
        experiments=experiments,
    )
    existing_experiment_ids = [
        row["experiment_id"]
        for row in (
            [experiment()] if experiments is None else experiments
        )
    ]
    task_path = _task(
        tmp_path,
        result_path,
        support,
        candidates,
        existing_experiment_ids=existing_experiment_ids,
    )
    fragment_path = tmp_path / "fragment.json"
    fragment_path.write_text(fragment.model_dump_json(), encoding="utf-8")
    return {
        "result_path": result_path,
        "packet_path": packet_path,
        "support_path": support_path,
        "pairs": [(task_path, fragment_path)],
        "output_path": tmp_path / "merged.json",
    }


def _merge_inputs_with_unlinked_outcome(tmp_path):
    row = candidate()
    fragment = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=[row.candidate_id],
        unresolved_candidate_ids=[],
        experiments=[],
        outcomes=[outcome()],
        unresolved_reason=None,
        candidate_resolutions=[
            _resolution(
                row.candidate_id,
                outcome_ids=[],
                experiment_ids=["EXP1"],
            )
        ],
    )
    return _merge_inputs(
        tmp_path,
        candidates=[row],
        fragment=fragment,
    )


def _merge_inputs_with_wrong_resolution_link(tmp_path):
    row = candidate()
    experiments = [
        experiment(identifier="EXP1"),
        experiment(identifier="EXP2"),
    ]
    fragment = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=[row.candidate_id],
        unresolved_candidate_ids=[],
        experiments=[],
        outcomes=[outcome(identifier="OUT1", experiment_id="EXP1")],
        unresolved_reason=None,
        candidate_resolutions=[
            _resolution(
                row.candidate_id,
                outcome_ids=["OUT1"],
                experiment_ids=["EXP2"],
            )
        ],
    )
    return _merge_inputs(
        tmp_path,
        candidates=[row],
        fragment=fragment,
        experiments=experiments,
    )


def _valid_multi_experiment_inputs(tmp_path):
    row = candidate()
    experiments = [
        experiment(identifier="EXP1"),
        experiment(identifier="EXP2"),
    ]
    fragment = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=[row.candidate_id],
        unresolved_candidate_ids=[],
        experiments=[],
        outcomes=[
            outcome(identifier="OUT1", experiment_id="EXP1"),
            outcome(identifier="OUT2", experiment_id="EXP2"),
        ],
        unresolved_reason=None,
        candidate_resolutions=[
            _resolution(
                row.candidate_id,
                outcome_ids=["OUT1", "OUT2"],
                experiment_ids=["EXP1", "EXP2"],
            )
        ],
    )
    return _merge_inputs(
        tmp_path,
        candidates=[row],
        fragment=fragment,
        experiments=experiments,
    )


def _cloned_same_experiment_inputs(tmp_path):
    row = candidate()
    fragment = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=[row.candidate_id],
        unresolved_candidate_ids=[],
        experiments=[],
        outcomes=[
            outcome(identifier="OUT1", experiment_id="EXP1"),
            outcome(identifier="OUT2", experiment_id="EXP1"),
        ],
        unresolved_reason=None,
        candidate_resolutions=[
            _resolution(
                row.candidate_id,
                outcome_ids=["OUT1", "OUT2"],
                experiment_ids=["EXP1"],
            )
        ],
    )
    return _merge_inputs(
        tmp_path,
        candidates=[row],
        fragment=fragment,
    )


def _cloned_cross_candidate_inputs(tmp_path):
    first = candidate(candidate_id="AOC-1", claim_ids=["ACL-1"])
    second = candidate(candidate_id="AOC-2", claim_ids=["ACL-2"])
    fragment = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=["AOC-1", "AOC-2"],
        unresolved_candidate_ids=[],
        experiments=[],
        outcomes=[
            outcome(identifier="OUT1", experiment_id="EXP1"),
            outcome(identifier="OUT2", experiment_id="EXP1"),
        ],
        unresolved_reason=None,
        candidate_resolutions=[
            _resolution("AOC-1", outcome_ids=["OUT1"]),
            _resolution("AOC-2", outcome_ids=["OUT2"]),
        ],
    )
    return _merge_inputs(
        tmp_path,
        candidates=[first, second],
        fragment=fragment,
    )


def _mixed_resolution_inputs(tmp_path):
    recovered = candidate(candidate_id="AOC-1", claim_ids=["ACL-1"])
    unresolved = candidate(
        candidate_id="AOC-2",
        claim_ids=["ACL-2"],
        subject_text="liver sinusoidal endothelial cells",
        predicate="reached",
        object_text=None,
        endpoint_text="total insertion frequency",
        qualitative_result=None,
        numeric_value=1.01,
        value_text="1.01 ± 0.38 %",
        unit="%",
    )
    fragment = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=["AOC-1"],
        unresolved_candidate_ids=["AOC-2"],
        experiments=[],
        outcomes=[outcome()],
        unresolved_reason="AOC-2 remains structurally ambiguous.",
        candidate_resolutions=[
            _resolution("AOC-1"),
            _resolution(
                "AOC-2",
                status="unresolved",
                outcome_ids=[],
                experiment_ids=[],
                reason="AOC-2 remains structurally ambiguous.",
            ),
        ],
    )
    return _merge_inputs(
        tmp_path,
        candidates=[recovered, unresolved],
        fragment=fragment,
    )


def test_merge_rejects_returned_outcome_absent_from_resolutions(tmp_path):
    with pytest.raises(ValueError, match="candidate resolution"):
        merge(**_merge_inputs_with_unlinked_outcome(tmp_path))


def test_merge_rejects_resolution_with_wrong_experiment_link(tmp_path):
    with pytest.raises(ValueError, match="experiment"):
        merge(**_merge_inputs_with_wrong_resolution_link(tmp_path))


def test_merge_accepts_one_candidate_with_distinct_verified_experiment_outcomes(
    tmp_path,
):
    report = merge(**_valid_multi_experiment_inputs(tmp_path))
    assert report["candidate_resolutions"][0]["experiment_ids"] == [
        "EXP1",
        "EXP2",
    ]


def test_merge_rejects_cloned_outcomes_for_one_candidate_in_same_experiment(
    tmp_path,
):
    with pytest.raises(ValueError, match="same experiment"):
        merge(**_cloned_same_experiment_inputs(tmp_path))


def test_merge_rejects_cloned_outcomes_split_across_candidate_resolutions(
    tmp_path,
):
    with pytest.raises(ValueError, match="non-claimant"):
        merge(**_cloned_cross_candidate_inputs(tmp_path))


def test_unresolved_candidate_is_quarantined_without_discarding_verified_peer(
    tmp_path,
):
    report = merge(**_mixed_resolution_inputs(tmp_path))
    assert report["recovered_candidate_ids"] == ["AOC-1"]
    assert report["quarantined_candidate_ids"] == ["AOC-2"]
    merged = json.loads(
        (tmp_path / "merged.json").read_text(encoding="utf-8")
    )
    assert [row["outcome_id"] for row in merged["outcomes"]] == ["OUT1"]


def test_merge_rejects_one_broad_outcome_claimed_for_two_candidates(tmp_path):
    first = candidate(candidate_id="AOC-1", claim_ids=["ACL-1"])
    second = candidate(candidate_id="AOC-2", claim_ids=["ACL-2"])
    result_path, packet_path, support_path, support = _write_inputs(
        tmp_path, [first, second]
    )
    task_path = _task(tmp_path, result_path, support, [first, second])
    broad = outcome(
        endpoint="eGFP expression in F4/80-positive Kupffer cells",
        qualitative="Few F4/80-positive Kupffer cells expressed eGFP.",
    )
    fragment = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=["AOC-1", "AOC-2"],
        unresolved_candidate_ids=[],
        experiments=[],
        outcomes=[broad],
        unresolved_reason=None,
    )
    fragment_path = tmp_path / "fragment.json"
    fragment_path.write_text(fragment.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="failed structural verification"):
        merge(
            result_path=result_path,
            packet_path=packet_path,
            support_path=support_path,
            pairs=[(task_path, fragment_path)],
            output_path=tmp_path / "merged.json",
        )
    assert not (tmp_path / "merged.json").exists()


def test_merge_writes_only_a_structurally_confirmed_atomic_repair(tmp_path):
    row = candidate()
    result_path, packet_path, support_path, support = _write_inputs(
        tmp_path, [row]
    )
    task_path = _task(tmp_path, result_path, support, [row])
    fragment = MissingRecordFragment(
        disposition="recovered",
        recovered_candidate_ids=[row.candidate_id],
        unresolved_candidate_ids=[],
        experiments=[],
        outcomes=[outcome()],
        unresolved_reason=None,
    )
    fragment_path = tmp_path / "fragment.json"
    fragment_path.write_text(fragment.model_dump_json(), encoding="utf-8")
    report = merge(
        result_path=result_path,
        packet_path=packet_path,
        support_path=support_path,
        pairs=[(task_path, fragment_path)],
        output_path=tmp_path / "merged.json",
    )
    assert report["structural_verification_passed"]
    assert report["finalization_allowed"]
    assert (tmp_path / "merged.json").exists()
