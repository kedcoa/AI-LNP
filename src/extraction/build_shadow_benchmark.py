"""Build immutable, gold-blind cases for the Codex/Ollama shadow benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.extraction.full_paper_contracts import ContextTask
from src.extraction.replay_shadow_baseline import (
    assert_gold_blind,
    build_evidence_inventory,
    replay_pilot_paper,
    replay_source_paths,
)
from src.extraction.shadow_benchmark_contracts import (
    AuditResponse,
    BenchmarkCase,
)


ROOT = Path(__file__).resolve().parents[2]
PAPERS = ("PILOT-001", "PILOT-002", "PILOT-003")
GATE_B_FIXTURE_ROOT = (
    ROOT / "tests/fixtures/codex_ollama_shadow/application_pilot_gate_b"
)
OUTPUT_ROOT = ROOT / "data/staging/extraction/codex_ollama_shadow"

AUDIT_PROMPT = """You are a read-only scientific audit agent. Review only the supplied
paper artifacts. Identify likely omissions, unsupported relationships, wrong-arm
associations, incomplete application-critical fields, and COMET-readiness gaps.
Use only experiment, candidate, record, and evidence IDs present in the payload.
Inventory every supported application-relevant fact as an observation with its
field name, raw value, experiment scope, and evidence IDs. Also report audit
findings. Do not rewrite records, estimate missing numbers, or claim evidence that
is not supplied. Return only JSON matching the provided schema."""

AUDIT_PACKET_INSTRUCTIONS = """You are a read-only scientific audit agent. Review only
the current merged facts and evidence excerpts supplied in this packet. Use only
issued paper, experiment, candidate, record, and evidence IDs. Identify likely
omissions, unsupported relationships, wrong-arm associations, incomplete
application-critical fields, and consistency gaps within the supplied scope. Do not
rewrite records, estimate missing values, use outside knowledge, or cite evidence
that is not supplied. Return only the required structured response."""
AUDIT_PACKET_ABSTENTION = (
    "If the supplied scope cannot support a finding, abstain and state the "
    "unresolved reason rather than inferring a fact."
)
MAX_AUDIT_PACKET_CHARACTERS = 45_000
MAX_AUDIT_PACKET_EVIDENCE_ITEMS = 15
MAX_AUDIT_EVIDENCE_EXCERPT_CHARACTERS = 1_800
AUDIT_PACKET_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["disposition", "proposals", "unresolved_reason"],
    "properties": {
        "disposition": {"type": "string", "enum": ["proposals", "abstained"]},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "proposal_id",
                    "proposal_type",
                    "experiment_id",
                    "candidate_id",
                    "field_name",
                    "raw_values",
                    "evidence_ids",
                    "quoted_support",
                    "record_id",
                    "fact_id",
                    "entity_ids",
                    "arm_id",
                ],
                "properties": {
                    "proposal_id": {"type": "string", "minLength": 1},
                    "proposal_type": {
                        "type": "string",
                        "enum": ["add_fact", "replace_fact", "flag_record"],
                    },
                    "experiment_id": {"type": ["string", "null"]},
                    "candidate_id": {"type": ["string", "null"]},
                    "field_name": {"type": "string", "minLength": 1},
                    "raw_values": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "evidence_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "quoted_support": {"type": "string", "minLength": 1},
                    "record_id": {"type": ["string", "null"], "minLength": 1},
                    "fact_id": {"type": ["string", "null"], "minLength": 1},
                    "entity_ids": {
                        "type": ["array", "null"],
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "arm_id": {"type": ["string", "null"], "minLength": 1},
                },
            },
        },
        "unresolved_reason": {"type": ["string", "null"]},
    },
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_path(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _combined_source_sha(root: Path, paths: list[Path]) -> str:
    rows = [
        {"path": _relative(root, path), "sha256": _sha_path(path)}
        for path in paths
    ]
    return _sha_bytes(_canonical(rows).encode("utf-8"))


def _evidence_ids(value: Any) -> list[str]:
    """Return de-duplicated evidence IDs in their first-seen deterministic order."""

    found: list[str] = []

    def visit(child: Any) -> None:
        if isinstance(child, Mapping):
            evidence_ids = child.get("evidence_ids")
            if isinstance(evidence_ids, list):
                for evidence_id in evidence_ids:
                    if isinstance(evidence_id, str) and evidence_id not in found:
                        found.append(evidence_id)
            for nested in child.values():
                visit(nested)
        elif isinstance(child, list):
            for nested in child:
                visit(nested)

    visit(value)
    return found


def _excerpt(text: str) -> str:
    if len(text) <= MAX_AUDIT_EVIDENCE_EXCERPT_CHARACTERS:
        return text
    return text[: MAX_AUDIT_EVIDENCE_EXCERPT_CHARACTERS - 1] + "…"


def _evidence_lookup(evidence: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in evidence:
        evidence_id = row.get("evidence_id")
        text = row.get("text")
        if not isinstance(evidence_id, str) or not isinstance(text, str):
            raise ValueError("audit packet evidence requires string evidence_id and text")
        full_normalized = {
            "evidence_id": evidence_id,
            "text": text,
            "source": row.get("source"),
            "page_number": row.get("page_number"),
            "heading": row.get("heading"),
            "table_or_figure": row.get("table_or_figure"),
            "used_by_merged_records": row.get("used_by_merged_records") is True,
        }
        existing = by_id.get(evidence_id)
        if existing is not None and existing["_full"] != full_normalized:
            raise ValueError(f"conflicting evidence inventory rows for {evidence_id}")
        by_id[evidence_id] = {
            "evidence_id": evidence_id,
            "excerpt": _excerpt(text),
            "source": full_normalized["source"],
            "page_number": full_normalized["page_number"],
            "heading": full_normalized["heading"],
            "table_or_figure": full_normalized["table_or_figure"],
            "used_by_merged_records": full_normalized["used_by_merged_records"],
            "_full": full_normalized,
        }
    return by_id


def _packet_evidence(
    evidence_by_id: Mapping[str, dict[str, Any]], evidence_ids: Sequence[str]
) -> list[dict[str, Any]]:
    if len(evidence_ids) > MAX_AUDIT_PACKET_EVIDENCE_ITEMS:
        raise ValueError("audit packet scope exceeds 15 evidence items")
    missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_by_id]
    if missing:
        raise ValueError(f"audit packet references evidence absent from inventory: {missing[0]}")
    return [
        {
            key: value
            for key, value in evidence_by_id[evidence_id].items()
            if key != "_full"
        }
        for evidence_id in evidence_ids
    ]


def _issued_ids(
    paper_id: str,
    *,
    experiment_ids: Sequence[str],
    candidate_ids: Sequence[str],
    evidence_ids: Sequence[str],
    current_merged_facts: Any,
) -> dict[str, Any]:
    def target_ids(value: Any, key: str) -> list[str]:
        found: list[str] = []
        if isinstance(value, Mapping):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate not in found:
                found.append(candidate)
            if key == "entity_ids" and isinstance(candidate, list):
                for item in candidate:
                    if isinstance(item, str) and item not in found:
                        found.append(item)
            for child in value.values():
                for item in target_ids(child, key):
                    if item not in found:
                        found.append(item)
        elif isinstance(value, list):
            for child in value:
                for item in target_ids(child, key):
                    if item not in found:
                        found.append(item)
        return found

    issued: dict[str, Any] = {
        "paper_ids": [paper_id],
        "experiment_ids": list(experiment_ids),
        "candidate_ids": list(candidate_ids),
        "evidence_ids": list(evidence_ids),
        "record_ids": target_ids(current_merged_facts, "record_id"),
        "fact_ids": target_ids(current_merged_facts, "fact_id"),
        "entity_ids": target_ids(current_merged_facts, "entity_ids"),
        "arm_ids": [],
        "arm_links": {},
    }
    if len(experiment_ids) == len(candidate_ids):
        for experiment_id, candidate_id in zip(experiment_ids, candidate_ids):
            arm_id = f"ARM-{_sha_bytes(_canonical([paper_id, experiment_id, candidate_id]).encode())[:16]}"
            issued["arm_ids"].append(arm_id)
            issued["arm_links"][arm_id] = {
                "experiment_id": experiment_id,
                "candidate_id": candidate_id,
            }
    return issued


def _seal_packet(packet: dict[str, Any]) -> dict[str, Any]:
    assert_gold_blind(packet)
    sealed = dict(packet)
    sealed["packet_sha256"] = _sha_bytes(_canonical(packet).encode("utf-8"))
    if len(sealed["evidence"]) > MAX_AUDIT_PACKET_EVIDENCE_ITEMS:
        raise ValueError("audit packet contains more than 15 evidence items")
    if len(json.dumps(sealed, ensure_ascii=False)) >= MAX_AUDIT_PACKET_CHARACTERS:
        raise ValueError("audit packet exceeds the 45,000-character limit")
    return sealed


def _build_packet(
    *,
    packet_id: str,
    packet_type: str,
    paper_id: str,
    current_merged_facts: Any,
    evidence_by_id: Mapping[str, dict[str, Any]],
    evidence_ids: Sequence[str],
    experiment_ids: Sequence[str] = (),
    candidate_ids: Sequence[str] = (),
) -> dict[str, Any]:
    return _seal_packet(
        {
            "packet_id": packet_id,
            "packet_type": packet_type,
            "paper_id": paper_id,
            "instructions": AUDIT_PACKET_INSTRUCTIONS,
            "abstention": AUDIT_PACKET_ABSTENTION,
            "output_schema": json.loads(_canonical(AUDIT_PACKET_OUTPUT_SCHEMA)),
            "issued_ids": _issued_ids(
                paper_id,
                experiment_ids=experiment_ids,
                candidate_ids=candidate_ids,
                evidence_ids=evidence_ids,
                current_merged_facts=current_merged_facts,
            ),
            "current_merged_facts": current_merged_facts,
            "evidence": _packet_evidence(evidence_by_id, evidence_ids),
        }
    )


def _project_fact(
    fact: Mapping[str, Any],
    allowed_evidence_ids: set[str] | None = None,
    *,
    include_evidence_free: bool = True,
) -> dict[str, Any] | None:
    field_name = fact.get("field_name")
    if not isinstance(field_name, str):
        raise ValueError("replayed facts require field_name")
    fact_evidence_ids = _evidence_ids(fact)
    if allowed_evidence_ids is not None:
        selected_evidence_ids = [
            evidence_id
            for evidence_id in fact_evidence_ids
            if evidence_id in allowed_evidence_ids
        ]
        if fact_evidence_ids and not selected_evidence_ids:
            return None
        if not fact_evidence_ids and not include_evidence_free:
            return None
    else:
        selected_evidence_ids = fact_evidence_ids
    projected: dict[str, Any] = {"field_name": field_name}
    for key in ("canonical_value", "raw_values"):
        value = fact.get(key)
        if value is not None:
            projected[key] = value
    projected["evidence_ids"] = selected_evidence_ids
    for key in ("record_id", "fact_id", "entity_ids"):
        if key in fact:
            projected[key] = fact[key]
    return projected


def _stable_target_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_sha_bytes(_canonical(value).encode())[:16]}"


def _issue_replayed_target_ids(replayed: Mapping[str, Any]) -> dict[str, Any]:
    """Copy replayed facts and attach deterministic model-visible target IDs."""

    issued = deepcopy(dict(replayed))
    paper_id = issued.get("paper_id")
    if not isinstance(paper_id, str):
        raise ValueError("replayed paper is missing paper_id")

    def issue_facts(facts: Any, record_id: str) -> None:
        if not isinstance(facts, list):
            raise ValueError("replayed facts must be a list")
        for fact in facts:
            if not isinstance(fact, dict):
                raise ValueError("replayed facts must contain objects")
            field_name = fact.get("field_name")
            if not isinstance(field_name, str):
                raise ValueError("replayed facts require field_name")
            fact.setdefault("record_id", record_id)
            fact.setdefault(
                "fact_id",
                _stable_target_id(
                    "FACT",
                    [
                        paper_id,
                        record_id,
                        field_name,
                        fact.get("canonical_value"),
                        fact.get("raw_values"),
                        fact.get("evidence_ids"),
                    ],
                ),
            )
            fact.setdefault(
                "entity_ids",
                [
                    _stable_target_id(
                        "ENT",
                        [paper_id, record_id, field_name, fact.get("canonical_value")],
                    )
                ],
            )

    shared_record_id = _stable_target_id("REC", [paper_id, "shared"])
    issue_facts(issued.get("shared_facts"), shared_record_id)
    experiments = issued.get("experiments")
    if not isinstance(experiments, list):
        raise ValueError("replayed paper is missing experiments")
    for experiment in experiments:
        if not isinstance(experiment, dict):
            raise ValueError("replayed experiments must contain objects")
        experiment_id = experiment.get("experiment_id")
        if not isinstance(experiment_id, str):
            raise ValueError("replayed experiments require experiment_id")
        candidate_id = experiment.get("candidate_id")
        record_id = _stable_target_id(
            "REC", [paper_id, experiment_id, candidate_id if isinstance(candidate_id, str) else None]
        )
        issue_facts(experiment.get("facts"), record_id)
    return issued


def _project_facts(
    facts: Any,
    allowed_evidence_ids: set[str] | None = None,
    *,
    include_evidence_free: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(facts, list):
        raise ValueError("replayed facts must be a list")
    projected = [
        _project_fact(
            fact,
            allowed_evidence_ids,
            include_evidence_free=include_evidence_free,
        )
        for fact in facts
        if isinstance(fact, Mapping)
    ]
    if len(projected) != len(facts):
        raise ValueError("replayed facts must contain objects")
    return [fact for fact in projected if fact is not None]


def _project_experiment(
    experiment: Mapping[str, Any],
    allowed_evidence_ids: set[str] | None = None,
    *,
    include_evidence_free: bool = True,
) -> dict[str, Any]:
    experiment_id = experiment.get("experiment_id")
    if not isinstance(experiment_id, str):
        raise ValueError("replayed experiments require experiment_id")
    projected = {
        "experiment_id": experiment_id,
        "facts": _project_facts(
            experiment.get("facts"),
            allowed_evidence_ids,
            include_evidence_free=include_evidence_free,
        ),
    }
    candidate_id = experiment.get("candidate_id")
    if isinstance(candidate_id, str):
        projected["candidate_id"] = candidate_id
    return projected


def _project_final_entry(
    entry: Mapping[str, Any],
    allowed_evidence_ids: set[str] | None = None,
    *,
    include_evidence_free: bool = True,
) -> dict[str, Any] | None:
    entry_evidence_ids = _evidence_ids(entry)
    if allowed_evidence_ids is not None:
        selected_evidence_ids = [
            evidence_id
            for evidence_id in entry_evidence_ids
            if evidence_id in allowed_evidence_ids
        ]
        if entry_evidence_ids and not selected_evidence_ids:
            return None
        if not entry_evidence_ids and not include_evidence_free:
            return None
    else:
        selected_evidence_ids = entry_evidence_ids
    projected = {
        key: entry[key]
        for key in (
            "conflict_id",
            "finding_id",
            "code",
            "reason",
            "message",
            "severity",
            "experiment_id",
            "candidate_id",
            "field_name",
            "canonical_value",
            "canonical_values",
            "raw_values",
        )
        if key in entry
    }
    projected["evidence_ids"] = selected_evidence_ids
    return projected


def _project_final_entries(
    entries: Any,
    allowed_evidence_ids: set[str] | None = None,
    *,
    include_evidence_free: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ValueError("final consistency entries must be a list")
    projected = [
        _project_final_entry(
            entry,
            allowed_evidence_ids,
            include_evidence_free=include_evidence_free,
        )
        for entry in entries
        if isinstance(entry, Mapping)
    ]
    if len(projected) != len(entries):
        raise ValueError("final consistency entries must contain objects")
    return [entry for entry in projected if entry is not None]


def _evidence_chunks(evidence_ids: Sequence[str]) -> list[list[str]]:
    if not evidence_ids:
        return [[]]
    return [
        list(evidence_ids[index : index + MAX_AUDIT_PACKET_EVIDENCE_ITEMS])
        for index in range(0, len(evidence_ids), MAX_AUDIT_PACKET_EVIDENCE_ITEMS)
    ]


def _build_scoped_packets(
    *,
    packet_id: str,
    packet_type: str,
    paper_id: str,
    evidence_by_id: Mapping[str, dict[str, Any]],
    evidence_ids: Sequence[str],
    current_facts: Callable[[set[str], bool], Any],
    experiment_ids: Sequence[str] = (),
    candidate_ids: Sequence[str] = (),
    always_index: bool = False,
) -> list[dict[str, Any]]:
    """Partition a complete scope until every serialized packet is bounded."""

    chunks = _evidence_chunks(evidence_ids)
    while True:
        packets: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            suffix = f":{index + 1:03d}" if always_index or len(chunks) > 1 else ""
            try:
                packets.append(
                    _build_packet(
                        packet_id=f"{packet_id}{suffix}",
                        packet_type=packet_type,
                        paper_id=paper_id,
                        current_merged_facts=current_facts(set(chunk), index == 0),
                        evidence_by_id=evidence_by_id,
                        evidence_ids=chunk,
                        experiment_ids=experiment_ids,
                        candidate_ids=candidate_ids,
                    )
                )
            except ValueError as exc:
                if (
                    str(exc) != "audit packet exceeds the 45,000-character limit"
                    or len(chunk) <= 1
                ):
                    raise
                midpoint = len(chunk) // 2
                chunks[index : index + 1] = [chunk[:midpoint], chunk[midpoint:]]
                break
        else:
            return packets


def build_audit_packets(
    replayed: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Build bounded, gold-blind audit packets for one replayed paper."""

    replayed = _issue_replayed_target_ids(replayed)
    paper_id = replayed.get("paper_id")
    shared_facts = replayed.get("shared_facts")
    experiments = replayed.get("experiments")
    if not isinstance(paper_id, str):
        raise ValueError("replayed paper is missing paper_id")
    if not isinstance(shared_facts, list) or not isinstance(experiments, list):
        raise ValueError("replayed paper is missing shared_facts or experiments")
    assert_gold_blind(replayed)
    evidence_by_id = _evidence_lookup(evidence)
    packets = _build_scoped_packets(
        packet_id=f"{paper_id}:shared-paper",
        packet_type="shared_paper",
        paper_id=paper_id,
        evidence_by_id=evidence_by_id,
        evidence_ids=_evidence_ids(shared_facts),
        current_facts=lambda selected, first: _project_facts(
            shared_facts,
            selected,
            include_evidence_free=first,
        ),
    )
    experiment_ids: list[str] = []
    for experiment in experiments:
        if not isinstance(experiment, Mapping) or not isinstance(
            experiment.get("experiment_id"), str
        ):
            raise ValueError("replayed experiments require experiment_id")
        experiment_id = experiment["experiment_id"]
        candidate_id = experiment.get("candidate_id")
        candidate_ids = [candidate_id] if isinstance(candidate_id, str) else []
        experiment_ids.append(experiment_id)
        packets.extend(
            _build_scoped_packets(
                packet_id=f"{paper_id}:experiment:{experiment_id}",
                packet_type="experiment",
                paper_id=paper_id,
                evidence_by_id=evidence_by_id,
                evidence_ids=_evidence_ids(experiment),
                current_facts=lambda selected, first, experiment=experiment: _project_experiment(
                    experiment,
                    selected,
                    include_evidence_free=first,
                ),
                experiment_ids=[experiment_id],
                candidate_ids=candidate_ids,
            )
        )
    unused_evidence = [
        row["evidence_id"]
        for row in evidence_by_id.values()
        if not row["used_by_merged_records"]
    ]
    packets.extend(
        _build_scoped_packets(
            packet_id=f"{paper_id}:unused-evidence",
            packet_type="unused_evidence",
            paper_id=paper_id,
            evidence_by_id=evidence_by_id,
            evidence_ids=unused_evidence,
            current_facts=lambda _selected, _first: {
                "paper_id": paper_id,
                "experiment_ids": experiment_ids,
                "scope": "evidence not yet used by the merged records",
            },
            experiment_ids=experiment_ids,
            always_index=True,
        )
    )
    final_facts = {
        "quarantined_conflicts": replayed.get("quarantined_conflicts", []),
        "validation_findings": replayed.get("validation_findings", []),
        "experiment_ids": experiment_ids,
    }
    packets.extend(
        _build_scoped_packets(
            packet_id=f"{paper_id}:final-consistency",
            packet_type="final_consistency",
            paper_id=paper_id,
            evidence_by_id=evidence_by_id,
            evidence_ids=_evidence_ids(final_facts),
            current_facts=lambda selected, first: {
                "quarantined_conflicts": _project_final_entries(
                    final_facts["quarantined_conflicts"],
                    selected,
                    include_evidence_free=first,
                ),
                "validation_findings": _project_final_entries(
                    final_facts["validation_findings"],
                    selected,
                    include_evidence_free=first,
                ),
                "experiment_ids": experiment_ids,
            },
            experiment_ids=experiment_ids,
        )
    )
    return packets


