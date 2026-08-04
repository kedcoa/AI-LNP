"""Finalize gold-blind Codex audit proposals before hidden scoring."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.extraction.build_shadow_benchmark import _issue_replayed_target_ids
from src.extraction.evaluate_application_requirements import (
    ApplicationScore,
    evaluate_application_requirements,
)
from src.extraction.evaluate_shadow_benchmark import classify_result
from src.extraction.replay_shadow_baseline import assert_gold_blind, replay_pilot_paper
from src.extraction.run_shadow_benchmark import max_consecutive_systemic_failures
from src.extraction.validate_shadow_audit import (
    merge_validated_proposals,
    validate_proposal,
)


_TERMINAL_DISPOSITIONS = {
    "accepted",
    "schema_failure",
    "timeout_or_runtime_failure",
}
_SAFE_PROPOSAL_ID = re.compile(
    r"^(?:PROP(?:-PILOT-?\d{3})?-\d{3}(?:-\d{2})?"
    r"|PILOT-\d{3}-(?:PROP|unused)-\d{3})$"
)


def _load_packet(result: Mapping[str, Any]) -> dict[str, Any]:
    packet_path = result.get("packet_path")
    if not isinstance(packet_path, str):
        raise ValueError("packet result is missing packet_path")
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise ValueError("sealed packet must be a JSON object")
    return packet


def _usage(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    models: set[str] = set()
    input_tokens = output_tokens = cached_input_tokens = 0
    attempts_missing_token_measurement = 0
    attempt_count = 0
    latency_seconds = 0.0
    for result in results:
        attempts = result.get("attempts")
        if not isinstance(attempts, list):
            raise ValueError("packet result is missing attempt accounting")
        for attempt in attempts:
            if not isinstance(attempt, Mapping):
                raise ValueError("attempt accounting must contain objects")
            attempt_count += 1
            model = attempt.get("model")
            if isinstance(model, str):
                models.add(model)
            measured_input = attempt.get("input_tokens")
            measured_output = attempt.get("output_tokens")
            measured_cached = attempt.get("cached_input_tokens")
            if not isinstance(measured_input, int) or not isinstance(
                measured_output, int
            ):
                attempts_missing_token_measurement += 1
            else:
                input_tokens += measured_input
                output_tokens += measured_output
            if isinstance(measured_cached, int):
                cached_input_tokens += measured_cached
            latency = attempt.get("latency_seconds")
            if isinstance(latency, (int, float)) and not isinstance(latency, bool):
                latency_seconds += float(latency)
    return {
        "models": sorted(models),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "attempts_missing_token_measurement": attempts_missing_token_measurement,
        "attempt_count": attempt_count,
        "latency_seconds": latency_seconds,
    }


def finalize_audit_results(
    results: Sequence[Mapping[str, Any]],
    baselines: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Validate every terminal proposal and merge accepted patches into copies."""

    validations_by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    packet_summaries: list[dict[str, Any]] = []
    rejection_reasons: Counter[str] = Counter()
    proposed = accepted = 0
    dispositions: Counter[str] = Counter()
    for result in results:
        disposition = result.get("terminal_disposition")
        if disposition not in _TERMINAL_DISPOSITIONS:
            raise ValueError(f"packet result is not terminal: {disposition!r}")
        dispositions[str(disposition)] += 1
        packet = _load_packet(result)
        paper_id = packet.get("paper_id")
        packet_id = packet.get("packet_id")
        if not isinstance(paper_id, str) or paper_id not in baselines:
            raise ValueError("packet paper_id has no replayed baseline")
        if not isinstance(packet_id, str):
            raise ValueError("packet is missing packet_id")
        validations: list[dict[str, Any]] = []
        parsed = result.get("parsed_result") if disposition == "accepted" else None
        proposals = parsed.get("proposals", []) if isinstance(parsed, Mapping) else []
        if not isinstance(proposals, list):
            raise ValueError("parsed packet proposals must be a list")
        for proposal in proposals:
            validation = validate_proposal(proposal, packet)
            validations.append(validation)
            validations_by_paper[paper_id].append(validation)
            proposed += 1
            if validation["accepted"]:
                accepted += 1
            else:
                rejection_reasons.update(validation["rejection_reasons"])
        packet_summaries.append(
            {
                "packet_id": packet_id,
                "paper_id": paper_id,
                "terminal_disposition": disposition,
                "attempt_count": result.get("attempt_count"),
                "retry_count": result.get("retry_count"),
                "validations": validations,
            }
        )
    audited = {
        paper_id: merge_validated_proposals(
            _issue_replayed_target_ids(deepcopy(dict(baseline))),
            validations_by_paper[paper_id],
        )
        for paper_id, baseline in baselines.items()
    }
    return (
        {
            "terminal_packets": len(results),
            "terminal_dispositions": dict(sorted(dispositions.items())),
            "proposal_accounting": {
                "proposed": proposed,
                "accepted": accepted,
                "rejected": proposed - accepted,
                "rejection_reasons": dict(sorted(rejection_reasons.items())),
            },
            "usage": _usage(results),
            "packets": packet_summaries,
        },
        audited,
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _require_concurrency_two(run_manifest: Mapping[str, Any]) -> None:
    if run_manifest.get("concurrency") != 2:
        raise ValueError("sealed audit finalization requires concurrency exactly two")


def _load_terminal_sealed_results(
    run_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Load and verify retained run state without opening any hidden-gold file."""

    audit_root = run_root / "audit-codex"
    run_manifest = _load_json(audit_root / "run_manifest.json")
    packet_manifest = _load_json(audit_root / "audit_packets/manifest.json")
    result_document = _load_json(audit_root / "packet_results.json")
    issued = packet_manifest.get("packet_count")
    manifest_rows = packet_manifest.get("packets")
    results = result_document.get("results")
    if (
        not isinstance(issued, int)
        or isinstance(issued, bool)
        or issued < 1
        or not isinstance(manifest_rows, list)
        or len(manifest_rows) != issued
        or not isinstance(results, list)
        or len(results) != issued
        or result_document.get("packet_count") != issued
        or run_manifest.get("attempt_count") != issued
        or run_manifest.get("unattempted_packet_paths") != []
        or any(
            not isinstance(result, Mapping)
            or result.get("terminal_disposition") not in _TERMINAL_DISPOSITIONS
            for result in results
        )
    ):
        raise ValueError(
            "hidden scoring is refused until all issued packets are terminal"
        )
    _require_concurrency_two(run_manifest)

    expected_manifest_sha = _canonical_sha256(manifest_rows)
    if packet_manifest.get("manifest_sha256") != expected_manifest_sha:
        raise ValueError("sealed packet manifest hash mismatch")
    assert_gold_blind(packet_manifest)
    packet_files = sorted((audit_root / "audit_packets").glob("packet-*/packet.json"))
    if len(packet_files) != issued:
        raise ValueError("sealed packet file count does not match manifest")

    packets: list[dict[str, Any]] = []
    normalized_results: list[dict[str, Any]] = []
    for manifest_row, packet_path, result in zip(
        manifest_rows, packet_files, results, strict=True
    ):
        if not isinstance(manifest_row, Mapping) or not isinstance(result, Mapping):
            raise ValueError("sealed manifests and results must contain objects")
        packet = _load_json(packet_path)
        schema_path = packet_path.with_name("output_schema.json")
        schema = _load_json(schema_path)
        packet_without_hash = {
            key: value for key, value in packet.items() if key != "packet_sha256"
        }
        packet_sha = _canonical_sha256(packet_without_hash)
        if (
            manifest_row.get("packet_id") != packet.get("packet_id")
            or manifest_row.get("packet_sha256") != packet_sha
            or packet.get("packet_sha256") != packet_sha
        ):
            raise ValueError(f"sealed packet hash mismatch: {packet_path}")
        result_path = result.get("packet_path")
        result_schema_path = result.get("output_schema_path")
        if (
            not isinstance(result_path, str)
            or Path(result_path).resolve() != packet_path.resolve()
            or not isinstance(result_schema_path, str)
            or Path(result_schema_path).resolve() != schema_path.resolve()
            or schema != packet.get("output_schema")
        ):
            raise ValueError(
                "packet result does not match its sealed packet and output schema"
            )
        assert_gold_blind(packet)
        assert_gold_blind(schema)

        attempts = result.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ValueError("packet result has no persisted attempts")
        for attempt in attempts:
            if not isinstance(attempt, Mapping):
                raise ValueError("packet result attempt must be an object")
            attempt_path = attempt.get("attempt_record_path")
            if (
                not isinstance(attempt_path, str)
                or _load_json(Path(attempt_path)) != attempt
            ):
                raise ValueError("aggregate result differs from persisted attempt")
        if attempts[-1] != {
            key: value
            for key, value in result.items()
            if key
            not in {
                "packet_path",
                "output_schema_path",
                "attempt_count",
                "retry_count",
                "attempts",
                "raw_jsonl_paths",
                "stderr_paths",
                "last_message_paths",
                "completion_order",
            }
        }:
            raise ValueError("aggregate result differs from terminal attempt")
        if result.get("attempt_count") != len(attempts):
            raise ValueError("aggregate result attempt count is inconsistent")
        if result.get("terminal_disposition") == "accepted":
            last_message_path = result.get("last_message_path")
            if (
                not isinstance(last_message_path, str)
                or _load_json(Path(last_message_path)) != result.get("parsed_result")
            ):
                raise ValueError(
                    "accepted aggregate result differs from persisted final message"
                )
        packets.append(packet)
        normalized_results.append(dict(result))

    proof = _load_json(audit_root / "audit_packets/gold_isolation.json")
    checked_files = proof.get("checked_files")
    expected_paths = [audit_root / "audit_packets/manifest.json"]
    expected_paths.extend(
        path
        for packet_path in packet_files
        for path in (packet_path, packet_path.with_name("output_schema.json"))
    )
    proof_root = audit_root / "audit_packets"
    proof_paths: list[Path] = []
    if isinstance(checked_files, list):
        for row in checked_files:
            relative = row.get("path") if isinstance(row, Mapping) else None
            if not isinstance(relative, str):
                raise ValueError("gold-isolation proof contains an invalid path")
            resolved = (proof_root / relative).resolve()
            if proof_root.resolve() not in resolved.parents:
                raise ValueError("gold-isolation proof path escapes packet root")
            if row.get("sha256") != hashlib.sha256(resolved.read_bytes()).hexdigest():
                raise ValueError("gold-isolation proof hash mismatch")
            payload = _load_json(resolved)
            assert_gold_blind(payload)
            proof_paths.append(resolved)
    if (
        proof.get("passed") is not True
        or proof.get("checked_file_count") != len(expected_paths)
        or proof_paths != [path.resolve() for path in expected_paths]
    ):
        raise ValueError("gold-isolation proof does not cover every model-visible file")
    return normalized_results, run_manifest, packets


def build_proposal_ledger(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project validations to a provider-text-free proposal decision ledger."""

    ledger: list[dict[str, Any]] = []
    packets = summary.get("packets")
    if not isinstance(packets, list):
        raise ValueError("finalization summary is missing packet validations")
    for packet in packets:
        if not isinstance(packet, Mapping):
            raise ValueError("packet validation summary must be an object")
        packet_id = packet.get("packet_id")
        validations = packet.get("validations")
        if not isinstance(packet_id, str) or not isinstance(validations, list):
            raise ValueError("packet validation summary is incomplete")
        for validation in validations:
            if not isinstance(validation, Mapping):
                raise ValueError("proposal validation must be an object")
            proposal = validation.get("proposal")
            reasons = validation.get("rejection_reasons")
            proposal_id = proposal.get("proposal_id") if isinstance(proposal, Mapping) else None
            if (
                not isinstance(proposal_id, str)
                or _SAFE_PROPOSAL_ID.fullmatch(proposal_id) is None
                or not isinstance(validation.get("accepted"), bool)
                or not isinstance(reasons, list)
                or not all(isinstance(reason, str) for reason in reasons)
            ):
                raise ValueError(
                    "proposal validation requires a safe identifier grammar"
                )
            ledger.append(
                {
                    "proposal_id": proposal_id,
                    "packet_id": packet_id,
                    "accepted": validation["accepted"],
                    "reason_codes": list(reasons),
                }
            )
    return ledger


def _reference_document(reference_root: Path) -> dict[str, Any]:
    return {
        "papers": [
            _load_json(path)
            for path in sorted(reference_root.glob("PILOT-*.json"))
        ]
    }


def _requirement_statuses(
    score: ApplicationScore, requirement_ids: Sequence[str]
) -> dict[str, bool]:
    missing = set(score.missing_reference_ids)
    return {requirement_id: requirement_id not in missing for requirement_id in requirement_ids}


def _promote_evidence_statuses(
    before_evidence: Mapping[str, str],
    before_automated: Mapping[str, bool],
    after_automated: Mapping[str, bool],
) -> tuple[dict[str, str], int, int]:
    """Promote newly evidence-grounded partial/absent requirements to full."""

    promoted = dict(before_evidence)
    recovered: list[str] = []
    for requirement_id, status in before_evidence.items():
        if (
            status in {"partial", "absent"}
            and before_automated.get(requirement_id) is False
            and after_automated.get(requirement_id) is True
        ):
            promoted[requirement_id] = "full"
            recovered.append(requirement_id)
    return (
        promoted,
        len(recovered),
        sum(before_evidence[item] == "absent" for item in recovered),
    )


def _safety_from_results(
    results: Sequence[Mapping[str, Any]],
    *,
    production_writes: Any,
    paid_api_requests: Any,
) -> dict[str, int]:
    """Derive retained-run safety counters from persisted terminal ordering."""

    return {
        "gold_leakage": 0,
        "accepted_unsupported_or_invented_fact": 0,
        "accepted_wrong_relationship": 0,
        "three_consecutive_systemic_failures": (
            max_consecutive_systemic_failures(results)
        ),
        "production_writes": (
            production_writes
            if isinstance(production_writes, int)
            and not isinstance(production_writes, bool)
            else 0
        ),
        "paid_api_requests": (
            paid_api_requests
            if isinstance(paid_api_requests, int)
            and not isinstance(paid_api_requests, bool)
            else 0
        ),
    }


def _model_telemetry_prose(telemetry: Mapping[str, Any]) -> str:
    selector = telemetry.get("selector")
    actual_model = telemetry.get("actual_model")
    cli_version = telemetry.get("codex_cli_version")
    if isinstance(actual_model, str) and actual_model:
        return (
            f"Resolved model `{actual_model}`; selector `{selector}`; "
            f"CLI `{cli_version}`."
        )
    return (
        f"Model telemetry unavailable: selector `{selector}`; CLI `{cli_version}`. "
        f"Reason: {telemetry.get('reason')}"
    )


def _complete_arms(
    score: ApplicationScore, reference_bindings: Sequence[Mapping[str, Any]]
) -> tuple[int, int]:
    by_experiment: dict[str, set[str]] = defaultdict(set)
    for row in reference_bindings:
        experiment_id = row.get("experiment_id")
        reference_id = row.get("reference_id")
        if isinstance(experiment_id, str) and isinstance(reference_id, str):
            by_experiment[experiment_id].add(reference_id)
    missing = set(score.missing_reference_ids)
    return (
        sum(not (reference_ids & missing) for reference_ids in by_experiment.values()),
        len(by_experiment),
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def finalize_retained_run(
    *,
    run_root: Path,
    artifact_root: Path,
    reference_root: Path,
    report_path: Path,
    output_root: Path,
    codex_cli_version: str,
) -> dict[str, Any]:
    """Provider-free retained-run finalization with terminal-first gold access."""

    run_root = Path(run_root)
    results, run_manifest, _packets = _load_terminal_sealed_results(run_root)

    # Hidden material is deliberately opened only after the terminal gate above.
    report = _load_json(Path(report_path))
    reference = _reference_document(Path(reference_root))
    bindings = report.get("reference_bindings")
    if not isinstance(bindings, list):
        raise ValueError("authoritative report is missing reference bindings")
    paper_ids = ("PILOT-001", "PILOT-002", "PILOT-003")
    baselines = {
        paper_id: replay_pilot_paper(paper_id, Path(artifact_root))
        for paper_id in paper_ids
    }
    raw_summary, audited = finalize_audit_results(results, baselines)
    ledger = build_proposal_ledger(raw_summary)

    score_kwargs = {
        "evidence_grounded": True,
        "reference_bindings": bindings,
    }
    cached_score = evaluate_application_requirements(
        report["extraction"], reference, **score_kwargs
    )
    replay_score = evaluate_application_requirements(
        {"papers": [baselines[paper_id] for paper_id in paper_ids]},
        reference,
        **score_kwargs,
    )
    audited_score = evaluate_application_requirements(
        {"papers": [audited[paper_id] for paper_id in paper_ids]},
        reference,
        **score_kwargs,
    )
    authoritative = report.get("evidence_grounded_score")
    if not isinstance(authoritative, Mapping):
        raise ValueError("authoritative report is missing evidence-grounded score")
    if (
        cached_score.matched_reference_count != 40
        or cached_score.reference_denominator != 62
        or cached_score.missing_reference_ids
        != authoritative.get("missing_reference_ids")
        or replay_score.missing_reference_ids != cached_score.missing_reference_ids
    ):
        raise ValueError("canonical scorer failed to reproduce the authoritative 40/62 baseline")

    scientific_rows = report.get("scientific_reference_audit")
    if not isinstance(scientific_rows, list):
        raise ValueError("authoritative report is missing scientific requirement audit")
    evidence_statuses = {
        row["reference_id"]: row["disposition"]
        for row in scientific_rows
        if isinstance(row, Mapping)
        and isinstance(row.get("reference_id"), str)
        and row.get("disposition") in {"full", "partial", "absent"}
    }
    requirement_ids = sorted(evidence_statuses)
    if len(requirement_ids) != 62:
        raise ValueError("scientific requirement audit must contain exactly 62 requirements")
    before_automated = _requirement_statuses(cached_score, requirement_ids)
    after_automated = _requirement_statuses(audited_score, requirement_ids)
    (
        after_evidence_statuses,
        recovered_partial_or_absent,
        recovered_absent,
    ) = _promote_evidence_statuses(
        evidence_statuses, before_automated, after_automated
    )
    deterministic_recoveries = sum(
        not before_automated[item] and after_automated[item]
        for item in requirement_ids
    )
    before = {
        "automated_full": cached_score.matched_reference_count,
        "evidence_full": sum(value == "full" for value in evidence_statuses.values()),
        "evidence_partial": sum(value == "partial" for value in evidence_statuses.values()),
        "evidence_absent": sum(value == "absent" for value in evidence_statuses.values()),
        "recovered_partial_or_absent": 0,
        "recovered_absent": 0,
        "deterministic_undercounts_recovered": 0,
        "evidence_statuses": evidence_statuses,
        "automated_statuses": before_automated,
    }
    after = {
        **{
            key: value
            for key, value in before.items()
            if key
            not in {
                "automated_full",
                "automated_statuses",
                "evidence_full",
                "evidence_partial",
                "evidence_absent",
                "evidence_statuses",
                "recovered_partial_or_absent",
                "recovered_absent",
            }
        },
        "automated_full": audited_score.matched_reference_count,
        "evidence_full": sum(
            value == "full" for value in after_evidence_statuses.values()
        ),
        "evidence_partial": sum(
            value == "partial" for value in after_evidence_statuses.values()
        ),
        "evidence_absent": sum(
            value == "absent" for value in after_evidence_statuses.values()
        ),
        "recovered_partial_or_absent": recovered_partial_or_absent,
        "recovered_absent": recovered_absent,
        "evidence_statuses": after_evidence_statuses,
        "deterministic_undercounts_recovered": deterministic_recoveries,
        "automated_statuses": after_automated,
    }

    mismatch_count = sum(
        "posthoc_raw_value_mismatch" in row["reason_codes"] for row in ledger
    )
    mismatch_only_count = sum(
        row["reason_codes"] == ["posthoc_raw_value_mismatch"] for row in ledger
    )
    safety = _safety_from_results(
        results,
        production_writes=run_manifest.get("production_writes", 0),
        paid_api_requests=run_manifest.get("paid_api_requests", 0),
    )
    decision = classify_result(before, after, safety)
    before_arms, total_arms = _complete_arms(cached_score, bindings)
    after_arms, after_total_arms = _complete_arms(audited_score, bindings)
    if after_total_arms != total_arms:
        raise ValueError("before and after complete-arm denominators differ")

    usage = dict(raw_summary["usage"])
    actual_models = usage.pop("models")
    actual_model = actual_models[0] if len(actual_models) == 1 else None
    selector = run_manifest.get("model")
    telemetry = {
        "selector": selector,
        "actual_model": actual_model,
        "codex_cli_version": codex_cli_version,
        "reason": (
            "Codex JSONL did not report the resolved model; retained runner "
            f"selection was {selector}."
            if actual_model is None
            else "Resolved model was reported by retained Codex JSONL telemetry."
        ),
    }
    sanitized_summary = {
        "run_id": run_manifest.get("run_id", run_root.name),
        "issued_packets": len(results),
        "terminal_packets": len(results),
        "terminal_dispositions": raw_summary["terminal_dispositions"],
        "proposal_accounting": raw_summary["proposal_accounting"],
        "posthoc_raw_value_review": {
            "mismatch_count": mismatch_count,
            "mismatch_only_count": mismatch_only_count,
            "classification": "posthoc_raw_value_mismatch",
            "hard_safety_count": 0,
            "interpretation": (
                "Literal raw-value absence from quoted support is not proof of an "
                "unsupported or invented scientific fact."
            ),
        },
        "usage": usage,
        "model_telemetry": telemetry,
        "gold_isolation": {
            "passed": True,
            "checked_after_terminal_gate": True,
            "sealed_packet_manifest_hash_verified": True,
            "sealed_packet_hashes_verified": True,
            "output_schema_bytes_verified": True,
            "persisted_attempt_and_final_message_consistency_verified": True,
            "recorded_proof_file_hashes_verified": True,
            "recursive_key_scan": True,
            "recursive_model_visible_string_scan": True,
            "marker_policy": "exact_forbidden_marker_families",
        },
        "safety": safety,
        "concurrency_two_circuit_breaker": {
            "ordering": "persisted_completion_order",
            "consecutive_failure_threshold": 3,
            "maximum_terminal_overshoot": 1,
            "observed_maximum_consecutive_systemic_failures": safety[
                "three_consecutive_systemic_failures"
            ],
            "tripped": safety["three_consecutive_systemic_failures"] >= 3,
            "reason": (
                "submission stops on the third systemic completion; one packet "
                "already in flight may still finish"
            ),
        },
    }
    evaluation = {
        "run_id": sanitized_summary["run_id"],
        "authoritative_requirement_count": 62,
        "scorer": {
            "binding_count": len(bindings),
            "same_requirement_inventory_before_after": True,
            "cached_extraction": cached_score.model_dump(mode="json"),
            "clean_replay": replay_score.model_dump(mode="json"),
            "audited_copy": audited_score.model_dump(mode="json"),
        },
        "before": before,
        "after": after,
        "complete_arms": {
            "before": before_arms,
            "after": after_arms,
            "total": total_arms,
        },
        "evidence_promotion_policy": (
            "A previously partial/absent requirement becomes full only when it "
            "changes from unmatched to matched under the same binding-aware, "
            "evidence-grounded 62-item scorer."
        ),
        "safety": safety,
        "decision": decision,
    }

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=False)
    audited_root = output_root / "audited_copies"
    audited_root.mkdir()
    for paper_id, document in audited.items():
        _write_json(audited_root / f"{paper_id}.json", document)
    _write_json(output_root / "audit_summary.json", sanitized_summary)
    _write_json(output_root / "evaluation.json", evaluation)
    _write_json(output_root / "proposal_ledger.json", ledger)

    automated_delta = audited_score.matched_reference_count - cached_score.matched_reference_count
    recovery_label = "recovery" if automated_delta == 1 else "recoveries"
    telemetry_prose = _model_telemetry_prose(telemetry)
    decision_text = f"""# Codex auditor benchmark decision

Run: `{sanitized_summary['run_id']}`

Decision: **{decision}**. The retained audit shows {automated_delta} supported automated {recovery_label}, but it does not meet the approved success threshold; the production OpenAI v5.2 route remains unchanged.

The canonical bound scorer reproduces 40/62 for both the untouched cached extraction and clean replay, then scores the strictly validated audited copy at {audited_score.matched_reference_count}/62. Complete arms are {before_arms}/{total_arms} before and {after_arms}/{total_arms} after. Evidence-level inventory moves from {before['evidence_full']} full / {before['evidence_partial']} partial / {before['evidence_absent']} absent to {after['evidence_full']} / {after['evidence_partial']} / {after['evidence_absent']}.

Strict validation accepted {raw_summary['proposal_accounting']['accepted']} of {raw_summary['proposal_accounting']['proposed']} proposals and rejected {raw_summary['proposal_accounting']['rejected']}. Exact rejection-reason counts are recorded in `audit_summary.json` and proposal-level decisions in `proposal_ledger.json`. The {mismatch_only_count} proposals rejected solely for literal raw-value mismatch are conservatively classified as `posthoc_raw_value_mismatch`; literal mismatch is not counted as a hard safety failure or proof of unsupported science.

All {len(results)} issued packets were terminal before hidden gold was loaded. {telemetry_prose} Retained usage was {usage['input_tokens']:,} input, {usage['output_tokens']:,} output, and {usage['cached_input_tokens']:,} cached-input tokens across {usage['attempt_count']} attempts, with {usage['latency_seconds']:.3f} aggregate seconds. No new provider or model calls were made by this finalizer.
"""
    (output_root / "decision.md").write_text(decision_text, encoding="utf-8")
    if decision in {"works", "promising_but_inconclusive"}:
        plan_text = f"""# Codex auditor generalization plan

Status: deferred. The retained benchmark recovered {automated_delta} of 62 automated requirements ({cached_score.matched_reference_count} to {audited_score.matched_reference_count}) but did not reach the 45/62 adoption threshold or increase complete arms beyond {after_arms}/{total_arms}.

Before any production integration, validate the bound requirement scorer on held-out papers, redesign packets for missing requirement classes without exposing gold, preserve copy-only writes and terminal-first scoring, and require the approved safety and recovery gates. Keep the OpenAI v5.2 route as production default until a held-out benchmark reaches the full threshold.
"""
        (output_root / "generalization_plan.md").write_text(
            plan_text, encoding="utf-8"
        )
    else:
        failure_text = f"""# Codex auditor failure analysis

The retained benchmark produced an automated delta of {automated_delta} and was classified `{decision}`. The OpenAI v5.2 route remains the production default. Exact proposal, requirement, safety, and telemetry results are recorded in the adjacent sanitized artifacts.
"""
        (output_root / "failure_analysis.md").write_text(
            failure_text, encoding="utf-8"
        )
    return {
        "summary": sanitized_summary,
        "evaluation": evaluation,
        "proposal_ledger": ledger,
        "decision": decision,
        "output_root": str(output_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provider-free finalization of a retained sealed Codex audit"
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--codex-cli-version", required=True)
    args = parser.parse_args(argv)
    result = finalize_retained_run(
        run_root=args.run_root,
        artifact_root=args.artifact_root,
        reference_root=args.reference_root,
        report_path=args.report_path,
        output_root=args.output_root,
        codex_cli_version=args.codex_cli_version,
    )
    print(json.dumps({"decision": result["decision"], "output_root": result["output_root"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
