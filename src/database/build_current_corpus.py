"""Build the canonical, local-only current-corpus routing manifest.

The builder merges reviewed lane documents and hashes existing local files. It
does not read credentials, contact providers, or import scientific evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.database.corpus_manifest import (
    ContributingArtifact,
    CorpusEntry,
    load_lane,
    validate_artifact_coverage,
    validate_corpus,
)


EXPECTED_PAPER_IDS = frozenset(
    [
        *(f"GP-{index:03d}" for index in range(1, 10)),
        "NP-001",
        "NP-002",
        "PILOT-001",
        "PILOT-002",
        "PILOT-003",
    ]
)
SCREENING_ONLY_PAPER_IDS = frozenset({"GP-001", "GP-003", "GP-009"})
DEFAULT_LANE_PATHS = (
    Path("data/manifests/current_corpus_lanes/gp_v1.json"),
    Path("data/manifests/current_corpus_lanes/np_v1.json"),
    Path("data/manifests/current_corpus_lanes/pilot_v1.json"),
)


def build_current_corpus_manifest(
    root: str | Path,
    lane_paths: Iterable[str | Path],
    output_path: str | Path,
) -> dict[str, object]:
    """Merge reviewed lanes into the deterministic Day 2 routing manifest."""

    corpus_root = Path(root).resolve()
    if not corpus_root.is_dir():
        raise ValueError(f"corpus root is not a directory: {corpus_root}")

    resolved_lanes = sorted(
        (_resolve_lane_path(corpus_root, path) for path in lane_paths),
        key=lambda path: _portable_path(corpus_root, path),
    )
    if not resolved_lanes:
        raise ValueError("at least one current-corpus lane is required")

    entries_by_id: dict[str, CorpusEntry] = {}
    source_lanes: list[dict[str, str]] = []
    for lane_path in resolved_lanes:
        source_lanes.append(
            {
                "path": _portable_path(corpus_root, lane_path),
                "sha256": _sha256(lane_path),
            }
        )
        for entry in load_lane(lane_path):
            if entry.paper_id in entries_by_id:
                raise ValueError(
                    f"conflicting lane claims for paper_id {entry.paper_id}"
                )
            entries_by_id[entry.paper_id] = entry

    entries = [entries_by_id[paper_id] for paper_id in sorted(entries_by_id)]
    entries = [
        entry.model_copy(
            update={
                "contributing_artifacts": _contributing_artifacts(
                    corpus_root, entry
                )
            }
        )
        for entry in entries
    ]
    _validate_expected_scope(entries)
    validate_corpus(entries, corpus_root)
    validate_artifact_coverage(entries, corpus_root)
    _validate_import_decisions(entries)

    selected_artifacts = []
    for entry in entries:
        if entry.import_artifact is None:
            continue
        selected_candidate = next(
            candidate
            for candidate in entry.candidate_artifacts
            if candidate.selection_status == "selected"
        )
        selected_artifacts.append(
            {
                "paper_id": entry.paper_id,
                "path": entry.import_artifact,
                "sha256": _sha256(corpus_root / entry.import_artifact),
                "rationale": entry.strongest_artifact_rationale,
                "pipeline_name": selected_candidate.pipeline_name,
                "pipeline_version": selected_candidate.pipeline_version,
            }
        )
    manifest: dict[str, object] = {
        "schema_version": "current-corpus/v1",
        "purpose": "Day 2 supported-evidence import routing",
        "constraints": {
            "paid_api_calls": 0,
            "scientific_extraction_performed": False,
            "evidence_import_performed": False,
        },
        "source_lanes": source_lanes,
        "selected_artifacts": selected_artifacts,
        "artifact_coverage": _artifact_coverage(entries),
        "summary": _summary(entries),
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    _write_json_atomic(_resolve_output_path(corpus_root, output_path), manifest)
    return manifest


def _contributing_artifacts(
    root: Path, entry: CorpusEntry
) -> list[ContributingArtifact]:
    contributors: dict[str, ContributingArtifact] = {}

    def register(
        path_value: str,
        *,
        role: str,
        schema_family: str,
        contributes_facts: bool,
        contributes_evidence: bool,
        pipeline_name: str | None = None,
        pipeline_version: str | None = None,
        validation_status: str | None = None,
        notes: str | None = None,
        expected_sha256: str | None = None,
    ) -> None:
        path = root / path_value
        available = path.is_file()
        contributors[path_value] = ContributingArtifact.model_validate(
            {
                "path": path_value,
                "role": role,
                "access_status": "available" if available else "missing",
                "sha256": _sha256(path) if available else expected_sha256,
                "schema_family": schema_family,
                "pipeline_name": pipeline_name,
                "pipeline_version": pipeline_version,
                "validation_status": validation_status,
                "contributes_facts": contributes_facts,
                "contributes_evidence": contributes_evidence,
                "notes": notes,
            }
        )

    for source in entry.source_access_records:
        if source.source_kind == "compact_packet":
            role = "evidence_inventory"
            contributes_evidence = True
        elif source.source_kind.startswith("full_text"):
            role = "source_document"
            contributes_evidence = True
        else:
            role = "validation"
            contributes_evidence = False
        register(
            source.path,
            role=role,
            schema_family=source.source_kind,
            contributes_facts=False,
            contributes_evidence=contributes_evidence,
            validation_status=source.access_status,
            notes=source.notes,
            expected_sha256=source.sha256,
        )

    for candidate in entry.candidate_artifacts:
        selected = candidate.selection_status == "selected"
        valid_slice = (
            candidate.selection_status == "candidate"
            and (candidate.validation_status or "").startswith("valid_")
        )
        rejected_pilot_ledger = (
            candidate.artifact_kind == "consolidated_replay"
            and candidate.selection_status == "rejected"
        )
        if not (selected or valid_slice or rejected_pilot_ledger):
            continue
        register(
            candidate.path,
            role=(
                "primary_extraction" if selected else "contributing_extraction"
            ),
            schema_family=candidate.artifact_kind,
            contributes_facts=True,
            contributes_evidence=True,
            pipeline_name=candidate.pipeline_name,
            pipeline_version=candidate.pipeline_version,
            validation_status=candidate.validation_status,
            notes=candidate.notes,
            expected_sha256=candidate.sha256,
        )

    if entry.import_artifact is not None:
        selected_path = root / entry.import_artifact
        for filename, role, facts, evidence in (
            ("source_clauses.json", "evidence_inventory", False, True),
            ("clause_provenance.json", "evidence_inventory", False, True),
            ("final_audit.json", "validation", False, False),
        ):
            sibling = selected_path.with_name(filename)
            if sibling.is_file():
                register(
                    sibling.relative_to(root).as_posix(),
                    role=role,
                    schema_family=filename.removesuffix(".json"),
                    contributes_facts=facts,
                    contributes_evidence=evidence,
                    pipeline_name="g1_fulltext_rag",
                    validation_status="local",
                )

    if entry.paper_id.startswith("GP-") and entry.import_status != "screening_only":
        for annotation_name in (
            "papers.csv",
            "formulations.csv",
            "components.csv",
            "experiments.csv",
            "outcomes.csv",
            "evidence.csv",
            "issues.csv",
        ):
            annotation_path = f"data/annotations/gold_v1/{annotation_name}"
            if (root / annotation_path).is_file():
                register(
                    annotation_path,
                    role="annotation",
                    schema_family="gold_v1_annotation",
                    contributes_facts=annotation_name not in {"evidence.csv", "issues.csv"},
                    contributes_evidence=annotation_name == "evidence.csv",
                    pipeline_name="gold_v1",
                    validation_status="human_annotation",
                )

    source_directory = (
        root / "data/raw/fulltext/oa_packages" / (entry.pmcid or "missing")
    )
    if source_directory.is_dir():
        for source_path in sorted(source_directory.iterdir()):
            if not source_path.is_file() or source_path.suffix.casefold() not in {
                ".pdf",
                ".xml",
                ".nxml",
            }:
                continue
            lower_name = source_path.name.casefold()
            is_supplement = "supp" in lower_name or "sapp" in lower_name
            register(
                source_path.relative_to(root).as_posix(),
                role="supplement" if is_supplement else "source_document",
                schema_family="supplement_pdf" if is_supplement else "full_text_source",
                contributes_facts=False,
                contributes_evidence=True,
                validation_status="local_source",
            )

    vision_root = root / "data/staging/extraction/day8_object_vision/results"
    if vision_root.is_dir():
        for vision_path in sorted(vision_root.glob(f"{entry.paper_id}-*.json")):
            if not (
                vision_path.name.endswith(".validated.json")
                or vision_path.name.endswith(".human_corrected.json")
            ):
                continue
            register(
                vision_path.relative_to(root).as_posix(),
                role="vision",
                schema_family="validated_visual_claims",
                contributes_facts=True,
                contributes_evidence=True,
                pipeline_name="day8_object_vision",
                validation_status="accepted",
            )

    return [contributors[path] for path in sorted(contributors)]


def _artifact_coverage(
    entries: Sequence[CorpusEntry],
) -> dict[str, dict[str, object]]:
    return {
        entry.paper_id: {
            "contributor_count": len(entry.contributing_artifacts),
            "missing_files": [
                artifact.path
                for artifact in entry.contributing_artifacts
                if artifact.access_status != "available"
            ],
            "hash_mismatches": [],
            "fact_producing_artifacts": [
                artifact.path
                for artifact in entry.contributing_artifacts
                if artifact.contributes_facts
            ],
            "evidence_producing_artifacts": [
                artifact.path
                for artifact in entry.contributing_artifacts
                if artifact.contributes_evidence
            ],
            "primary_artifact": entry.import_artifact,
        }
        for entry in entries
    }


def write_day1_reports(
    manifest: Mapping[str, object], report_root: str | Path
) -> tuple[Path, Path]:
    """Write deterministic reports atomically, making repeated runs idempotent."""

    destination = Path(report_root)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "day1_current_corpus_inventory.json"
    markdown_path = destination / "day1_current_corpus_inventory.md"

    entries = _report_entries(manifest)
    summary = manifest.get("summary")
    selected_artifacts = manifest.get("selected_artifacts")
    if not isinstance(summary, Mapping) or not isinstance(selected_artifacts, list):
        raise ValueError("manifest is missing summary or selected_artifacts")

    unresolved = [
        {
            "paper_id": entry["paper_id"],
            "reason": entry["rerun_reason"],
        }
        for entry in entries
        if entry["import_status"] != "screening_only"
        and entry["import_artifact"] is None
    ]
    report: dict[str, object] = {
        "schema_version": "day1-current-corpus-inventory/v1",
        "summary": dict(summary),
        "selected_artifacts": selected_artifacts,
        "unresolved_import_candidates": unresolved,
        "routing": {
            status: [
                entry["paper_id"]
                for entry in entries
                if entry["import_status"] == status
            ]
            for status in sorted({str(entry["import_status"]) for entry in entries})
        },
    }
    _write_json_atomic(json_path, report)
    _write_text_atomic(markdown_path, _render_markdown(entries, summary))
    return json_path, markdown_path


def _validate_expected_scope(entries: Sequence[CorpusEntry]) -> None:
    paper_ids = {entry.paper_id for entry in entries}
    if paper_ids != EXPECTED_PAPER_IDS:
        missing = sorted(EXPECTED_PAPER_IDS - paper_ids)
        unexpected = sorted(paper_ids - EXPECTED_PAPER_IDS)
        raise ValueError(
            "current corpus must contain exactly the 14 reviewed paper IDs; "
            f"missing={missing}, unexpected={unexpected}"
        )

    screening_only = {
        entry.paper_id for entry in entries if entry.import_status == "screening_only"
    }
    if screening_only != SCREENING_ONLY_PAPER_IDS:
        raise ValueError(
            "screening-only papers must be exactly GP-001, GP-003, and GP-009; "
            f"found={sorted(screening_only)}"
        )


def _validate_import_decisions(entries: Sequence[CorpusEntry]) -> None:
    for entry in entries:
        if entry.import_status == "screening_only":
            continue
        if entry.import_artifact is None and not (entry.rerun_reason or "").strip():
            raise ValueError(
                f"{entry.paper_id} requires a selected artifact or explicit reason"
            )


def _summary(entries: Sequence[CorpusEntry]) -> dict[str, object]:
    import_status_counts = Counter(entry.import_status for entry in entries)
    rerun_status_counts = Counter(entry.rerun_status for entry in entries)
    import_candidates = [
        entry for entry in entries if entry.import_status != "screening_only"
    ]
    return {
        "total_papers": len(entries),
        "import_candidates": len(import_candidates),
        "screening_only": import_status_counts["screening_only"],
        "selected_artifacts": sum(
            entry.import_artifact is not None for entry in entries
        ),
        "explicit_unresolved_reasons": sum(
            entry.import_artifact is None and bool((entry.rerun_reason or "").strip())
            for entry in import_candidates
        ),
        "import_status_counts": dict(sorted(import_status_counts.items())),
        "rerun_status_counts": dict(sorted(rerun_status_counts.items())),
        "paid_api_calls": 0,
    }


def _report_entries(manifest: Mapping[str, object]) -> list[dict[str, object]]:
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list) or not all(
        isinstance(entry, dict) for entry in raw_entries
    ):
        raise ValueError("manifest entries must be a list of objects")
    return raw_entries


def _render_markdown(
    entries: Sequence[Mapping[str, object]], summary: Mapping[str, object]
) -> str:
    lines = [
        "# Day 1 current-corpus inventory",
        "",
        "Canonical local-only routing inventory for Day 2 supported-evidence import.",
        "No evidence was imported and no scientific extraction was performed.",
        "",
        "## Verified counts",
        "",
        f"- Total papers: **{summary['total_papers']}**",
        f"- Import candidates: **{summary['import_candidates']}**",
        f"- Screening-only records: **{summary['screening_only']}**",
        f"- Selected supported artifacts: **{summary['selected_artifacts']}**",
        f"- Included records with an explicit unresolved reason: **{summary['explicit_unresolved_reasons']}**",
        f"- Paid/API/LLM calls recorded: **{summary['paid_api_calls']}**",
        "",
        "## Day 2 routing",
        "",
        "| Paper | Import status | Rerun status | Selected artifact or explicit reason |",
        "| --- | --- | --- | --- |",
    ]
    for entry in entries:
        decision = entry["import_artifact"] or entry["rerun_reason"] or (
            "Screening-ledger-only record; no import artifact permitted."
        )
        lines.append(
            "| {paper_id} | {import_status} | {rerun_status} | {decision} |".format(
                paper_id=_markdown_cell(entry["paper_id"]),
                import_status=_markdown_cell(entry["import_status"]),
                rerun_status=_markdown_cell(entry["rerun_status"]),
                decision=_markdown_cell(decision),
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This inventory selects or defers local artifacts only. Field- and "
            "arm-level validation, evidence import, and any authorized selective "
            "repair remain Day 2-3 work.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _resolve_lane_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_file():
        raise ValueError(f"current-corpus lane does not exist: {resolved}")
    return resolved


def _resolve_output_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _portable_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    _write_text_atomic(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--lane", action="append", type=Path, dest="lane_paths")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = args.root.resolve()
    lane_paths = args.lane_paths or list(DEFAULT_LANE_PATHS)
    output = _resolve_output_path(root, args.output)
    report_root = _resolve_output_path(root, args.report_root)
    manifest = build_current_corpus_manifest(root, lane_paths, output)
    write_day1_reports(manifest, report_root)
    print(json.dumps(manifest["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
