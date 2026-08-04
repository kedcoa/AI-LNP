"""Replay saved application-pilot artifacts without constructing a provider."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from src.extraction.full_paper_contracts import ContextTask, PaperMapResponse
from src.extraction.full_paper_inventory import FullPaperEvidenceInventory
from src.extraction.full_paper_tasks import validate_context_response
from src.extraction.merge_full_paper_results import merge_full_paper_results
from src.extraction.prepare_application_pilot import _extract_output_text
from src.extraction.selective_vision_contracts import SelectiveVisionResponse


_FORBIDDEN_KEY_PARTS = (
    "gold",
    "reference",
    "audit",
    "benchmark_score",
    "known_miss",
    "human_correction",
)

_FORBIDDEN_STRING_MARKERS = (
    "application_pilot_final.json",
    "scientific_reference_audit",
    "reference_bindings",
    "human_audit_corrections",
    "/data/benchmarks/" "application_pilot/",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return value


def _pilot_root(artifact_root: Path) -> Path:
    artifact_root = Path(artifact_root)
    candidate = artifact_root / "data/staging/extraction/application_pilot"
    return candidate if candidate.is_dir() else artifact_root


def _project_root(artifact_root: Path, pilot_root: Path) -> Path:
    if pilot_root == artifact_root:
        return artifact_root.parents[3]
    return artifact_root


def _response_payload(path: Path) -> dict[str, Any]:
    return dict(_extract_output_text(_load(path)))


def _sources_for_paper(
    report: Mapping[str, Any], *, paper_id: str, kind: str
) -> list[Mapping[str, Any]]:
    source_key = "context_sources" if kind == "context" else "vision_sources"
    sources = report.get(source_key)
    if not isinstance(sources, list):
        raise ValueError(f"final report is missing {source_key}")
    return [
        row
        for row in sources
        if isinstance(row, Mapping) and row.get("gate") and row.get("request_id")
    ]


def _request_paper_ids(pilot_root: Path, gate: str) -> dict[str, str]:
    manifest = _load(pilot_root / gate / "manifest.json")
    requests = manifest.get("requests")
    if not isinstance(requests, list):
        raise ValueError(f"{gate} manifest is missing requests")
    return {
        row["request_id"]: row["paper_id"]
        for row in requests
        if isinstance(row, Mapping)
        and isinstance(row.get("request_id"), str)
        and isinstance(row.get("paper_id"), str)
    }


def _selected_response_paths(
    report: Mapping[str, Any], pilot_root: Path, paper_id: str, kind: str
) -> list[Path]:
    selected: list[Path] = []
    request_ids_by_gate: dict[str, dict[str, str]] = {}
    for row in _sources_for_paper(report, paper_id=paper_id, kind=kind):
        gate = str(row["gate"])
        request_id = str(row["request_id"])
        request_ids = request_ids_by_gate.setdefault(
            gate, _request_paper_ids(pilot_root, gate)
        )
        if request_ids.get(request_id) == paper_id:
            selected.append(pilot_root / gate / "run" / request_id / "response.json")
    return selected


def _request_path(response_path: Path) -> Path:
    return (
        response_path.parents[2]
        / "requests"
        / f"{response_path.parent.name}.json"
    )


def replay_source_paths(paper_id: str, artifact_root: Path) -> list[Path]:
    """Return every saved artifact whose bytes can affect a paper replay."""

    pilot_root = _pilot_root(Path(artifact_root))
    project_root = _project_root(Path(artifact_root), pilot_root)
    report_path = project_root / "reports/extraction/application_pilot_final.json"
    report = _load(report_path)
    context_paths = _selected_response_paths(
        report, pilot_root, paper_id, "context"
    )
    vision_paths = _selected_response_paths(report, pilot_root, paper_id, "vision")
    context_gates = {
        str(row["gate"])
        for row in _sources_for_paper(report, paper_id=paper_id, kind="context")
    }
    vision_gates = {
        str(row["gate"])
        for row in _sources_for_paper(report, paper_id=paper_id, kind="vision")
    }
    paths = [
        report_path,
        pilot_root / "validated_maps" / f"{paper_id}.json",
        pilot_root / paper_id / "inventory.json",
        *(
            pilot_root / gate / "manifest.json"
            for gate in sorted(context_gates | vision_gates)
        ),
        *(
            path
            for response_path in [*context_paths, *vision_paths]
            for path in (response_path, _request_path(response_path))
        ),
    ]
    return list(dict.fromkeys(paths))


def _context_task(pilot_root: Path, response_path: Path) -> ContextTask:
    request_path = _request_path(response_path)
    request = _load(request_path)
    messages = request.get("input")
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError(f"context request is missing input messages: {request_path}")
    payload_text = messages[1].get("content") if isinstance(messages[1], Mapping) else None
    schema = request.get("text", {}).get("format", {}).get("schema")
    if not isinstance(payload_text, str) or not isinstance(schema, dict):
        raise ValueError(f"context request is missing its payload or schema: {request_path}")
    payload = json.loads(payload_text)
    return ContextTask(
        context_task_version="full-paper-context-task-1.2.0",
        task_id=response_path.parent.name,
        paper_id=payload["paper_id"],
        context_key=payload["context_key"],
        token_budget=100_000,
        estimated_input_tokens=0,
        shared_formulations=payload["shared_formulations"],
        shared_payloads=payload["shared_payloads"],
        candidates=payload["candidates"],
        evidence=payload["evidence"],
        candidate_evidence_envelopes=payload["candidate_evidence_envelopes"],
        payload=payload,
        response_schema=schema,
    )


def _used_evidence_ids(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        evidence_ids = value.get("evidence_ids")
        direct = {
            evidence_id
            for evidence_id in evidence_ids
            if isinstance(evidence_id, str)
        } if isinstance(evidence_ids, list) else set()
        return direct | set().union(*(_used_evidence_ids(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_used_evidence_ids(child) for child in value))
    return set()


def _inventory_rows(inventory: FullPaperEvidenceInventory) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": block.evidence_id,
            "text": block.text,
            "source": inventory.source_pdf,
            "page_number": block.page_number,
            "heading": block.heading,
            "table_or_figure": None,
        }
        for block in inventory.evidence_blocks
    ]


def _vision_evidence_rows(
    pilot_root: Path, response_paths: Iterable[Path], source: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for response_path in response_paths:
        response = SelectiveVisionResponse.model_validate(_response_payload(response_path))
        request = _load(_request_path(response_path))
        inputs = request.get("input")
        if not isinstance(inputs, list) or len(inputs) < 2:
            raise ValueError(f"vision request has no user input: {response_path}")
        content = inputs[1].get("content") if isinstance(inputs[1], Mapping) else None
        text_item = content[0] if isinstance(content, list) and content else None
        if not isinstance(text_item, Mapping) or not isinstance(text_item.get("text"), str):
            raise ValueError(f"vision request has no text payload: {response_path}")
        task = json.loads(text_item["text"])
        location = task.get("visual_location") if isinstance(task, Mapping) else None
        if not isinstance(location, Mapping):
            raise ValueError(f"vision request has no visual location: {response_path}")
        evidence_id = location.get("crop_evidence_id")
        if not isinstance(evidence_id, str):
            raise ValueError(f"vision request has no crop evidence ID: {response_path}")
        rows.append(
            {
                "evidence_id": evidence_id,
                "text": response.visible_support,
                "source": task.get("source_pdf", source),
                "page_number": location.get("page_number"),
                "heading": None,
                "table_or_figure": location.get("figure_or_table"),
            }
        )
    return rows


def replay_pilot_paper(paper_id: str, artifact_root: Path) -> dict[str, Any]:
    """Reconstruct one post-merge paper from saved, local pilot artifacts."""

    pilot_root = _pilot_root(Path(artifact_root))
    project_root = _project_root(Path(artifact_root), pilot_root)
    report = _load(project_root / "reports/extraction/application_pilot_final.json")
    paper_map = PaperMapResponse.model_validate(
        _extract_output_text(_load(pilot_root / "validated_maps" / f"{paper_id}.json"))
    ).model_dump(mode="json")
    inventory = FullPaperEvidenceInventory.model_validate_json(
        (pilot_root / paper_id / "inventory.json").read_bytes()
    )
    if paper_map["paper_id"] != paper_id or inventory.paper_id != paper_id:
        raise ValueError(f"saved artifacts do not match requested paper {paper_id}")

    context_paths = _selected_response_paths(report, pilot_root, paper_id, "context")
    vision_paths = _selected_response_paths(report, pilot_root, paper_id, "vision")
    context_results = []
    for path in context_paths:
        result = _response_payload(path)
        task = _context_task(pilot_root, path)
        if task.paper_id != paper_id:
            raise ValueError(f"context task does not match requested paper: {path}")
        validate_context_response(result, task)
        context_results.append(result)
    visual_results = [
        SelectiveVisionResponse.model_validate(_response_payload(path)).model_dump(mode="json")
        for path in vision_paths
    ]
    merged = merge_full_paper_results(paper_map, context_results, visual_results)
    replayed = {
        "paper_id": paper_id,
        **merged.model_dump(mode="json"),
        "evidence_sources": [
            *_inventory_rows(inventory),
            *_vision_evidence_rows(pilot_root, vision_paths, inventory.source_pdf),
        ],
    }
    assert_gold_blind(replayed)
    return replayed


def build_evidence_inventory(replayed: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one provenance-preserving row per evidence ID used by a replay."""

    sources = replayed.get("evidence_sources")
    if not isinstance(sources, list):
        raise ValueError("replayed paper is missing local evidence sources")
    used_evidence_ids = _used_evidence_ids(
        {key: value for key, value in replayed.items() if key != "evidence_sources"}
    )
    by_id: dict[str, dict[str, Any]] = {}
    for row in sources:
        if not isinstance(row, Mapping) or not isinstance(row.get("evidence_id"), str):
            raise ValueError("evidence sources require an evidence_id")
        evidence_id = row["evidence_id"]
        normalized = dict(row)
        existing = by_id.get(evidence_id)
        if existing is not None:
            if existing.get("text") != normalized.get("text"):
                raise ValueError(
                    f"conflicting duplicate evidence text for {evidence_id}"
                )
            provenance = (
                "source",
                "page_number",
                "heading",
                "table_or_figure",
            )
            if any(existing.get(key) != normalized.get(key) for key in provenance):
                raise ValueError(
                    f"conflicting duplicate evidence provenance for {evidence_id}"
                )
        by_id.setdefault(evidence_id, normalized)
    return [
        {**row, "used_by_merged_records": evidence_id in used_evidence_ids}
        for evidence_id, row in by_id.items()
    ]


def assert_gold_blind(payload: Mapping[str, Any]) -> None:
    """Reject reference-key and audit-key leakage before a model sees a payload."""

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if isinstance(key, str) and any(
                    part in key.casefold() for part in _FORBIDDEN_KEY_PARTS
                ):
                    raise ValueError(f"gold-blind payload contains forbidden key: {key}")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            normalized = value.casefold().replace("\\", "/")
            if any(marker in normalized for marker in _FORBIDDEN_STRING_MARKERS):
                raise ValueError(
                    "gold-blind payload contains forbidden string marker"
                )

    visit(payload)