def write_audit_packet_manifest(
    packets: Sequence[Mapping[str, Any]], destination: Path
) -> Path:
    """Write an append-only packet-hash manifest without source or gold paths."""

    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    entries: list[dict[str, str]] = []
    for packet in packets:
        packet_id = packet.get("packet_id")
        packet_sha256 = packet.get("packet_sha256")
        if not isinstance(packet_id, str) or not isinstance(packet_sha256, str):
            raise ValueError("sealed packets require packet_id and packet_sha256")
        expected = _sha_bytes(
            _canonical(
                {key: value for key, value in packet.items() if key != "packet_sha256"}
            ).encode("utf-8")
        )
        if packet_sha256 != expected:
            raise ValueError(f"packet hash does not match contents: {packet_id}")
        entries.append({"packet_id": packet_id, "packet_sha256": packet_sha256})
    if len({entry["packet_id"] for entry in entries}) != len(entries):
        raise ValueError("packet IDs must be unique")
    manifest = {
        "packet_count": len(entries),
        "packets": entries,
        "manifest_sha256": _sha_bytes(_canonical(entries).encode("utf-8")),
    }
    assert_gold_blind(manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def build_audit_cases(
    root: Path = ROOT,
    *,
    artifact_root: Path | None = None,
) -> list[BenchmarkCase]:
    """Build audit inputs by replaying saved post-merge artifacts."""

    replay_root = artifact_root or (root.parent / "np002-selective-vision")
    cases = []
    for paper_id in PAPERS:
        paths = replay_source_paths(paper_id, replay_root)
        replayed = replay_pilot_paper(paper_id, replay_root)
        payload = {
            "paper_id": paper_id,
            "merged_extraction": replayed,
            "evidence_inventory": build_evidence_inventory(replayed),
        }
        assert_gold_blind(payload)
        cases.append(
            BenchmarkCase(
                case_id=f"audit-{paper_id}",
                route="audit",
                paper_id=paper_id,
                source_paths=[_relative(root, path) for path in paths],
                source_sha256=_combined_source_sha(root, paths),
                prompt=AUDIT_PROMPT,
                payload=payload,
                output_schema=AuditResponse.model_json_schema(),
            )
        )
    return cases


def build_gate_b_cases(root: Path = ROOT) -> list[BenchmarkCase]:
    cases = []
    fixture_root = root / GATE_B_FIXTURE_ROOT.relative_to(ROOT)
    paths = sorted(
        fixture_root.glob("REQ-*.json"),
        key=lambda path: int(path.stem.split("-")[1]),
    )
    for path in paths:
        request = _load(path)
        messages = request["input"]
        prompt = messages[0]["content"]
        task_payload = json.loads(messages[1]["content"])
        paper_id = task_payload["paper_id"]
        response_schema = request["text"]["format"]["schema"]
        task = ContextTask(
            context_task_version="full-paper-context-task-1.2.0",
            task_id=path.stem,
            paper_id=paper_id,
            context_key=task_payload["context_key"],
            token_budget=100_000,
            estimated_input_tokens=0,
            shared_formulations=task_payload["shared_formulations"],
            shared_payloads=task_payload["shared_payloads"],
            candidates=task_payload["candidates"],
            evidence=task_payload["evidence"],
            candidate_evidence_envelopes=task_payload[
                "candidate_evidence_envelopes"
            ],
            payload=task_payload,
            response_schema=response_schema,
        )
        relative = _relative(root, path)
        cases.append(
            BenchmarkCase(
                case_id=f"gate-b-{paper_id}-{path.stem.lower()}",
                route="gate_b",
                paper_id=paper_id,
                source_paths=[relative],
                source_sha256=_sha_path(path),
                prompt=prompt,
                payload=task.model_dump(mode="json"),
                output_schema=response_schema,
            )
        )
    return cases


def build_all_cases(
    root: Path = ROOT,
    *,
    artifact_root: Path | None = None,
) -> list[BenchmarkCase]:
    cases = [
        *build_audit_cases(root, artifact_root=artifact_root),
        *build_gate_b_cases(root),
    ]
    ids = [row.case_id for row in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Benchmark case IDs must be unique")
    return cases


def write_case_manifest(
    cases: list[BenchmarkCase], destination: Path
) -> Path:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    route_counts = Counter(row.route for row in cases)
    payload = {
        "benchmark_version": "codex-ollama-shadow-1.0.0",
        "case_count": len(cases),
        "route_counts": dict(sorted(route_counts.items())),
        "paid_api_requests": 0,
        "cases": [row.model_dump(mode="json") for row in cases],
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    destination = (
        args.root
        / OUTPUT_ROOT.relative_to(ROOT)
        / args.run_id
        / "case_manifest.json"
    )
    path = write_case_manifest(build_all_cases(args.root), destination)
    print(path)


if __name__ == "__main__":
    main()
