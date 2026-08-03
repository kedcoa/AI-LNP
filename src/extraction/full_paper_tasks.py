"""Prepare and validate gold-blind generalized full-paper extraction tasks."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from src.extraction.compact_contracts import ReportedField
from src.extraction.compact_validation import (
    ValidationFinding,
    ValidationReport,
    validate_candidate,
)
from src.extraction.full_paper_contracts import (
    AnchorCandidate,
    CandidateOutcomeBundle,
    ContextAccountingEntry,
    ContextCandidate,
    ContextTask,
    PaperMapResponse,
    PreparedRequest,
    ProvisionalExperimentContext,
    SharedFormulation,
    SharedPayload,
    build_context_response_schema,
    build_paper_map_schema,
)
from src.extraction.full_paper_inventory import (
    FullPaperEvidenceBlock,
    FullPaperEvidenceInventory,
)
from src.rag.compact_api_packet import estimate_tokens


PAPER_MAP_PROMPT = """\
Build a shared, evidence-grounded map of this paper. Account for every local
anchor. Report formulations, components, ratios and bases, payloads, common
routes/species/models, recipient contexts, and provisional experiment contexts.
Every reported field must cite only supplied evidence IDs. Provisional contexts
must not combine facts unless one supplied record directly supports their joint
membership or the source explicitly supplies pairing/cross-product metadata.
"""

CONTEXT_PROMPT = """\
Extract the supplied experiment-context candidates using the compact response
contract. Account for every candidate ID exactly once in both candidate
accounting and candidate outcomes. Preserve the candidate formulation, payload,
dose/unit, route, species, model, recipient, timepoint/unit identity, and its
locally issued experiment ID. Decompose source claims into atomic foundational,
comparative, and exact-measurement assertions without inventing assertions.
Treat a number as exact only when it is printed in source text, a table, or a
figure label; graph-height estimates are not exact measurements. Link each
outcome to its experiment and cite only evidence inside that candidate's
supplied envelope. Never create or alter an experiment ID.
"""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _anchor_candidates(
    inventory: FullPaperEvidenceInventory,
) -> list[AnchorCandidate]:
    return [
        AnchorCandidate(
            anchor_id=f"ANCHOR::{block.evidence_id}",
            evidence_id=block.evidence_id,
            anchor_types=list(block.retrieval_tags),
        )
        for block in inventory.evidence_blocks
        if block.retrieval_tags
    ]


def _estimated_request_tokens(
    prompt: str,
    payload: Mapping[str, Any],
    response_schema: Mapping[str, Any],
) -> int:
    return (
        estimate_tokens(prompt)
        + estimate_tokens(payload)
        + estimate_tokens(response_schema)
    )


def build_paper_map_request(
    inventory: FullPaperEvidenceInventory,
    model: str,
    token_budget: int,
) -> PreparedRequest:
    """Prepare one exact local paper-map request without provider access."""

    if token_budget <= 0:
        raise ValueError("token_budget must be positive")
    if not model.strip():
        raise ValueError("model cannot be empty")
    anchors = _anchor_candidates(inventory)
    response_schema = build_paper_map_schema(anchors)
    payload = {
        "paper_id": inventory.paper_id,
        "anchor_candidates": [
            row.model_dump(mode="json") for row in anchors
        ],
        "evidence": [
            row.model_dump(mode="json") for row in inventory.evidence_blocks
        ],
        "coverage_diagnostics": [
            row.model_dump(mode="json")
            for row in inventory.coverage_diagnostics
        ],
    }
    estimated_input_tokens = _estimated_request_tokens(
        PAPER_MAP_PROMPT,
        payload,
        response_schema,
    )
    if estimated_input_tokens > token_budget:
        raise ValueError(
            "token_budget cannot hold the complete paper-map request: "
            f"estimated {estimated_input_tokens}, budget {token_budget}"
        )
    fingerprint = _sha256(
        {
            "request_kind": "paper_map",
            "paper_id": inventory.paper_id,
            "model": model,
            "payload": payload,
            "response_schema": response_schema,
        }
    )
    request = {
        "model": model,
        "reasoning": {"effort": "low"},
        "store": False,
        "prompt_cache_key": fingerprint,
        "input": [
            {"role": "system", "content": PAPER_MAP_PROMPT},
            {"role": "user", "content": _canonical_json(payload)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "FullPaperMapResponse",
                "schema": response_schema,
                "strict": True,
            }
        },
    }
    return PreparedRequest(
        prepared_request_version="full-paper-request-1.0.0",
        request_kind="paper_map",
        paper_id=inventory.paper_id,
        model=model,
        token_budget=token_budget,
        estimated_input_tokens=estimated_input_tokens,
        anchor_candidates=anchors,
        evidence=inventory.evidence_blocks,
        payload=payload,
        response_schema=response_schema,
        request=request,
    )


def _all_evidence_ids(value: Any) -> list[str]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key.endswith("evidence_ids") and isinstance(child, list):
                found.extend(
                    item for item in child if isinstance(item, str)
                )
            else:
                found.extend(_all_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_all_evidence_ids(child))
    return list(dict.fromkeys(found))


def _ordered_evidence_ids(
    inventory: FullPaperEvidenceInventory,
    evidence_ids: Iterable[str],
) -> list[str]:
    requested = set(evidence_ids)
    return [
        block.evidence_id
        for block in inventory.evidence_blocks
        if block.evidence_id in requested
    ]


def _validate_paper_map_bindings(
    paper_map: PaperMapResponse,
    inventory: FullPaperEvidenceInventory,
) -> None:
    if paper_map.paper_id != inventory.paper_id:
        raise ValueError(
            "paper map paper_id does not match the evidence inventory"
        )
    anchors = _anchor_candidates(inventory)
    expected_anchor_ids = {row.anchor_id for row in anchors}
    returned_anchor_ids = set(paper_map.anchor_accounting)
    missing = sorted(expected_anchor_ids - returned_anchor_ids)
    invented = sorted(returned_anchor_ids - expected_anchor_ids)
    if missing or invented:
        raise ValueError(
            "paper-map anchor accounting requires exact locally detected keys; "
            f"missing={missing}, unknown={invented}"
        )
    evidence_by_anchor = {
        row.anchor_id: row.evidence_id for row in anchors
    }
    for anchor_id, entry in paper_map.anchor_accounting.items():
        if evidence_by_anchor[anchor_id] not in entry.evidence_ids:
            raise ValueError(
                f"anchor accounting {anchor_id!r} does not cite its local anchor"
            )
    allowed_evidence_ids = {
        block.evidence_id for block in inventory.evidence_blocks
    }
    unknown = sorted(
        set(_all_evidence_ids(paper_map)) - allowed_evidence_ids
    )
    if unknown:
        raise ValueError(
            f"paper map references unknown evidence IDs: {unknown}"
        )


def _field_evidence(
    context: ProvisionalExperimentContext,
    formulation: SharedFormulation,
    payload: SharedPayload,
) -> dict[str, list[str]]:
    joint = list(context.joint_evidence_ids)

    def with_joint(evidence_ids: list[str]) -> list[str]:
        return list(dict.fromkeys([*evidence_ids, *joint]))

    evidence = {
        "formulation": with_joint(formulation.name.evidence_ids),
        "payload": with_joint(payload.identity.evidence_ids),
        "dose": list(context.dose.evidence_ids),
        "dose_unit": list(context.dose_unit.evidence_ids),
        "route": list(context.route.evidence_ids),
        "species": list(context.species.evidence_ids),
        "experimental_model": list(
            context.experimental_model.evidence_ids
        ),
        "recipient_cell": list(context.recipient_cell.evidence_ids),
        "timepoint": list(context.timepoint.evidence_ids),
        "timepoint_unit": list(context.timepoint_unit.evidence_ids),
    }
    if context.organ is not None:
        evidence["organ"] = list(context.organ.evidence_ids)
    return evidence


def _context_candidate(
    paper_id: str,
    context: ProvisionalExperimentContext,
    formulation: SharedFormulation,
    payload: SharedPayload,
) -> ContextCandidate:
    values = {
        "candidate_id": context.provisional_context_id,
        "provisional_context_id": context.provisional_context_id,
        "formulation_id": formulation.formulation_id,
        "formulation": formulation.name.value,
        "payload_id": payload.payload_id,
        "payload": payload.identity.value,
        "dose": context.dose.value,
        "dose_unit": context.dose_unit.value,
        "route": context.route.value,
        "species": context.species.value,
        "experimental_model": context.experimental_model.value,
        "recipient_cell": context.recipient_cell.value,
        "organ": context.organ.value if context.organ is not None else None,
        "timepoint": context.timepoint.value,
        "timepoint_unit": context.timepoint_unit.value,
        "field_evidence_ids": _field_evidence(
            context,
            formulation,
            payload,
        ),
        "joint_evidence_ids": list(context.joint_evidence_ids),
        "outcome_evidence_ids": list(context.outcome_evidence_ids),
        "pairing_metadata": context.pairing_metadata,
    }
    provisional = ContextCandidate(
        experiment_id="locally-issued-after-validation",
        **values,
    )
    return ContextCandidate(
        experiment_id=stable_experiment_id(paper_id, provisional),
        **values,
    )


def stable_experiment_id(
    paper_id: str,
    candidate: ContextCandidate,
) -> str:
    """Issue an experiment ID from validated scientific and evidence identity."""

    if not paper_id.strip():
        raise ValueError("paper_id cannot be empty")
    evidence_identity = {
        "field_evidence_ids": {
            field_name: sorted(set(evidence_ids))
            for field_name, evidence_ids in sorted(
                candidate.field_evidence_ids.items()
            )
        },
        "joint_evidence_ids": sorted(set(candidate.joint_evidence_ids)),
        "pairing_evidence_ids": sorted(
            set(candidate.pairing_metadata.evidence_ids)
            if candidate.pairing_metadata is not None
            else set()
        ),
    }
    return "EXP-" + _sha256(
        {
            "paper_id": paper_id,
            "scientific_identity": candidate.identity,
            "evidence_identity": evidence_identity,
        }
    )[:20]


def _compatibility_key(candidate: ContextCandidate) -> tuple[str, ...]:
    return (
        candidate.recipient_cell.casefold(),
        (candidate.organ or "").casefold(),
        candidate.route.casefold(),
        candidate.species.casefold(),
        candidate.experimental_model.casefold(),
    )


def _context_key(key: tuple[str, ...]) -> str:
    return "|".join(value or "unspecified" for value in key)


def _candidate_envelope(
    *,
    candidate: ContextCandidate,
    formulation: SharedFormulation,
    payload: SharedPayload,
) -> set[str]:
    evidence_ids = {
        evidence_id
        for rows in candidate.field_evidence_ids.values()
        for evidence_id in rows
    }
    evidence_ids.update(candidate.joint_evidence_ids)
    evidence_ids.update(candidate.outcome_evidence_ids)
    evidence_ids.update(_all_evidence_ids(formulation))
    evidence_ids.update(_all_evidence_ids(payload))
    if candidate.pairing_metadata is not None:
        evidence_ids.update(candidate.pairing_metadata.evidence_ids)
    return evidence_ids


def issue_context_candidates(
    paper_map: PaperMapResponse | Mapping[str, Any],
) -> list[ContextCandidate]:
    """Issue deterministic IDs for every validated provisional context."""

    parsed_map = (
        paper_map
        if isinstance(paper_map, PaperMapResponse)
        else PaperMapResponse.model_validate(paper_map)
    )
    formulations_by_id = {
        row.formulation_id: row for row in parsed_map.formulations
    }
    payloads_by_id = {
        row.payload_id: row for row in parsed_map.payloads
    }
    return [
        _context_candidate(
            parsed_map.paper_id,
            context,
            formulations_by_id[context.formulation_id],
            payloads_by_id[context.payload_id],
        )
        for context in parsed_map.provisional_experiment_contexts
    ]


def context_candidate_evidence_envelopes(
    paper_map: PaperMapResponse | Mapping[str, Any],
    candidates: Iterable[ContextCandidate],
) -> dict[str, set[str]]:
    """Return the complete source-backed envelope for issued candidates."""

    parsed_map = (
        paper_map
        if isinstance(paper_map, PaperMapResponse)
        else PaperMapResponse.model_validate(paper_map)
    )
    formulations_by_id = {
        row.formulation_id: row for row in parsed_map.formulations
    }
    payloads_by_id = {
        row.payload_id: row for row in parsed_map.payloads
    }
    return {
        candidate.candidate_id: _candidate_envelope(
            candidate=candidate,
            formulation=formulations_by_id[candidate.formulation_id],
            payload=payloads_by_id[candidate.payload_id],
        )
        for candidate in candidates
    }


def _make_context_task(
    *,
    key: tuple[str, ...],
    candidates: list[ContextCandidate],
    formulations_by_id: Mapping[str, SharedFormulation],
    payloads_by_id: Mapping[str, SharedPayload],
    inventory: FullPaperEvidenceInventory,
    token_budget: int,
) -> ContextTask:
    formulation_ids = list(
        dict.fromkeys(row.formulation_id for row in candidates)
    )
    payload_ids = list(dict.fromkeys(row.payload_id for row in candidates))
    formulations = [
        formulations_by_id[formulation_id]
        for formulation_id in formulation_ids
    ]
    payloads = [payloads_by_id[payload_id] for payload_id in payload_ids]
    envelopes = {
        candidate.candidate_id: _ordered_evidence_ids(
            inventory,
            _candidate_envelope(
                candidate=candidate,
                formulation=formulations_by_id[candidate.formulation_id],
                payload=payloads_by_id[candidate.payload_id],
            ),
        )
        for candidate in candidates
    }
    task_evidence_ids = set().union(
        *(set(rows) for rows in envelopes.values())
    )
    evidence = [
        block
        for block in inventory.evidence_blocks
        if block.evidence_id in task_evidence_ids
    ]
    response_schema = build_context_response_schema(candidates)
    payload = {
        "paper_id": inventory.paper_id,
        "context_key": _context_key(key),
        "shared_formulations": [
            row.model_dump(mode="json") for row in formulations
        ],
        "shared_payloads": [
            row.model_dump(mode="json") for row in payloads
        ],
        "candidates": [
            row.model_dump(mode="json") for row in candidates
        ],
        "candidate_evidence_envelopes": envelopes,
        "evidence": [row.model_dump(mode="json") for row in evidence],
    }
    estimated_input_tokens = _estimated_request_tokens(
        CONTEXT_PROMPT,
        payload,
        response_schema,
    )
    task_id = "FPC-" + _sha256(
        {
            "paper_id": inventory.paper_id,
            "context_key": key,
            "candidate_ids": [
                row.candidate_id for row in candidates
            ],
            "experiment_ids": [
                row.experiment_id for row in candidates
            ],
        }
    )[:16]
    return ContextTask(
        context_task_version="full-paper-context-task-1.1.0",
        task_id=task_id,
        paper_id=inventory.paper_id,
        context_key=_context_key(key),
        token_budget=token_budget,
        estimated_input_tokens=estimated_input_tokens,
        shared_formulations=formulations,
        shared_payloads=payloads,
        candidates=candidates,
        evidence=evidence,
        candidate_evidence_envelopes=envelopes,
        payload=payload,
        response_schema=response_schema,
    )


def build_context_tasks(
    paper_map: PaperMapResponse | Mapping[str, Any],
    inventory: FullPaperEvidenceInventory,
    token_budget: int,
) -> list[ContextTask]:
    """Build evidence-backed candidates and token-pack compatible contexts."""

    if token_budget <= 0:
        raise ValueError("token_budget must be positive")
    parsed_map = (
        paper_map
        if isinstance(paper_map, PaperMapResponse)
        else PaperMapResponse.model_validate(paper_map)
    )
    _validate_paper_map_bindings(parsed_map, inventory)
    formulations_by_id = {
        row.formulation_id: row for row in parsed_map.formulations
    }
    payloads_by_id = {
        row.payload_id: row for row in parsed_map.payloads
    }
    candidates = issue_context_candidates(parsed_map)
    grouped: OrderedDict[tuple[str, ...], list[ContextCandidate]] = (
        OrderedDict()
    )
    for candidate in candidates:
        grouped.setdefault(_compatibility_key(candidate), []).append(candidate)

    tasks: list[ContextTask] = []
    for key, group in grouped.items():
        packed: list[ContextCandidate] = []
        for candidate in group:
            proposed = _make_context_task(
                key=key,
                candidates=[*packed, candidate],
                formulations_by_id=formulations_by_id,
                payloads_by_id=payloads_by_id,
                inventory=inventory,
                token_budget=token_budget,
            )
            if proposed.estimated_input_tokens <= token_budget:
                packed.append(candidate)
                continue
            if packed:
                tasks.append(
                    _make_context_task(
                        key=key,
                        candidates=packed,
                        formulations_by_id=formulations_by_id,
                        payloads_by_id=payloads_by_id,
                        inventory=inventory,
                        token_budget=token_budget,
                    )
                )
                packed = [candidate]
                proposed = _make_context_task(
                    key=key,
                    candidates=packed,
                    formulations_by_id=formulations_by_id,
                    payloads_by_id=payloads_by_id,
                    inventory=inventory,
                    token_budget=token_budget,
                )
            if proposed.estimated_input_tokens > token_budget:
                raise ValueError(
                    "token_budget cannot hold one context candidate: "
                    f"{candidate.candidate_id} estimates "
                    f"{proposed.estimated_input_tokens} tokens"
                )
        if packed:
            tasks.append(
                _make_context_task(
                    key=key,
                    candidates=packed,
                    formulations_by_id=formulations_by_id,
                    payloads_by_id=payloads_by_id,
                    inventory=inventory,
                    token_budget=token_budget,
                )
            )
    return tasks


def _finding(
    *,
    paper_id: str,
    code: str,
    message: str,
    location: list[str | int],
    evidence_ids: Iterable[str] = (),
) -> ValidationFinding:
    finding_id = "VF-" + _sha256(
        [paper_id, code, location, message]
    )[:16]
    return ValidationFinding(
        finding_id=finding_id,
        code=code,
        message=message,
        location=location,
        cited_evidence_ids=list(dict.fromkeys(evidence_ids)),
        repairable=False,
    )


def _reported_value(record: Any, field_name: str) -> Any:
    value = getattr(record, field_name)
    return value.value if isinstance(value, ReportedField) else value


def _same_text(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return " ".join(str(left).casefold().split()) == " ".join(
        str(right).casefold().split()
    )


def _same_number(left: Any, right: float) -> bool:
    return (
        not isinstance(left, bool)
        and isinstance(left, (int, float))
        and float(left) == float(right)
    )


def _record_evidence_ids(records: Iterable[Any]) -> set[str]:
    return {
        evidence_id
        for record in records
        for evidence_id in _all_evidence_ids(record)
    }


def validate_context_response(
    response: Mapping[str, Any] | str,
    task: ContextTask,
) -> ValidationReport:
    """Validate compact records and exhaustive candidate-specific accounting."""

    findings: list[ValidationFinding] = []
    if isinstance(response, str):
        try:
            raw = json.loads(response)
        except json.JSONDecodeError as error:
            return ValidationReport(
                paper_id=task.paper_id,
                status="invalid",
                findings=[
                    _finding(
                        paper_id=task.paper_id,
                        code="invalid_json",
                        message=str(error),
                        location=[],
                    )
                ],
            )
    else:
        raw = dict(response)
    if not isinstance(raw, dict):
        return ValidationReport(
            paper_id=task.paper_id,
            status="invalid",
            findings=[
                _finding(
                    paper_id=task.paper_id,
                    code="invalid_response_type",
                    message="context response must be an object",
                    location=[],
                )
            ],
        )

    accounting_raw = raw.pop("context_candidate_accounting", None)
    candidate_outcomes_raw = raw.pop("candidate_outcomes", None)
    expected_ids = {row.candidate_id for row in task.candidates}
    candidate_by_id = {
        row.candidate_id: row for row in task.candidates
    }
    accounting: dict[str, ContextAccountingEntry] = {}
    if not isinstance(accounting_raw, Mapping):
        findings.append(
            _finding(
                paper_id=task.paper_id,
                code="context_candidate_accounting_not_object",
                message="context_candidate_accounting must be an object",
                location=["context_candidate_accounting"],
            )
        )
        returned_ids: set[str] = set()
    else:
        returned_ids = {str(item) for item in accounting_raw}
    missing_ids = sorted(expected_ids - returned_ids)
    invented_ids = sorted(returned_ids - expected_ids)
    if missing_ids:
        findings.append(
            _finding(
                paper_id=task.paper_id,
                code="missing_candidate_ids",
                message="candidate accounting omitted task candidate IDs",
                location=["context_candidate_accounting"],
            )
        )
    if invented_ids:
        findings.append(
            _finding(
                paper_id=task.paper_id,
                code="invented_candidate_ids",
                message="candidate accounting included unknown candidate IDs",
                location=["context_candidate_accounting"],
            )
        )
    if isinstance(accounting_raw, Mapping):
        for candidate_id in sorted(expected_ids & returned_ids):
            try:
                entry = ContextAccountingEntry.model_validate(
                    accounting_raw[candidate_id]
                )
            except ValidationError as error:
                findings.append(
                    _finding(
                        paper_id=task.paper_id,
                        code="invalid_accounting_entry",
                        message=str(error),
                        location=[
                            "context_candidate_accounting",
                            candidate_id,
                        ],
                        evidence_ids=_all_evidence_ids(
                            accounting_raw[candidate_id]
                        ),
                    )
                )
                continue
            accounting[candidate_id] = entry
            candidate_envelope = set(
                task.candidate_evidence_envelopes[candidate_id]
            )
            outside = sorted(
                set(entry.evidence_ids) - candidate_envelope
            )
            if outside:
                findings.append(
                    _finding(
                        paper_id=task.paper_id,
                        code="candidate_evidence_outside_envelope",
                        message=(
                            "candidate accounting cites evidence outside its "
                            f"envelope: {outside}"
                        ),
                        location=[
                            "context_candidate_accounting",
                            candidate_id,
                            "evidence_ids",
                        ],
                        evidence_ids=outside,
                    )
                )

    if not isinstance(candidate_outcomes_raw, Mapping):
        findings.append(
            _finding(
                paper_id=task.paper_id,
                code="candidate_outcomes_not_object",
                message="candidate_outcomes must be an object",
                location=["candidate_outcomes"],
            )
        )
        returned_outcome_candidate_ids: set[str] = set()
    else:
        returned_outcome_candidate_ids = {
            str(item) for item in candidate_outcomes_raw
        }
    missing_outcome_candidate_ids = sorted(
        expected_ids - returned_outcome_candidate_ids
    )
    invented_outcome_candidate_ids = sorted(
        returned_outcome_candidate_ids - expected_ids
    )
    if missing_outcome_candidate_ids:
        findings.append(
            _finding(
                paper_id=task.paper_id,
                code="missing_candidate_outcome_ids",
                message="candidate outcomes omitted task candidate IDs",
                location=["candidate_outcomes"],
            )
        )
    if invented_outcome_candidate_ids:
        findings.append(
            _finding(
                paper_id=task.paper_id,
                code="invented_candidate_outcome_ids",
                message="candidate outcomes included unknown candidate IDs",
                location=["candidate_outcomes"],
            )
        )
    if isinstance(candidate_outcomes_raw, Mapping):
        for candidate_id in sorted(
            expected_ids & returned_outcome_candidate_ids
        ):
            try:
                bundle = CandidateOutcomeBundle.model_validate(
                    candidate_outcomes_raw[candidate_id]
                )
            except ValidationError as error:
                findings.append(
                    _finding(
                        paper_id=task.paper_id,
                        code="invalid_candidate_outcome_bundle",
                        message=str(error),
                        location=["candidate_outcomes", candidate_id],
                        evidence_ids=_all_evidence_ids(
                            candidate_outcomes_raw[candidate_id]
                        ),
                    )
                )
                continue
            candidate = candidate_by_id[candidate_id]
            if bundle.candidate_id != candidate_id:
                findings.append(
                    _finding(
                        paper_id=task.paper_id,
                        code="candidate_outcome_id_mismatch",
                        message="outcome bundle key must match candidate_id",
                        location=[
                            "candidate_outcomes",
                            candidate_id,
                            "candidate_id",
                        ],
                    )
                )
            if bundle.experiment_id != candidate.experiment_id:
                findings.append(
                    _finding(
                        paper_id=task.paper_id,
                        code="candidate_outcome_experiment_id_mismatch",
                        message=(
                            "outcome bundle must preserve the locally issued "
                            "experiment_id"
                        ),
                        location=[
                            "candidate_outcomes",
                            candidate_id,
                            "experiment_id",
                        ],
                    )
                )
            candidate_envelope = set(
                task.candidate_evidence_envelopes[candidate_id]
            )
            outside = sorted(
                set(_all_evidence_ids(bundle)) - candidate_envelope
            )
            if outside:
                findings.append(
                    _finding(
                        paper_id=task.paper_id,
                        code="candidate_outcome_evidence_outside_envelope",
                        message=(
                            "candidate outcomes cite evidence outside their "
                            f"envelope: {outside}"
                        ),
                        location=["candidate_outcomes", candidate_id],
                        evidence_ids=outside,
                    )
                )

    allowed_evidence_ids = {
        block.evidence_id for block in task.evidence
    }
    compact_response, compact_report = validate_candidate(
        _canonical_json(raw),
        paper_id=task.paper_id,
        allowed_evidence_ids=allowed_evidence_ids,
    )
    findings.extend(compact_report.findings)
    if compact_response is None:
        return ValidationReport(
            paper_id=task.paper_id,
            status="invalid",
            findings=findings,
        )

    formulations = {
        row.formulation_id: row for row in compact_response.formulations
    }
    components_by_formulation: dict[str, list[Any]] = {}
    for component in compact_response.components:
        components_by_formulation.setdefault(
            component.formulation_id,
            [],
        ).append(component)
    experiments = {
        row.experiment_id: row for row in compact_response.experiments
    }
    outcomes = {
        row.outcome_id: row for row in compact_response.outcomes
    }
    linked_experiment_ids = {
        experiment_id
        for entry in accounting.values()
        for experiment_id in entry.linked_experiment_ids
    }
    linked_outcome_ids = {
        outcome_id
        for entry in accounting.values()
        for outcome_id in entry.linked_outcome_ids
    }
    unaccounted_experiment_ids = sorted(
        set(experiments) - linked_experiment_ids
    )
    unaccounted_outcome_ids = sorted(set(outcomes) - linked_outcome_ids)
    if unaccounted_experiment_ids:
        findings.append(
            _finding(
                paper_id=task.paper_id,
                code="unaccounted_returned_experiment_ids",
                message=(
                    "returned experiments must all be linked by candidate "
                    f"accounting: {unaccounted_experiment_ids}"
                ),
                location=["experiments"],
            )
        )
    if unaccounted_outcome_ids:
        findings.append(
            _finding(
                paper_id=task.paper_id,
                code="unaccounted_returned_outcome_ids",
                message=(
                    "returned outcomes must all be linked by candidate "
                    f"accounting: {unaccounted_outcome_ids}"
                ),
                location=["outcomes"],
            )
        )
    linked_outcome_users: dict[str, list[str]] = {}

    for candidate_id, entry in accounting.items():
        if entry.disposition != "extracted":
            continue
        candidate = candidate_by_id[candidate_id]
        unknown_experiments = sorted(
            set(entry.linked_experiment_ids) - set(experiments)
        )
        unknown_outcomes = sorted(
            set(entry.linked_outcome_ids) - set(outcomes)
        )
        if unknown_experiments or unknown_outcomes:
            findings.append(
                _finding(
                    paper_id=task.paper_id,
                    code="unknown_linked_record_ids",
                    message=(
                        "accounting links unknown returned records; "
                        f"experiments={unknown_experiments}, "
                        f"outcomes={unknown_outcomes}"
                    ),
                    location=[
                        "context_candidate_accounting",
                        candidate_id,
                    ],
                )
            )
            continue
        if any(
            outcomes[outcome_id].experiment_id
            not in entry.linked_experiment_ids
            for outcome_id in entry.linked_outcome_ids
        ):
            findings.append(
                _finding(
                    paper_id=task.paper_id,
                    code="outcome_experiment_link_mismatch",
                    message=(
                        "linked outcomes must belong to a linked experiment"
                    ),
                    location=[
                        "context_candidate_accounting",
                        candidate_id,
                        "linked_outcome_ids",
                    ],
                )
            )
        for outcome_id in entry.linked_outcome_ids:
            linked_outcome_users.setdefault(outcome_id, []).append(
                candidate_id
            )

        linked_experiments = [
            experiments[experiment_id]
            for experiment_id in entry.linked_experiment_ids
        ]
        linked_outcomes = [
            outcomes[outcome_id] for outcome_id in entry.linked_outcome_ids
        ]
        scientific_mismatch = False
        for experiment in linked_experiments:
            text_checks = (
                ("payload_name", candidate.payload),
                ("dose_unit", candidate.dose_unit),
                ("route", candidate.route),
                ("species", candidate.species),
                ("experimental_model", candidate.experimental_model),
                ("delivery_recipient_cell", candidate.recipient_cell),
                ("timepoint_unit", candidate.timepoint_unit),
            )
            scientific_mismatch = scientific_mismatch or (
                experiment.formulation_id != candidate.formulation_id
                or not _same_number(
                    _reported_value(experiment, "dose"),
                    candidate.dose,
                )
                or not _same_number(
                    _reported_value(experiment, "timepoint"),
                    candidate.timepoint,
                )
                or any(
                    not _same_text(
                        _reported_value(experiment, field_name),
                        expected,
                    )
                    for field_name, expected in text_checks
                )
            )
            if candidate.organ is not None:
                scientific_mismatch = scientific_mismatch or not _same_text(
                    _reported_value(experiment, "tissue_or_organ"),
                    candidate.organ,
                )
        formulation = formulations.get(candidate.formulation_id)
        if formulation is None or not _same_text(
            _reported_value(formulation, "formulation_name")
            if formulation is not None
            else None,
            candidate.formulation,
        ):
            scientific_mismatch = True
        if scientific_mismatch:
            findings.append(
                _finding(
                    paper_id=task.paper_id,
                    code="candidate_record_mismatch",
                    message=(
                        "linked returned records do not preserve the candidate "
                        "scientific identity"
                    ),
                    location=[
                        "context_candidate_accounting",
                        candidate_id,
                    ],
                )
            )

        linked_records: list[Any] = [
            *linked_experiments,
            *linked_outcomes,
        ]
        if formulation is not None:
            linked_records.append(formulation)
            linked_records.extend(
                components_by_formulation.get(candidate.formulation_id, [])
            )
        cited = _record_evidence_ids(linked_records)
        candidate_envelope = set(
            task.candidate_evidence_envelopes[candidate_id]
        )
        outside = sorted(cited - candidate_envelope)
        if outside:
            findings.append(
                _finding(
                    paper_id=task.paper_id,
                    code="candidate_evidence_outside_envelope",
                    message=(
                        "linked records cite evidence outside the candidate "
                        f"envelope: {outside}"
                    ),
                    location=[
                        "context_candidate_accounting",
                        candidate_id,
                    ],
                    evidence_ids=outside,
                )
            )

    for outcome_id, users in linked_outcome_users.items():
        unique_users = list(dict.fromkeys(users))
        identities = {
            candidate_by_id[candidate_id].identity
            for candidate_id in unique_users
        }
        if len(unique_users) > 1 and len(identities) > 1:
            findings.append(
                _finding(
                    paper_id=task.paper_id,
                    code="outcome_reused_across_incompatible_candidates",
                    message=(
                        "one outcome cannot confirm scientifically "
                        "incompatible candidates"
                    ),
                    location=["outcomes", outcome_id],
                )
            )

    return ValidationReport(
        paper_id=task.paper_id,
        status="invalid" if findings else "valid",
        findings=findings,
    )
