"""Prepare immutable, provider-free request manifests for the application pilot."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.extraction.full_paper_contracts import PaperMapResponse
from src.extraction.full_paper_inventory import FullPaperEvidenceInventory
from src.extraction.full_paper_tasks import (
    CONTEXT_PROMPT,
    build_context_tasks,
    build_paper_map_request,
)
from src.extraction.run_selective_vision import (
    VISION_PROMPT,
    _image_data,
    load_task,
    response_schema,
    vision_fingerprint,
)
from src.rag.compact_api_packet import estimate_tokens


MAP_MAX_OUTPUT_TOKENS = 12_000
CONTEXT_MAX_OUTPUT_TOKENS = 12_000
VISION_MAX_OUTPUT_TOKENS = 2_000
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_TOKEN_BUDGET = 100_000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PilotPaper(StrictModel):
    """One local evidence inventory selected for the three-paper pilot."""

    paper_id: str = Field(min_length=1)
    inventory_path: Path
    model: str = Field(default=DEFAULT_MODEL, min_length=1)
    token_budget: int = Field(default=DEFAULT_TOKEN_BUDGET, gt=0)
    max_output_tokens: int = Field(default=MAP_MAX_OUTPUT_TOKENS, gt=0)


class ApprovalRequest(StrictModel):
    """One exact provider request authorized only as part of its manifest."""

    request_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    request_kind: Literal["paper_map", "context", "selective_vision"]
    request_path: Path
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1)
    estimated_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    source_artifact_path: Path | None = None
    source_artifact_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )


class SourceArtifactBinding(StrictModel):
    """One exact local input independently bound by an approval manifest."""

    binding_kind: Literal["inventory", "map_artifact", "vision_task"]
    paper_id: str = Field(min_length=1)
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApprovalManifest(StrictModel):
    """Complete immutable accounting for one approval gate."""

    manifest_version: Literal["application-pilot-approval-1.0.0"] = (
        "application-pilot-approval-1.0.0"
    )
    gate: Literal["map", "downstream"]
    manifest_path: Path
    request_root: Path
    run_root: Path
    requests: list[ApprovalRequest]
    source_bindings: list[SourceArtifactBinding]
    call_count: int = Field(ge=0)
    total_estimated_input_tokens: int = Field(ge=0)
    total_max_output_tokens: int = Field(ge=0)
    total_estimated_tokens: int = Field(ge=0)
    provider_calls: Literal[0] = 0
    human_approval_required: Literal[True] = True
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_exact_accounting(self) -> "ApprovalManifest":
        request_ids = [row.request_id for row in self.requests]
        request_paths = [row.request_path for row in self.requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("approval request IDs must be unique")
        if len(request_paths) != len(set(request_paths)):
            raise ValueError("approval request paths must be unique")
        binding_keys = [
            (row.binding_kind, row.paper_id, row.path)
            for row in self.source_bindings
        ]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("manifest source bindings must be unique")
        if self.call_count != len(self.requests):
            raise ValueError("manifest call_count must equal its request count")
        input_total = sum(row.estimated_input_tokens for row in self.requests)
        output_total = sum(row.max_output_tokens for row in self.requests)
        if self.total_estimated_input_tokens != input_total:
            raise ValueError("manifest input-token total does not match requests")
        if self.total_max_output_tokens != output_total:
            raise ValueError("manifest output-token total does not match requests")
        if self.total_estimated_tokens != input_total + output_total:
            raise ValueError("manifest total estimated tokens do not match requests")
        kinds = {row.request_kind for row in self.requests}
        if self.gate == "map":
            if self.call_count != 3:
                raise ValueError("map gate requires exactly three requests")
            if kinds != {"paper_map"}:
                raise ValueError("map gate may contain only paper-map requests")
        elif "paper_map" in kinds:
            raise ValueError("downstream gate cannot contain paper-map requests")
        return self


class RunSummary(StrictModel):
    """Terminal accounting for one bounded sequential manifest run."""

    summary_version: Literal["application-pilot-run-1.0.0"] = (
        "application-pilot-run-1.0.0"
    )
    manifest_path: Path
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempted_request_ids: list[str]
    succeeded_request_ids: list[str]
    failed_request_ids: list[str]
    provider_call_count: int = Field(ge=0)
    retry_count: Literal[0] = 0
    repair_count: Literal[0] = 0
    response_artifact_paths: dict[str, Path]
    error_artifact_paths: dict[str, Path]


def _sha256(value: bytes) -> str:
    """Use the same byte-exact SHA-256 approval convention as existing runners."""

    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _freeze_request(
    *,
    index: int,
    paper_id: str,
    request_kind: Literal["paper_map", "context", "selective_vision"],
    request: Mapping[str, Any],
    request_root: Path,
    source_artifact_path: Path | None,
    expected_source_artifact_sha256: str | None = None,
    source_change_label: str = "map artifact",
) -> ApprovalRequest:
    request_id = f"REQ-{index}"
    request_path = (request_root / f"{request_id}.json").resolve()
    request_bytes = _json_bytes(dict(request))
    _atomic_write(request_path, request_bytes)
    model = request.get("model")
    max_output_tokens = request.get("max_output_tokens")
    if not isinstance(model, str) or not model:
        raise ValueError("exact request is missing its model")
    if type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise ValueError("exact request is missing maximum output tokens")
    source_sha256 = None
    if source_artifact_path is not None:
        source_sha256 = _sha256(source_artifact_path.read_bytes())
        if (
            expected_source_artifact_sha256 is not None
            and source_sha256 != expected_source_artifact_sha256
        ):
            phase = (
                "task construction"
                if source_change_label == "map artifact"
                else "request construction"
            )
            raise ValueError(
                f"{source_change_label} bytes changed during {phase}"
            )
    return ApprovalRequest(
        request_id=request_id,
        paper_id=paper_id,
        request_kind=request_kind,
        request_path=request_path,
        request_sha256=_sha256(request_bytes),
        model=model,
        estimated_input_tokens=estimate_tokens(dict(request)),
        max_output_tokens=max_output_tokens,
        source_artifact_path=(
            source_artifact_path.resolve() if source_artifact_path else None
        ),
        source_artifact_sha256=source_sha256,
    )


def _write_manifest(
    *,
    gate: Literal["map", "downstream"],
    output_root: Path,
    requests: list[ApprovalRequest],
    source_bindings: list[SourceArtifactBinding],
) -> ApprovalManifest:
    root = output_root.resolve()
    manifest_path = root / "manifest.json"
    unsigned = {
        "manifest_version": "application-pilot-approval-1.0.0",
        "gate": gate,
        "manifest_path": manifest_path,
        "request_root": root / "requests",
        "run_root": root / "run",
        "requests": [row.model_dump(mode="json") for row in requests],
        "source_bindings": [
            row.model_dump(mode="json") for row in source_bindings
        ],
        "call_count": len(requests),
        "total_estimated_input_tokens": sum(
            row.estimated_input_tokens for row in requests
        ),
        "total_max_output_tokens": sum(
            row.max_output_tokens for row in requests
        ),
        "total_estimated_tokens": sum(
            row.estimated_input_tokens + row.max_output_tokens
            for row in requests
        ),
        "provider_calls": 0,
        "human_approval_required": True,
    }
    json_unsigned = json.loads(
        json.dumps(unsigned, ensure_ascii=False, default=str)
    )
    manifest = ApprovalManifest(
        **json_unsigned,
        approval_hash=_sha256(_canonical_json(json_unsigned).encode("utf-8")),
    )
    _atomic_write(manifest_path, _json_bytes(manifest.model_dump(mode="json")))
    return manifest


def prepare_map_gate(
    papers: Sequence[PilotPaper], output_root: Path
) -> ApprovalManifest:
    """Freeze exactly three paper-map requests without constructing a provider."""

    parsed_papers = [PilotPaper.model_validate(row) for row in papers]
    if len(parsed_papers) != 3:
        raise ValueError("map gate requires exactly three pilot papers")
    paper_ids = [row.paper_id for row in parsed_papers]
    if len(paper_ids) != len(set(paper_ids)):
        raise ValueError("map gate requires three distinct paper IDs")
    request_root = output_root.resolve() / "requests"
    requests: list[ApprovalRequest] = []
    source_bindings: list[SourceArtifactBinding] = []
    for index, paper in enumerate(parsed_papers, start=1):
        inventory_path = paper.inventory_path.resolve()
        inventory_bytes = inventory_path.read_bytes()
        inventory_sha256 = _sha256(inventory_bytes)
        inventory = FullPaperEvidenceInventory.model_validate_json(inventory_bytes)
        if inventory.paper_id != paper.paper_id:
            raise ValueError("pilot paper ID does not match its inventory")
        source_bindings.append(
            SourceArtifactBinding(
                binding_kind="inventory",
                paper_id=paper.paper_id,
                path=inventory_path,
                sha256=inventory_sha256,
            )
        )
        prepared = build_paper_map_request(
            inventory, model=paper.model, token_budget=paper.token_budget
        )
        request = {**prepared.request, "max_output_tokens": paper.max_output_tokens}
        requests.append(
            _freeze_request(
                index=index,
                paper_id=paper.paper_id,
                request_kind="paper_map",
                request=request,
                request_root=request_root,
                source_artifact_path=inventory_path,
                expected_source_artifact_sha256=inventory_sha256,
                source_change_label="inventory",
            )
        )
    return _write_manifest(
        gate="map",
        output_root=output_root,
        requests=requests,
        source_bindings=source_bindings,
    )


def _extract_output_text(value: Mapping[str, Any]) -> Mapping[str, Any]:
    candidate: Any = value.get("paper_map", value)
    if "response" in value:
        response = value["response"]
        if not isinstance(response, Mapping):
            raise ValueError("map response artifact contains an invalid response")
        candidate = response.get("output_text")
    elif "output_text" in value:
        candidate = value["output_text"]
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError("map response output_text is not valid JSON") from exc
    if not isinstance(candidate, Mapping):
        raise ValueError("map artifact does not contain a paper-map object")
    return candidate


def _map_artifact_inputs(
    artifact_path: Path,
) -> tuple[
    PaperMapResponse,
    FullPaperEvidenceInventory,
    str,
    int,
    int,
    list[Path],
    str,
    Path,
    str,
]:
    artifact_bytes = artifact_path.read_bytes()
    raw = json.loads(artifact_bytes)
    if not isinstance(raw, Mapping):
        raise ValueError("map artifact must be a JSON object")
    paper_map = PaperMapResponse.model_validate(_extract_output_text(raw))
    request_metadata = raw.get("approval_request", {})
    if not isinstance(request_metadata, Mapping):
        raise ValueError("map artifact approval_request must be an object")
    if request_metadata:
        if request_metadata.get("request_kind") != "paper_map":
            raise ValueError("map artifact is not bound to a paper-map request")
        if request_metadata.get("paper_id") != paper_map.paper_id:
            raise ValueError("map artifact paper_id does not match Gate-A binding")
    inventory_value = raw.get("inventory")
    inventory_path_value = raw.get(
        "inventory_path", request_metadata.get("source_artifact_path")
    )
    if inventory_value is not None:
        inventory = FullPaperEvidenceInventory.model_validate(inventory_value)
        inventory_binding_path = artifact_path.resolve()
        inventory_sha256 = _sha256(artifact_bytes)
    elif isinstance(inventory_path_value, str) and inventory_path_value:
        inventory_binding_path = Path(inventory_path_value).resolve()
        inventory_bytes = inventory_binding_path.read_bytes()
        inventory_sha256 = _sha256(inventory_bytes)
        recorded_path = request_metadata.get("source_artifact_path")
        recorded_sha256 = request_metadata.get("source_artifact_sha256")
        if request_metadata and (
            recorded_path != str(inventory_binding_path)
            or recorded_sha256 != inventory_sha256
        ):
            raise ValueError("inventory path or hash does not match Gate-A binding")
        inventory = FullPaperEvidenceInventory.model_validate_json(inventory_bytes)
    else:
        raise ValueError("map artifact is missing its evidence inventory binding")
    if inventory.paper_id != paper_map.paper_id:
        raise ValueError("map artifact paper and inventory IDs do not match")
    model = raw.get("model", request_metadata.get("model", DEFAULT_MODEL))
    token_budget = raw.get("token_budget", DEFAULT_TOKEN_BUDGET)
    max_output_tokens = raw.get(
        "max_output_tokens", CONTEXT_MAX_OUTPUT_TOKENS
    )
    vision_paths = raw.get("selective_vision_task_paths", [])
    if (
        not isinstance(model, str)
        or type(token_budget) is not int
        or type(max_output_tokens) is not int
        or not isinstance(vision_paths, list)
        or not all(isinstance(row, str) for row in vision_paths)
    ):
        raise ValueError("map artifact contains invalid downstream settings")
    return (
        paper_map,
        inventory,
        model,
        token_budget,
        max_output_tokens,
        [Path(row) for row in vision_paths],
        _sha256(artifact_bytes),
        inventory_binding_path,
        inventory_sha256,
    )


def _context_request(task: Any, model: str, max_output_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "reasoning": {"effort": "low"},
        "store": False,
        "service_tier": "default",
        "max_output_tokens": max_output_tokens,
        "prompt_cache_key": task.task_id,
        "input": [
            {"role": "system", "content": CONTEXT_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    task.payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "FullPaperContextResponse",
                "schema": task.response_schema,
                "strict": True,
            }
        },
    }


def _vision_request(
    task_path: Path, model: str, expected_paper_id: str
) -> dict[str, Any]:
    task = load_task(task_path)
    if task.paper_id != expected_paper_id:
        raise ValueError("selective vision task paper_id does not match map paper_id")
    return {
        "model": model,
        "reasoning": {"effort": "low"},
        "store": False,
        "service_tier": "default",
        "max_output_tokens": VISION_MAX_OUTPUT_TOKENS,
        "prompt_cache_key": vision_fingerprint(task, model),
        "input": [
            {"role": "system", "content": VISION_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            task.text_payload(),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": _image_data(Path(task.crop_path)),
                        "detail": "original",
                    },
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "SelectiveVisionResponse",
                "schema": response_schema(task),
                "strict": True,
            }
        },
    }


def prepare_downstream_gate(
    map_artifacts: Sequence[Path], output_root: Path
) -> ApprovalManifest:
    """Freeze validated context and selective-vision requests without a provider."""

    request_root = output_root.resolve() / "requests"
    requests: list[ApprovalRequest] = []
    source_bindings: list[SourceArtifactBinding] = []
    for artifact_path in map_artifacts:
        (
            paper_map,
            inventory,
            model,
            token_budget,
            max_output_tokens,
            vision_paths,
            map_artifact_sha256,
            inventory_binding_path,
            inventory_sha256,
        ) = _map_artifact_inputs(Path(artifact_path))
        source_bindings.extend(
            [
                SourceArtifactBinding(
                    binding_kind="map_artifact",
                    paper_id=paper_map.paper_id,
                    path=Path(artifact_path).resolve(),
                    sha256=map_artifact_sha256,
                ),
                SourceArtifactBinding(
                    binding_kind="inventory",
                    paper_id=paper_map.paper_id,
                    path=inventory_binding_path,
                    sha256=inventory_sha256,
                ),
            ]
        )
        for task in build_context_tasks(paper_map, inventory, token_budget):
            request = _context_request(task, model, max_output_tokens)
            requests.append(
                _freeze_request(
                    index=len(requests) + 1,
                    paper_id=paper_map.paper_id,
                    request_kind="context",
                    request=request,
                    request_root=request_root,
                    source_artifact_path=Path(artifact_path),
                    expected_source_artifact_sha256=map_artifact_sha256,
                )
            )
        for task_path in vision_paths:
            request = _vision_request(task_path, model, paper_map.paper_id)
            source_bindings.append(
                SourceArtifactBinding(
                    binding_kind="vision_task",
                    paper_id=paper_map.paper_id,
                    path=task_path.resolve(),
                    sha256=_sha256(task_path.read_bytes()),
                )
            )
            requests.append(
                _freeze_request(
                    index=len(requests) + 1,
                    paper_id=paper_map.paper_id,
                    request_kind="selective_vision",
                    request=request,
                    request_root=request_root,
                    source_artifact_path=task_path,
                    expected_source_artifact_sha256=(
                        _sha256(task_path.read_bytes())
                    ),
                )
            )
    return _write_manifest(
        gate="downstream",
        output_root=output_root,
        requests=requests,
        source_bindings=source_bindings,
    )
