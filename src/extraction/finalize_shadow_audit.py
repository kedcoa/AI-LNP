"""Finalize gold-blind Codex audit proposals before hidden scoring."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.extraction.build_shadow_benchmark import _issue_replayed_target_ids
from src.extraction.validate_shadow_audit import (
    merge_validated_proposals,
    validate_proposal,
)


_TERMINAL_DISPOSITIONS = {
    "accepted",
    "schema_failure",
    "timeout_or_runtime_failure",
}


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
        parsed = result.get("parsed_result")
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
