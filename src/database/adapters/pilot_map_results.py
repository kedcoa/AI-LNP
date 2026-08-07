"""Promote completed, inventory-bound PILOT paper maps conservatively.

The map gate already ran successfully for the three PILOT papers.  This adapter
validates those immutable response artifacts against their bound evidence
inventories and projects only explicitly cited formulation and provisional-arm
fields.  It never treats a paper-map outcome evidence ID as a normalized
outcome value because the map contract does not contain that value.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from src.database.import_contracts import (
    ArmRecord,
    ComponentRecord,
    FieldEvidenceLink,
    FormulationRecord,
    ImportBundle,
    OutcomeRecord,
    ReviewRecord,
    SourceArtifactRecord,
)
from src.database.lossless_adapter import AdapterCoverage, LosslessAdapterResult
from src.database.scientific_identity import fact_identity
from src.database.source_fact_import import (
    SourceArtifactRecord as LedgerArtifactRecord,
    SourceFactEvidenceRecord,
    SourceFactRecord,
)
from src.extraction.prepare_application_pilot import (
    _canonical_json,
    _map_artifact_inputs,
    _sha256,
)


_FULL_RATIO = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?(?::\d+(?:\.\d+)?){2,})(?![\d.])"
)
_OUTCOME_FIELD = re.compile(
    r"^outcome\.(?P<outcome_id>[^.]+)\.(?P<field_name>"
    r"assay|endpoint|comparator|outcome_value|outcome_unit|qualitative_outcome)$"
)


def pilot_map_logical_path(path: Path) -> str:
    """Return the checkout-independent path of a preserved pilot map."""

    resolved = Path(path).resolve()
    marker = ("data", "staging", "extraction", "application_pilot")
    parts = resolved.parts
    for index in range(len(parts) - len(marker) + 1):
        if tuple(parts[index:index + len(marker)]) == marker:
            return Path(*parts[index:]).as_posix()
    return resolved.as_posix()


def _repository_logical_path(path: Path) -> str:
    resolved = path.resolve()
    for root in resolved.parents:
        if (root / "src/database").is_dir() and (root / "data").is_dir():
            return resolved.relative_to(root).as_posix()
    return resolved.as_posix()


def _reported_fact_value(row: dict[str, Any]) -> Any:
    raw_values = row.get("raw_values")
    if isinstance(raw_values, list) and raw_values:
        return raw_values[0]
    return row.get("canonical_value")


def _consolidated_outcome_groups(
    path: Path,
    paper_id: str,
) -> dict[str, list[dict[str, dict[str, Any]]]]:
    """Return normalized outcome facts grouped by approved map candidate.

    The consolidated replay failed aggregate recall thresholds, but its safety
    audit found zero wrong-arm links and zero unsupported exact numerics.  A
    later inventory-bound paper map supplies the arm/evidence boundary used by
    the caller to admit or reject each individual field.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    safety = payload.get("scientific_safety_audit") or {}
    if safety.get("accepted_wrong_arm_links") != 0:
        raise ValueError("pilot outcome source has accepted wrong-arm links")
    if safety.get("unsupported_exact_numeric_values") != 0:
        raise ValueError("pilot outcome source has unsupported exact numerics")
    paper = next(
        (
            row for row in payload.get("extraction", {}).get("papers", ())
            if row.get("paper_id") == paper_id
        ),
        None,
    )
    if paper is None:
        raise ValueError(f"pilot outcome source lacks {paper_id}")
    grouped: dict[str, list[dict[str, dict[str, Any]]]] = {}
    for experiment in paper.get("experiments", ()):
        candidate_id = str(experiment.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        by_outcome: dict[str, dict[str, dict[str, Any]]] = {}
        for fact in experiment.get("facts", ()):
            match = _OUTCOME_FIELD.fullmatch(str(fact.get("field_name") or ""))
            if match is None:
                continue
            by_outcome.setdefault(match.group("outcome_id"), {})[
                match.group("field_name")
            ] = fact
        grouped[candidate_id] = [
            {"_identity": {"value": outcome_id}, **fields}
            for outcome_id, fields in by_outcome.items()
        ]
    return grouped


def completed_pilot_map_response(
    approval_manifest_path: Path,
    paper_id: str,
) -> Path | None:
    """Return an exact successful response, or None when none exists.

    This is deliberately read-only and never dispatches a provider request.
    """

    manifest_path = Path(approval_manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in manifest.items() if key != "approval_hash"}
    approval_hash = str(manifest.get("approval_hash") or "")
    if _sha256(_canonical_json(unsigned).encode("utf-8")) != approval_hash:
        raise ValueError("pilot approval manifest hash is invalid")
    requests = [
        row for row in manifest.get("requests", ())
        if row.get("paper_id") == paper_id
    ]
    if len(requests) != 1:
        return None
    request = requests[0]
    signed_run_root = Path(manifest["run_root"])
    local_run_root = manifest_path.parent / "run"
    run_root = local_run_root if (local_run_root / "summary.json").is_file() else signed_run_root
    summary_path = run_root / "summary.json"
    if not summary_path.is_file():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    request_id = str(request["request_id"])
    if summary.get("approval_hash") != approval_hash:
        raise ValueError("pilot run summary approval hash changed")
    if request_id not in summary.get("succeeded_request_ids", ()):
        return None
    if request_id in summary.get("failed_request_ids", ()):
        raise ValueError("pilot request is simultaneously successful and failed")
    recorded_path = summary.get("response_artifact_paths", {}).get(request_id)
    signed_expected_path = (signed_run_root / request_id / "response.json").resolve()
    if not recorded_path or Path(recorded_path).resolve() != signed_expected_path:
        raise ValueError("pilot response path is outside its approved run slot")
    expected_path = (run_root / request_id / "response.json").resolve()
    wrapper = json.loads(expected_path.read_text(encoding="utf-8"))
    if wrapper.get("request_id") != request_id:
        raise ValueError("pilot response request ID changed")
    if wrapper.get("request_sha256") != request.get("request_sha256"):
        raise ValueError("pilot response request hash changed")
    if wrapper.get("status") != "completed":
        return None
    return expected_path


def _value(field: Any) -> Any:
    return field.get("value") if isinstance(field, dict) else None


def _evidence_ids(field: Any) -> tuple[str, ...]:
    if not isinstance(field, dict):
        return ()
    return tuple(str(item) for item in field.get("evidence_ids", ()))


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _component_role(identity: str, reported_role: str | None) -> str:
    text = f"{identity} {reported_role or ''}".casefold()
    if "cholesterol" in text:
        return "cholesterol"
    if "peg" in text and not any(
        marker in text for marker in ("targeting ligand portion", "anisamide")
    ):
        return "peg_lipid"
    if any(
        marker in text
        for marker in (
            "ionizable", "cationic aminolipid", "aminolipid", "lipidoid",
            "dlin-mc3-dma", "kl-52",
        )
    ):
        return "ionizable_lipid"
    if any(marker in text for marker in ("targeting ligand", "anisamide", "mannose")):
        return "targeting_ligand"
    if any(
        marker in text
        for marker in ("helper lipid", "phospholipid", "dspc", "dope")
    ):
        return "helper_lipid"
    return "other"


def _cell_type(value: str | None) -> str:
    text = (value or "").casefold()
    categories = []
    if "hepatocyte" in text:
        categories.append("hepatocyte")
    if "kupffer" in text:
        categories.append("kupffer_cell")
    if "lsec" in text or "liver sinusoidal endothelial" in text:
        categories.append("lsec")
    if "hsc" in text or "hepatic stellate" in text:
        categories.append("hsc")
    return categories[0] if len(set(categories)) == 1 else "other" if text else "not_reported"


def _payload_type(value: str | None) -> str | None:
    text = (value or "").casefold()
    if "sirna" in text or "small interfering" in text:
        return "siRNA"
    if "mrna" in text or "messenger rna" in text:
        return "mRNA"
    if "rna" in text:
        return "RNA"
    if "dna" in text:
        return "DNA"
    return None


def _study_scope(route: str | None, model: str | None) -> str | None:
    text = f"{route or ''} {model or ''}".casefold()
    if any(marker in text for marker in ("in vitro", "cell treatment", "cell-culture", "transfection")):
        return "in_vitro"
    if any(marker in text for marker in ("mouse", "mice", "in-vivo", "in vivo", "intravenous", "injected", "injection")):
        return "in_vivo"
    return "not_reported"


def _ratio_details(formulation: dict[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    ratios = list(formulation.get("ratios", ()))
    bases = list(formulation.get("ratio_bases", ()))
    for index, basis in enumerate(bases):
        if "molar" not in str(_value(basis) or "").casefold():
            continue
        candidates = ratios[index:index + 1] + ratios
        for ratio in candidates:
            match = _FULL_RATIO.search(str(_value(ratio) or ""))
            if match:
                evidence = _ordered_unique(
                    (*_evidence_ids(ratio), *_evidence_ids(basis))
                )
                return match.group(1), evidence
    return None, ()


def _all_ratio_text(formulation: dict[str, Any]) -> str | None:
    values = [str(_value(row)) for row in formulation.get("ratios", ()) if _value(row)]
    return "; ".join(values) or None


def _add_link(
    links: list[FieldEvidenceLink],
    *,
    paper_id: str,
    entity_type: str,
    entity_id: str,
    field_name: str,
    evidence_ids: Iterable[str],
    allowed_evidence: set[str],
) -> None:
    ids = _ordered_unique(str(value) for value in evidence_ids)
    unknown = set(ids) - allowed_evidence
    if unknown:
        raise ValueError(f"paper map cites unknown evidence IDs: {sorted(unknown)}")
    if not ids:
        raise ValueError(f"populated map field lacks evidence: {entity_id}.{field_name}")
    links.append(
        FieldEvidenceLink(
            paper_id=paper_id,
            entity_type=entity_type,  # type: ignore[arg-type]
            entity_id=entity_id,
            field_name=field_name,
            evidence_ids=ids,
            verification_status="automatically_validated",
            notes=(
                "Automatically validated against the immutable request, strict "
                "paper-map schema, and bound evidence-inventory identifiers."
            ),
        )
    )


def _map_source_facts(
    paper_id: str, paper_map: dict[str, Any]
) -> tuple[SourceFactRecord, ...]:
    facts: list[SourceFactRecord] = []

    def visit(value: Any, path: str, record_key: str, field_name: str) -> None:
        if isinstance(value, dict):
            next_key = str(
                next(
                    (
                        child
                        for name, child in value.items()
                        if name.endswith("_id") and child
                    ),
                    record_key,
                )
            )
            for name, child in value.items():
                visit(child, f"{path}.{name}", next_key, name)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]", record_key, field_name)
            return
        evidence_ids: tuple[str, ...] = ()
        facts.append(
            SourceFactRecord(
                json_path=path,
                source_record_key=record_key,
                record_kind="validated_paper_map_field",
                subject_type="paper_map_record",
                subject_key=record_key,
                field_name=field_name,
                raw_value=value,
                canonical_value=value,
                fact_identity_sha256=fact_identity(
                    paper_id,
                    "validated_paper_map_field",
                    record_key,
                    field_name,
                    value,
                ),
                import_disposition="unresolved",
                disposition_reason=(
                    "Losslessly retained; recognized canonical mappings are "
                    "recorded through import_field_evidence."
                ),
                evidence=tuple(
                    SourceFactEvidenceRecord(
                        source_evidence_key=evidence_id,
                        resolution_status="unresolved",
                        resolution_reason="Evidence identity is resolved during canonical bundle import.",
                    )
                    for evidence_id in evidence_ids
                ),
            )
        )

    visit(paper_map, "$.paper_map", paper_id, "paper_map")
    return tuple(facts)


def build_pilot_map_lossless_result(
    *,
    response_path: Path,
    base_bundle: ImportBundle,
    consolidated_path: Path | None = None,
) -> LosslessAdapterResult:
    """Validate and conservatively project one completed PILOT paper map."""

    response_path = Path(response_path).resolve()
    paper_map_model, inventory, *_ = _map_artifact_inputs(response_path)
    paper_map = paper_map_model.model_dump(mode="json")
    paper_id = paper_map_model.paper_id
    if base_bundle.paper.source_paper_id != paper_id:
        raise ValueError("paper-map and base-bundle paper IDs differ")
    if inventory.paper_id != paper_id:
        raise ValueError("paper-map inventory belongs to another paper")

    wrapper = json.loads(response_path.read_text(encoding="utf-8"))
    if wrapper.get("status") != "completed":
        raise ValueError("paper-map response is not completed")
    response_sha = hashlib.sha256(response_path.read_bytes()).hexdigest()
    logical_response_path = pilot_map_logical_path(response_path)
    request_sha = str(wrapper.get("request_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", request_sha):
        raise ValueError("completed paper-map response lacks its request hash")
    map_artifact_id = f"{paper_id}:completed-map:{request_sha[:16]}"
    map_artifact = SourceArtifactRecord(
        artifact_id=map_artifact_id,
        path=logical_response_path,
        sha256=response_sha,
        source_kind="validated_extraction",
        pipeline_name="application_pilot_completed_map",
        pipeline_version="full-paper-map-1.0.0",
        extraction_run_identifier=request_sha,
    )
    ledger_artifact = LedgerArtifactRecord(
        paper_id=paper_id,
        logical_path=logical_response_path,
        sha256=response_sha,
        role="completed_extraction",
        schema_family="full_paper_map",
        validation_status="schema_and_inventory_binding_valid",
        contributes_facts=True,
        contributes_evidence=True,
        pipeline_name="application_pilot_completed_map",
        pipeline_version="full-paper-map-1.0.0",
    )

    allowed_evidence = {record.record_id for record in base_bundle.evidence}
    inventory_evidence = {block.evidence_id for block in inventory.evidence_blocks}
    if allowed_evidence != inventory_evidence:
        raise ValueError("base bundle does not exactly match the bound inventory")

    outcome_groups: dict[str, list[dict[str, dict[str, Any]]]] = {}
    outcome_artifact: SourceArtifactRecord | None = None
    if consolidated_path is not None:
        consolidated_path = Path(consolidated_path).resolve()
        outcome_groups = _consolidated_outcome_groups(consolidated_path, paper_id)
        outcome_artifact = SourceArtifactRecord(
            artifact_id=f"{paper_id}:evidence-bound-outcomes",
            path=_repository_logical_path(consolidated_path),
            sha256=hashlib.sha256(consolidated_path.read_bytes()).hexdigest(),
            source_kind="validated_extraction",
            pipeline_name="application_pilot_evidence_bound_outcome_projection",
            pipeline_version="v1",
        )

    links: list[FieldEvidenceLink] = []
    formulations: list[FormulationRecord] = []
    components: list[ComponentRecord] = []
    formulation_ids: dict[str, str] = {}

    for raw_formulation in paper_map["formulations"]:
        raw_formulation_id = str(raw_formulation["formulation_id"])
        formulation_id = f"{paper_id}::map-formulation::{raw_formulation_id}"
        formulation_ids[raw_formulation_id] = formulation_id
        component_rows: list[tuple[dict[str, Any], str, str]] = []
        for raw_component in raw_formulation.get("components", ()):
            identity = str(_value(raw_component.get("identity")) or "").strip()
            if not identity:
                raise ValueError("paper-map component identity is empty")
            role_value = _value(raw_component.get("role"))
            role = _component_role(identity, str(role_value) if role_value else None)
            component_rows.append((raw_component, identity, role))

        core_rows = [
            row for row in component_rows
            if row[2] in {"ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid"}
        ]
        chemical_total = "-".join(row[1] for row in core_rows) or None
        molar_ratio, molar_evidence = _ratio_details(raw_formulation)
        ratio_values = molar_ratio.split(":") if molar_ratio else []
        core_amounts = (
            {id(row[0]): ratio_values[index] for index, row in enumerate(core_rows)}
            if len(ratio_values) == len(core_rows)
            else {}
        )
        name = _value(raw_formulation.get("name"))
        formulation_evidence = _evidence_ids(raw_formulation.get("name"))
        formulation = FormulationRecord(
            record_id=formulation_id,
            paper_id=paper_id,
            artifact_id=map_artifact_id,
            formulation_name=str(name) if name else None,
            chemical_formulation_total=chemical_total,
            lnp_molar_ratio=molar_ratio,
            composition_raw=_all_ratio_text(raw_formulation),
            composition_basis=(
                "molar_ratio"
                if molar_ratio
                else "other"
                if _all_ratio_text(raw_formulation)
                else None
            ),
            formulation_notes="; ".join(
                str(_value(row))
                for row in raw_formulation.get("ratio_bases", ())
                if _value(row)
            ) or None,
            formulation_review_status="unreviewed",
        )
        formulations.append(formulation)
        if formulation.formulation_name:
            _add_link(
                links, paper_id=paper_id, entity_type="formulation",
                entity_id=formulation_id, field_name="formulation_name",
                evidence_ids=formulation_evidence, allowed_evidence=allowed_evidence,
            )
        component_evidence = _ordered_unique(
            evidence_id
            for row, _, _ in component_rows
            for evidence_id in _evidence_ids(row.get("identity"))
        )
        if chemical_total:
            _add_link(
                links, paper_id=paper_id, entity_type="formulation",
                entity_id=formulation_id, field_name="chemical_formulation_total",
                evidence_ids=component_evidence, allowed_evidence=allowed_evidence,
            )
        ratio_evidence = _ordered_unique(
            evidence_id
            for collection in ("ratios", "ratio_bases")
            for row in raw_formulation.get(collection, ())
            for evidence_id in _evidence_ids(row)
        )
        if formulation.composition_raw:
            _add_link(
                links, paper_id=paper_id, entity_type="formulation",
                entity_id=formulation_id, field_name="composition_raw",
                evidence_ids=ratio_evidence, allowed_evidence=allowed_evidence,
            )
        if formulation.composition_basis:
            _add_link(
                links, paper_id=paper_id, entity_type="formulation",
                entity_id=formulation_id, field_name="composition_basis",
                evidence_ids=molar_evidence or ratio_evidence,
                allowed_evidence=allowed_evidence,
            )
        if formulation.lnp_molar_ratio:
            _add_link(
                links, paper_id=paper_id, entity_type="formulation",
                entity_id=formulation_id, field_name="lnp_molar_ratio",
                evidence_ids=molar_evidence, allowed_evidence=allowed_evidence,
            )

        for position, (raw_component, identity, role) in enumerate(component_rows, start=1):
            raw_component_id = str(raw_component["component_id"])
            component_id = f"{paper_id}::map-component::{raw_formulation_id}::{raw_component_id}"
            identity_evidence = _evidence_ids(raw_component.get("identity"))
            role_evidence = _evidence_ids(raw_component.get("role")) or identity_evidence
            amount_raw = core_amounts.get(id(raw_component))
            amount_evidence = molar_evidence if amount_raw is not None else ()
            components.append(
                ComponentRecord(
                    record_id=component_id,
                    paper_id=paper_id,
                    artifact_id=map_artifact_id,
                    formulation_id=formulation_id,
                    component_name_reported=identity,
                    component_name_normalized=identity,
                    component_role=role,
                    component_review_status="unreviewed",
                    identity_source="completed inventory-bound paper map",
                    amount_value=float(amount_raw) if amount_raw is not None else None,
                    amount_unit="mol%" if amount_raw is not None else None,
                    amount_raw=amount_raw,
                    molar_percentage=float(amount_raw) if amount_raw is not None else None,
                    percentage_unit="mol%" if amount_raw is not None else None,
                    composition_position=position,
                )
            )
            for field_name in ("component_name_reported", "component_name_normalized"):
                _add_link(
                    links, paper_id=paper_id, entity_type="component",
                    entity_id=component_id, field_name=field_name,
                    evidence_ids=identity_evidence, allowed_evidence=allowed_evidence,
                )
            _add_link(
                links, paper_id=paper_id, entity_type="component",
                entity_id=component_id, field_name="component_role",
                evidence_ids=role_evidence, allowed_evidence=allowed_evidence,
            )
            if amount_raw is not None:
                for field_name in (
                    "molar_percentage", "percentage_unit", "amount_value",
                    "amount_unit", "amount_raw",
                ):
                    _add_link(
                        links, paper_id=paper_id, entity_type="component",
                        entity_id=component_id, field_name=field_name,
                        evidence_ids=amount_evidence, allowed_evidence=allowed_evidence,
                    )

    payloads = {str(row["payload_id"]): row for row in paper_map["payloads"]}
    arms: list[ArmRecord] = []
    outcomes: list[OutcomeRecord] = []
    reviews: list[ReviewRecord] = []
    for raw_context in paper_map["provisional_experiment_contexts"]:
        raw_context_id = str(raw_context["provisional_context_id"])
        formulation_id = formulation_ids[str(raw_context["formulation_id"])]
        payload = payloads[str(raw_context["payload_id"])]
        payload_name = str(_value(payload.get("identity")) or "").strip() or None
        recipient = str(_value(raw_context.get("recipient_cell")) or "").strip() or None
        route = str(_value(raw_context.get("route")) or "").strip() or None
        model = str(_value(raw_context.get("experimental_model")) or "").strip() or None
        arm_id = f"{paper_id}::map-arm::{raw_context_id}"
        context_evidence = set(raw_context.get("joint_evidence_ids", ())) | set(
            raw_context.get("outcome_evidence_ids", ())
        )
        projected_outcomes: list[tuple[OutcomeRecord, dict[str, dict[str, Any]]]] = []
        for fields in outcome_groups.get(raw_context_id, ()):
            supported = {
                name: fact
                for name, fact in fields.items()
                if name == "_identity"
                or (
                    _evidence_ids(fact)
                    and set(_evidence_ids(fact)).issubset(context_evidence)
                )
            }
            endpoint_fact = supported.get("endpoint")
            qualitative_fact = supported.get("qualitative_outcome")
            numeric_fact = supported.get("outcome_value")
            if endpoint_fact is None or (
                qualitative_fact is None and numeric_fact is None
            ):
                continue
            raw_numeric = _reported_fact_value(numeric_fact) if numeric_fact else None
            try:
                numeric_value = float(raw_numeric) if raw_numeric is not None else None
            except (TypeError, ValueError):
                numeric_value = None
            qualitative = (
                str(_reported_fact_value(qualitative_fact))
                if qualitative_fact is not None else None
            )
            outcome_identity = str(supported["_identity"]["value"])
            notes = []
            for label, name in (("Assay", "assay"), ("Comparator", "comparator")):
                if name in supported:
                    notes.append(f"{label}: {_reported_fact_value(supported[name])}")
            projected_outcomes.append((OutcomeRecord(
                record_id=f"{paper_id}::map-outcome::{raw_context_id}::{outcome_identity}",
                paper_id=paper_id,
                artifact_id=(
                    outcome_artifact.artifact_id if outcome_artifact else map_artifact_id
                ),
                arm_id=arm_id,
                endpoint_family="other",
                endpoint_name=str(_reported_fact_value(endpoint_fact)),
                value_status=(
                    "reported" if numeric_value is not None
                    else "qualitative_only" if qualitative else "missing"
                ),
                outcome_value=numeric_value,
                outcome_unit=(
                    str(_reported_fact_value(supported["outcome_unit"]))
                    if "outcome_unit" in supported else None
                ),
                qualitative_outcome=qualitative,
                outcome_notes="; ".join(notes) or None,
            ), supported))
        assay_values = _ordered_unique(
            str(_reported_fact_value(fields["assay"]))
            for _, fields in projected_outcomes if "assay" in fields
        )
        comparator_values = _ordered_unique(
            str(_reported_fact_value(fields["comparator"]))
            for _, fields in projected_outcomes if "comparator" in fields
        )
        study_scope = _study_scope(route, model)
        arm = ArmRecord(
            record_id=arm_id,
            paper_id=paper_id,
            artifact_id=map_artifact_id,
            formulation_id=formulation_id,
            cell_type=_cell_type(recipient),
            cell_source=recipient,
            tissue_or_organ=_value(raw_context.get("organ")),
            intended_target_cell=recipient if study_scope == "in_vitro" else None,
            target_or_recipient_organ=_value(raw_context.get("organ")),
            observed_transfected_cell=recipient,
            species=_value(raw_context.get("species")),
            disease_model=model,
            in_vitro_in_vivo=study_scope,
            payload_type=_payload_type(payload_name),
            payload_name=payload_name,
            payload_molecular_target=_value(payload.get("role")),
            dose=_value(raw_context.get("dose")),
            dose_unit=_value(raw_context.get("dose_unit")),
            route=route,
            timepoint=_value(raw_context.get("timepoint")),
            timepoint_unit=_value(raw_context.get("timepoint_unit")),
            assay="; ".join(assay_values) or None,
            comparator_description="; ".join(comparator_values) or None,
            experiment_notes=(
                "Provisional context from a completed, schema-valid paper map. "
                "Outcome evidence remains unnormalized: "
                + ", ".join(raw_context.get("outcome_evidence_ids", ()))
            ),
            completeness_status="incomplete",
            verification_status="automatically_validated",
            nearest_neighbor_eligible=False,
            comet_eligible=False,
        )
        arms.append(arm)

        def link_arm(field_name: str, evidence_ids: Iterable[str]) -> None:
            _add_link(
                links, paper_id=paper_id, entity_type="arm", entity_id=arm_id,
                field_name=field_name, evidence_ids=evidence_ids,
                allowed_evidence=allowed_evidence,
            )

        recipient_evidence = _evidence_ids(raw_context.get("recipient_cell"))
        if arm.cell_type != "not_reported":
            link_arm("cell_type", recipient_evidence)
        if arm.cell_source:
            link_arm("cell_source", recipient_evidence)
        mappings = (
            ("tissue_or_organ", "organ"),
            ("intended_target_cell", "recipient_cell"),
            ("target_or_recipient_organ", "organ"),
            ("observed_transfected_cell", "recipient_cell"),
            ("species", "species"),
            ("disease_model", "experimental_model"), ("dose", "dose"),
            ("dose_unit", "dose_unit"), ("route", "route"),
            ("timepoint", "timepoint"), ("timepoint_unit", "timepoint_unit"),
        )
        for destination, source in mappings:
            if getattr(arm, destination) is not None:
                link_arm(destination, _evidence_ids(raw_context.get(source)))
        scope_evidence = _ordered_unique(
            (*_evidence_ids(raw_context.get("route")),
             *_evidence_ids(raw_context.get("experimental_model")),
             *raw_context.get("joint_evidence_ids", ()))
        )
        if arm.in_vitro_in_vivo:
            link_arm("in_vitro_in_vivo", scope_evidence)
        payload_evidence = _evidence_ids(payload.get("identity"))
        if arm.payload_name:
            link_arm("payload_name", payload_evidence)
        if arm.payload_type:
            link_arm("payload_type", payload_evidence)
        if arm.payload_molecular_target:
            link_arm(
                "payload_molecular_target",
                _evidence_ids(payload.get("role")) or payload_evidence,
            )
        if arm.assay:
            link_arm(
                "assay",
                _ordered_unique(
                    evidence_id
                    for _, fields in projected_outcomes
                    if "assay" in fields
                    for evidence_id in _evidence_ids(fields["assay"])
                ),
            )
        if arm.comparator_description:
            link_arm(
                "comparator_description",
                _ordered_unique(
                    evidence_id
                    for _, fields in projected_outcomes
                    if "comparator" in fields
                    for evidence_id in _evidence_ids(fields["comparator"])
                ),
            )
        for outcome, fields in projected_outcomes:
            outcomes.append(outcome)
            endpoint_evidence = _evidence_ids(fields["endpoint"])
            _add_link(
                links, paper_id=paper_id, entity_type="outcome",
                entity_id=outcome.record_id, field_name="endpoint_family",
                evidence_ids=endpoint_evidence, allowed_evidence=allowed_evidence,
            )
            for destination, source in (
                ("endpoint_name", "endpoint"),
                ("outcome_value", "outcome_value"),
                ("outcome_unit", "outcome_unit"),
                ("qualitative_outcome", "qualitative_outcome"),
            ):
                if source in fields and getattr(outcome, destination) is not None:
                    _add_link(
                        links, paper_id=paper_id, entity_type="outcome",
                        entity_id=outcome.record_id, field_name=destination,
                        evidence_ids=_evidence_ids(fields[source]),
                        allowed_evidence=allowed_evidence,
                    )
        review_evidence = _ordered_unique(
            (*raw_context.get("joint_evidence_ids", ()),
             *raw_context.get("outcome_evidence_ids", ()))
        )
        if not projected_outcomes:
            reviews.append(
            ReviewRecord(
                record_id=f"{paper_id}::map-review::{raw_context_id}",
                paper_id=paper_id,
                artifact_id=map_artifact_id,
                reason_code="outcome_link_unclear",
                status="incomplete",
                # The underlying inventory evidence remains attached through
                # field links.  It is intentionally not arm-scoped until an
                # outcome record can be normalized without inventing a value.
                evidence_ids=(),
                arm_id=arm_id,
                field_name="outcome",
                notes=(
                    "The formulation/arm pairing passed automatic provenance "
                    "validation. The map supplies outcome evidence IDs but not a "
                    "normalized outcome record, so only that outcome projection "
                    "remains unresolved. Source evidence IDs: "
                    + ", ".join(review_evidence)
                ),
            ))
        else:
            reviews.append(ReviewRecord(
                record_id=f"{paper_id}::map-review::{raw_context_id}",
                paper_id=paper_id,
                artifact_id=map_artifact_id,
                reason_code="missing_required_fields",
                status="incomplete",
                evidence_ids=(),
                arm_id=arm_id,
                notes=(
                    "Evidence-bound outcomes were projected automatically. "
                    "The arm remains incomplete only for other mandatory "
                    "database fields."
                ),
            ))

    for index, unresolved in enumerate(paper_map.get("unresolved_items", ()), start=1):
        reviews.append(
            ReviewRecord(
                record_id=f"{paper_id}::map-unresolved::{index}",
                paper_id=paper_id,
                artifact_id=map_artifact_id,
                reason_code="unsupported_value",
                status="incomplete",
                notes=str(unresolved),
            )
        )

    source_facts = _map_source_facts(paper_id, paper_map)
    bundle = ImportBundle(
        paper=replace(
            base_bundle.paper,
            import_status="ready_with_missing_fields",
            screening_reason=(
                "Completed inventory-bound paper map merged; provisional arms "
                "remain review-gated and no map-only outcome was invented."
            ),
        ),
        artifacts=(
            *base_bundle.artifacts,
            map_artifact,
            *((outcome_artifact,) if outcome_artifact is not None else ()),
        ),
        formulations=tuple(formulations),
        components=tuple(components),
        arms=tuple(arms),
        outcomes=tuple(outcomes),
        evidence=base_bundle.evidence,
        field_evidence_links=tuple(links),
        reviews=tuple(reviews),
    )
    return LosslessAdapterResult(
        bundle=bundle,
        artifact=ledger_artifact,
        source_facts=source_facts,
        coverage=AdapterCoverage(
            source_entities=(
                len(paper_map["formulations"])
                + len(paper_map["payloads"])
                + len(paper_map["recipient_contexts"])
            ),
            source_experiments=len(paper_map["provisional_experiment_contexts"]),
            source_fields=len(source_facts),
            unresolved_items=len(paper_map.get("unresolved_items", ())),
            silent_omissions=0,
        ),
    )


__all__ = [
    "build_pilot_map_lossless_result",
    "completed_pilot_map_response",
    "pilot_map_logical_path",
]
