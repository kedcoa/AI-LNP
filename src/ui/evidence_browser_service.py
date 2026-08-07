"""Read-only data boundary for the paper/formulation evidence browser."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import MappingProxyType
from typing import Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.database.paths import (
    CANONICAL_AUTHORITATIVE_DATABASE,
    COMMON_CHECKOUT_ROOT,
)
from src.database.scientific_identity import (
    CompositionPart,
    composition_fingerprint,
)


FORMULATION_COLUMNS = (
    "lnp_name",
    "chemical_formulation_total",
    "lnp_molar_ratio",
    "ionizable_lipid",
    "helper_lipid",
    "cholesterol",
    "peg_lipid",
    "others",
)

ARM_FIELD_COLUMNS = (
    "target_or_recipient_organ",
    "intended_target_cell",
    "observed_transfected_cell",
    "cell_type",
    "cell_source",
    "tissue_or_organ",
    "species",
    "disease_model",
    "in_vitro_in_vivo",
    "route",
    "payload_type",
    "payload_name",
    "payload_encoded_product",
    "payload_molecular_target",
    "dose",
    "assay",
    "timepoint",
    "comparator_type",
    "comparator_description",
    "protocol_reference",
)

OUTCOME_FIELD_COLUMNS = (
    "endpoint_family",
    "endpoint_name",
    "outcome_value",
    "outcome_unit",
    "normalization_basis",
    "uncertainty_value",
    "uncertainty_type",
    "qualitative_outcome",
    "value_status",
)


@dataclass(frozen=True)
class BrowserCounts:
    formulations: int
    components: int
    arms: int
    outcomes: int
    evidence_records: int
    automatic_resolution_issues: int


@dataclass(frozen=True)
class BrowserSummary:
    unique_chemical_formulations: int
    general_use_ready_arms: int
    nearest_neighbor_ready_arms: int
    comet_ready_arms: int
    experimental_arms: int


@dataclass(frozen=True)
class BrowserEvidence:
    evidence_id: int
    text: str
    location: str
    modality: str
    confidence: str
    verification_status: str


@dataclass(frozen=True)
class BrowserField:
    name: str
    value: str | None
    evidence: tuple[BrowserEvidence, ...] = ()

    @property
    def display_value(self) -> str:
        value = (self.value or "").strip()
        return value if value else "NA"


@dataclass(frozen=True)
class BrowserIssue:
    reason_code: str
    status: str
    tag: str
    field_name: str | None
    notes: str | None
    arm_id: int | None
    outcome_id: int | None


@dataclass(frozen=True)
class BrowserOutcome:
    outcome_id: int
    fields: Mapping[str, BrowserField]


@dataclass(frozen=True)
class BrowserFilters:
    paper_ids: tuple[str, ...] = ()
    cell_types: tuple[str, ...] = ()
    general_usable: bool | None = None
    nearest_neighbor_ready: bool | None = None
    comet_ready: bool | None = None
    blocker: str | None = None


@dataclass(frozen=True)
class BrowserArmRow:
    experiment_id: int
    paper: BrowserPaper
    formulation_id: int
    formulation: Mapping[str, BrowserField]
    arm_fields: Mapping[str, BrowserField]
    outcomes: tuple[BrowserOutcome, ...]
    general_usable: bool
    nearest_neighbor_ready: bool
    comet_ready: bool
    queue_label: str
    missing_fields: tuple[str, ...]
    nearest_neighbor_blockers: tuple[str, ...]
    comet_blockers: tuple[str, ...]
    issues: tuple[BrowserIssue, ...]

    @property
    def outcomes_display(self) -> str:
        lines: list[str] = []
        for outcome in self.outcomes:
            fields = outcome.fields
            endpoint = (
                fields["endpoint_name"].value
                or fields["endpoint_family"].value
                or f"Outcome #{outcome.outcome_id}"
            )
            value = fields["outcome_value"].display_value
            if value != "NA" and fields["outcome_unit"].value:
                value = f"{value} {fields['outcome_unit'].value}"
            if value == "NA":
                value = fields["qualitative_outcome"].display_value
            qualifiers = [
                fields["normalization_basis"].value,
                fields["value_status"].value,
            ]
            suffix = " · ".join(str(item) for item in qualifiers if item)
            lines.append(f"{endpoint}: {value}" + (f" · {suffix}" if suffix else ""))
        return "\n".join(lines) if lines else "NA"


@dataclass(frozen=True)
class BrowserArm:
    experiment_id: int
    fields: Mapping[str, BrowserField]
    completeness_status: str
    verification_status: str
    missing_fields: tuple[str, ...]
    nearest_neighbor_eligible: bool
    comet_eligible: bool
    nearest_neighbor_blockers: tuple[str, ...]
    comet_blockers: tuple[str, ...]
    outcomes: tuple[BrowserOutcome, ...]
    issues: tuple[BrowserIssue, ...]


@dataclass(frozen=True)
class BrowserFormulation:
    formulation_id: int
    cells: Mapping[str, BrowserField]
    arms: tuple[BrowserArm, ...]


@dataclass(frozen=True)
class BrowserPaper:
    paper_id: int
    source_paper_id: str
    title: str
    full_text_status: str
    import_status: str
    links: Mapping[str, str]
    counts: BrowserCounts


@dataclass(frozen=True)
class PaperBrowserView:
    paper: BrowserPaper
    counts: BrowserCounts
    formulations: tuple[BrowserFormulation, ...]
    issues: tuple[BrowserIssue, ...]


def browser_database_path() -> Path:
    """Return the single authoritative database used by the live browser."""

    snapshot = os.environ.get("LNP_MENTOR_SNAPSHOT_DB", "").strip()
    if snapshot:
        path = Path(snapshot).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Mentor snapshot database is missing: {path}")
        return path
    return CANONICAL_AUTHORITATIVE_DATABASE


def _connect(database_path: Path | None = None) -> sqlite3.Connection:
    path = (database_path or browser_database_path()).resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _arm_has_usable_evidence(
    connection: sqlite3.Connection, experiment_id: int
) -> bool:
    """Recognize direct evidence and canonical field-evidence links."""

    return connection.execute(
        """
        SELECT 1
        FROM evidence
        WHERE length(trim(coalesce(evidence_text,'')))>0
          AND evidence_review_status NOT IN ('rejected','conflict','ambiguous')
          AND (
            experiment_id=?
            OR evidence_id IN (
              SELECT link.evidence_id
              FROM import_field_evidence AS link
              WHERE (link.entity_type='arm' AND link.entity_id=?)
                 OR (link.entity_type='outcome' AND link.entity_id IN (
                      SELECT outcome_id FROM outcome WHERE experiment_id=?
                 ))
            )
          )
        LIMIT 1
        """,
        (experiment_id, experiment_id, experiment_id),
    ).fetchone() is not None


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return format(value, "g")
    rendered = str(value).strip()
    return rendered or None


def _with_unit(value: object, unit: object) -> str | None:
    rendered = _text(value)
    rendered_unit = _text(unit)
    if rendered is None:
        return None
    return f"{rendered} {rendered_unit}" if rendered_unit else rendered


def _counts(connection: sqlite3.Connection, paper_id: int) -> BrowserCounts:
    row = connection.execute(
        """
        SELECT
          (SELECT count(*) FROM formulation f WHERE f.paper_id=p.paper_id),
          (SELECT count(*) FROM chemical_component c JOIN formulation f USING(formulation_id)
             WHERE f.paper_id=p.paper_id),
          (SELECT count(*) FROM experiment x WHERE x.paper_id=p.paper_id),
          (SELECT count(*) FROM outcome o JOIN experiment x USING(experiment_id)
             WHERE x.paper_id=p.paper_id),
          (SELECT count(*) FROM evidence e WHERE e.paper_id=p.paper_id),
          (SELECT count(*) FROM import_review r WHERE r.paper_id=p.paper_id
             AND r.reason_code!='missing_required_fields')
        FROM paper p WHERE p.paper_id=?
        """,
        (paper_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown paper: {paper_id}")
    return BrowserCounts(*(int(value) for value in row))


def _local_artifact_link(
    connection: sqlite3.Connection, paper_id: int
) -> str | None:
    for (logical_path,) in connection.execute(
        """
        SELECT logical_path FROM source_artifact
        WHERE paper_id=? ORDER BY
          CASE role WHEN 'full_text' THEN 0 WHEN 'supplement' THEN 1 ELSE 2 END,
          source_artifact_id
        """,
        (paper_id,),
    ):
        path = Path(str(logical_path))
        if path.suffix.casefold() not in {".pdf", ".html", ".htm", ".xml", ".nxml"}:
            continue
        candidate = path if path.is_absolute() else COMMON_CHECKOUT_ROOT / path
        if candidate.is_file():
            return candidate.resolve().as_uri()
    return None


def _paper_from_row(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> BrowserPaper:
    links: dict[str, str] = {}
    if row["doi"]:
        links["DOI / publisher"] = f"https://doi.org/{row['doi']}"
    if row["pmid"]:
        links["PubMed"] = f"https://pubmed.ncbi.nlm.nih.gov/{row['pmid']}/"
    if row["pmcid"]:
        links["PMC"] = f"https://pmc.ncbi.nlm.nih.gov/articles/{row['pmcid']}/"
    if row["source_url"]:
        links["Source record"] = str(row["source_url"])
    local = None
    if not os.environ.get("LNP_MENTOR_SNAPSHOT_DB", "").strip():
        local = _local_artifact_link(connection, int(row["paper_id"]))
    if local:
        links["Local source"] = local
    return BrowserPaper(
        paper_id=int(row["paper_id"]),
        source_paper_id=str(row["source_paper_id"] or row["paper_id"]),
        title=str(row["title"]),
        full_text_status=str(row["full_text_status"]),
        import_status=str(row["import_status"]),
        links=MappingProxyType(links),
        counts=_counts(connection, int(row["paper_id"])),
    )


def list_browser_papers() -> tuple[BrowserPaper, ...]:
    """Return every manifest paper, including screening-only dispositions."""

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT paper_id,source_paper_id,title,doi,pmid,pmcid,source_url,
                   full_text_status,import_status
            FROM paper ORDER BY coalesce(source_paper_id,printf('%09d',paper_id))
            """
        ).fetchall()
        return tuple(_paper_from_row(connection, row) for row in rows)


def default_browser_paper_id(papers: Sequence[BrowserPaper]) -> int:
    """Choose the first paper with extracted formulations for the initial view."""

    if not papers:
        raise ValueError("at least one paper is required")
    return next(
        (paper.paper_id for paper in papers if paper.counts.formulations > 0),
        papers[0].paper_id,
    )


def _location(row: sqlite3.Row) -> str:
    values = [
        row["section_name"],
        f"page {row['page_number']}" if row["page_number"] else None,
        f"table {row['table_number']}" if row["table_number"] else None,
        f"figure {row['figure_number']}" if row["figure_number"] else None,
        row["supplement_identifier"],
    ]
    return " · ".join(str(value) for value in values if value) or str(
        row["evidence_location_type"]
    )


def _evidence_for(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_ids: Sequence[int],
    field_names: Sequence[str] = (),
) -> tuple[BrowserEvidence, ...]:
    if not entity_ids:
        return ()
    entity_slots = ",".join("?" for _ in entity_ids)
    parameters: list[object] = [entity_type, *entity_ids]
    field_clause = ""
    if field_names:
        field_slots = ",".join("?" for _ in field_names)
        field_clause = f" AND link.field_name IN ({field_slots})"
        parameters.extend(field_names)
    rows = connection.execute(
        f"""
        SELECT DISTINCT evidence.evidence_id,evidence.evidence_text,
               evidence.evidence_location_type,evidence.section_name,
               evidence.page_number,evidence.table_number,evidence.figure_number,
               evidence.supplement_identifier,evidence.extraction_method,
               evidence.extraction_confidence,link.verification_status
        FROM import_field_evidence link
        JOIN evidence ON evidence.evidence_id=link.evidence_id
        WHERE link.entity_type=? AND link.entity_id IN ({entity_slots})
        {field_clause}
        ORDER BY evidence.evidence_id
        """,
        parameters,
    ).fetchall()
    return tuple(
        BrowserEvidence(
            evidence_id=int(row["evidence_id"]),
            text=str(row["evidence_text"]),
            location=_location(row),
            modality=str(row["extraction_method"]),
            confidence=str(row["extraction_confidence"]),
            verification_status=str(row["verification_status"]),
        )
        for row in rows
    )


def _issues(
    connection: sqlite3.Connection,
    paper_id: int,
    *,
    arm_id: int | None = None,
    paper_level_only: bool = False,
) -> tuple[BrowserIssue, ...]:
    conditions = ["paper_id=?", "reason_code!='missing_required_fields'"]
    parameters: list[object] = [paper_id]
    if arm_id is not None:
        conditions.append("arm_id=?")
        parameters.append(arm_id)
    elif paper_level_only:
        conditions.append("arm_id IS NULL")
    rows = connection.execute(
        """
        SELECT reason_code,review_status,review_tag,field_name,notes,arm_id,outcome_id
        FROM import_review WHERE """
        + " AND ".join(conditions)
        + " ORDER BY import_review_id",
        parameters,
    ).fetchall()
    return tuple(
        BrowserIssue(
            reason_code=str(row["reason_code"]),
            status=str(row["review_status"]),
            tag=str(row["review_tag"]),
            field_name=_text(row["field_name"]),
            notes=_text(row["notes"]),
            arm_id=int(row["arm_id"]) if row["arm_id"] is not None else None,
            outcome_id=int(row["outcome_id"]) if row["outcome_id"] is not None else None,
        )
        for row in rows
    )


def _eligibility(
    connection: sqlite3.Connection, experiment_id: int, profile: str
) -> tuple[bool, tuple[str, ...]]:
    row = connection.execute(
        """
        SELECT eligible,reasons_json FROM eligibility_result
        WHERE experiment_id=? AND profile=?
        """,
        (experiment_id, profile),
    ).fetchone()
    if row is None:
        return False, ("not_evaluated",)
    reasons = json.loads(row["reasons_json"])
    return bool(row["eligible"]), tuple(
        str(reason) for reason in reasons if isinstance(reason, str)
    )


def _outcomes(
    connection: sqlite3.Connection, experiment_id: int
) -> tuple[BrowserOutcome, ...]:
    rows = connection.execute(
        "SELECT * FROM outcome WHERE experiment_id=? ORDER BY outcome_id",
        (experiment_id,),
    ).fetchall()
    results: list[BrowserOutcome] = []
    for row in rows:
        outcome_id = int(row["outcome_id"])
        fields = {
            name: BrowserField(
                name,
                _text(row[name]),
                _evidence_for(connection, "outcome", (outcome_id,), (name,)),
            )
            for name in OUTCOME_FIELD_COLUMNS
        }
        results.append(BrowserOutcome(outcome_id, MappingProxyType(fields)))
    return tuple(results)


def _arms(
    connection: sqlite3.Connection, paper_id: int, formulation_id: int
) -> tuple[BrowserArm, ...]:
    rows = connection.execute(
        """
        SELECT experiment.*,assessment.completeness_status,
               assessment.verification_status,assessment.missing_fields_json
        FROM experiment
        LEFT JOIN arm_assessment assessment USING(experiment_id)
        WHERE experiment.paper_id=? AND experiment.formulation_id=?
        ORDER BY experiment.experiment_id
        """,
        (paper_id, formulation_id),
    ).fetchall()
    results: list[BrowserArm] = []
    for row in rows:
        experiment_id = int(row["experiment_id"])
        values = {name: _text(row[name]) for name in ARM_FIELD_COLUMNS}
        values["dose"] = _with_unit(row["dose"], row["dose_unit"])
        values["timepoint"] = _with_unit(row["timepoint"], row["timepoint_unit"])
        fields = {
            name: BrowserField(
                name,
                values[name],
                _evidence_for(
                    connection,
                    "arm",
                    (experiment_id,),
                    (name, f"{name}_unit") if name in {"dose", "timepoint"} else (name,),
                ),
            )
            for name in ARM_FIELD_COLUMNS
        }
        nearest, nearest_reasons = _eligibility(
            connection, experiment_id, "nearest_neighbor"
        )
        comet, comet_reasons = _eligibility(connection, experiment_id, "comet")
        missing = json.loads(row["missing_fields_json"] or "[]")
        results.append(
            BrowserArm(
                experiment_id=experiment_id,
                fields=MappingProxyType(fields),
                completeness_status=str(row["completeness_status"] or "incomplete"),
                verification_status=str(row["verification_status"] or "unreviewed"),
                missing_fields=tuple(str(value) for value in missing),
                nearest_neighbor_eligible=nearest,
                comet_eligible=comet,
                nearest_neighbor_blockers=nearest_reasons,
                comet_blockers=comet_reasons,
                outcomes=_outcomes(connection, experiment_id),
                issues=_issues(connection, paper_id, arm_id=experiment_id),
            )
        )
    return tuple(results)


def _formulations(
    connection: sqlite3.Connection, paper_id: int
) -> tuple[BrowserFormulation, ...]:
    rows = connection.execute(
        "SELECT * FROM formulation WHERE paper_id=? ORDER BY formulation_id",
        (paper_id,),
    ).fetchall()
    results: list[BrowserFormulation] = []
    core_roles = {"ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid"}
    for row in rows:
        formulation_id = int(row["formulation_id"])
        components = connection.execute(
            """
            SELECT component_id,component_role,
                   coalesce(component_name_normalized,component_name_reported) AS name
            FROM chemical_component WHERE formulation_id=?
            ORDER BY coalesce(composition_position,component_id),component_id
            """,
            (formulation_id,),
        ).fetchall()
        by_role: dict[str, list[sqlite3.Row]] = {}
        for component in components:
            by_role.setdefault(str(component["component_role"]), []).append(component)

        def component_cell(name: str, roles: set[str]) -> BrowserField:
            selected = [
                component for component in components
                if str(component["component_role"]) in roles
            ]
            value = "; ".join(str(component["name"]) for component in selected) or None
            return BrowserField(
                name,
                value,
                _evidence_for(
                    connection,
                    "component",
                    tuple(int(component["component_id"]) for component in selected),
                ),
            )

        cells: dict[str, BrowserField] = {
            "lnp_name": BrowserField(
                "lnp_name", _text(row["formulation_name"]),
                _evidence_for(
                    connection, "formulation", (formulation_id,),
                    ("formulation_name",),
                ),
            ),
            "chemical_formulation_total": BrowserField(
                "chemical_formulation_total", _text(row["chemical_formulation_total"]),
                _evidence_for(
                    connection, "formulation", (formulation_id,),
                    ("chemical_formulation_total", "composition_raw"),
                ),
            ),
            "lnp_molar_ratio": BrowserField(
                "lnp_molar_ratio", _text(row["lnp_molar_ratio"]),
                _evidence_for(
                    connection, "formulation", (formulation_id,),
                    ("lnp_molar_ratio", "composition_raw"),
                ),
            ),
        }
        for role in ("ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid"):
            cells[role] = component_cell(role, {role})
        cells["others"] = component_cell(
            "others", {str(component["component_role"]) for component in components} - core_roles
        )
        ordered = {column: cells[column] for column in FORMULATION_COLUMNS}
        results.append(
            BrowserFormulation(
                formulation_id=formulation_id,
                cells=MappingProxyType(ordered),
                arms=_arms(connection, paper_id, formulation_id),
            )
        )
    return tuple(results)


def load_paper_browser(paper_id: int) -> PaperBrowserView:
    """Load one complete read-only paper view by canonical integer ID."""

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT paper_id,source_paper_id,title,doi,pmid,pmcid,source_url,
                   full_text_status,import_status
            FROM paper WHERE paper_id=?
            """,
            (paper_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown paper: {paper_id}")
        paper = _paper_from_row(connection, row)
        return PaperBrowserView(
            paper=paper,
            counts=paper.counts,
            formulations=_formulations(connection, paper_id),
            issues=_issues(connection, paper_id, paper_level_only=True),
        )


def list_combined_arm_rows(
    filters: BrowserFilters | None = None,
    *,
    database_path: Path | None = None,
) -> tuple[BrowserArmRow, ...]:
    """Return exactly one display row per canonical experimental arm."""

    selected = filters or BrowserFilters()
    results: list[BrowserArmRow] = []
    with _connect(database_path) as connection:
        paper_rows = connection.execute(
            """
            SELECT paper_id,source_paper_id,title,doi,pmid,pmcid,source_url,
                   full_text_status,import_status
            FROM paper WHERE import_status!='screening_only'
            ORDER BY source_paper_id,paper_id
            """
        ).fetchall()
        for paper_row in paper_rows:
            paper = _paper_from_row(connection, paper_row)
            if selected.paper_ids and paper.source_paper_id not in selected.paper_ids:
                continue
            for formulation in _formulations(connection, paper.paper_id):
                for arm in formulation.arms:
                    has_evidence = _arm_has_usable_evidence(
                        connection, arm.experiment_id
                    )
                    general = (
                        arm.completeness_status == "complete"
                        and has_evidence
                    )
                    queue = (
                        "conflict" if arm.completeness_status == "conflict"
                        else "quarantined" if arm.completeness_status == "quarantined"
                        else "comet_ready" if arm.comet_eligible
                        else "almost_comet_ready" if general and len(arm.comet_blockers) <= 3
                        else "comet_gap"
                    )
                    cell_type = arm.fields["cell_type"].value or ""
                    all_blockers = set(arm.nearest_neighbor_blockers) | set(
                        arm.comet_blockers
                    )
                    if selected.cell_types and cell_type not in selected.cell_types:
                        continue
                    if selected.general_usable is not None and general != selected.general_usable:
                        continue
                    if (selected.nearest_neighbor_ready is not None and
                            arm.nearest_neighbor_eligible != selected.nearest_neighbor_ready):
                        continue
                    if selected.comet_ready is not None and arm.comet_eligible != selected.comet_ready:
                        continue
                    if selected.blocker and selected.blocker not in all_blockers:
                        continue
                    results.append(BrowserArmRow(
                        experiment_id=arm.experiment_id,
                        paper=paper,
                        formulation_id=formulation.formulation_id,
                        formulation=formulation.cells,
                        arm_fields=arm.fields,
                        outcomes=arm.outcomes,
                        general_usable=general,
                        nearest_neighbor_ready=arm.nearest_neighbor_eligible,
                        comet_ready=arm.comet_eligible,
                        queue_label=queue,
                        missing_fields=arm.missing_fields,
                        nearest_neighbor_blockers=arm.nearest_neighbor_blockers,
                        comet_blockers=arm.comet_blockers,
                        issues=arm.issues,
                    ))
    return tuple(results)


def summarize_browser_database(
    database_path: Path | None = None,
) -> BrowserSummary:
    """Return headline counts from the same canonical rows shown in the UI."""

    rows = list_combined_arm_rows(database_path=database_path)
    fingerprints: set[str] = set()
    with _connect(database_path) as connection:
        formulation_ids = connection.execute(
            "SELECT formulation_id FROM formulation ORDER BY formulation_id"
        ).fetchall()
        for (formulation_id,) in formulation_ids:
            components = connection.execute(
                """
                SELECT component_role,
                       coalesce(component_name_normalized,
                                component_name_reported),
                       coalesce(amount_value,molar_percentage),
                       coalesce(amount_unit,percentage_unit)
                FROM chemical_component
                WHERE formulation_id=?
                ORDER BY component_id
                """,
                (formulation_id,),
            ).fetchall()
            fingerprint = composition_fingerprint(
                CompositionPart(role, name, amount, unit)
                for role, name, amount, unit in components
            )
            if fingerprint:
                fingerprints.add(fingerprint)
    return BrowserSummary(
        unique_chemical_formulations=len(fingerprints),
        general_use_ready_arms=sum(row.general_usable for row in rows),
        nearest_neighbor_ready_arms=sum(
            row.nearest_neighbor_ready for row in rows
        ),
        comet_ready_arms=sum(row.comet_ready for row in rows),
        experimental_arms=len(rows),
    )


def combined_arm_rows_for_export(
    rows: Sequence[BrowserArmRow],
    *,
    include_local_links: bool = True,
) -> list[dict[str, str]]:
    """Serialize combined arm rows without importing Streamlit."""

    formulation_labels = {
        "lnp_name": "LNP name",
        "chemical_formulation_total": "Chemical formulation (total)",
        "lnp_molar_ratio": "LNP molar ratio",
        "ionizable_lipid": "Ionizable lipid",
        "helper_lipid": "Helper lipid",
        "cholesterol": "Cholesterol",
        "peg_lipid": "PEG lipid",
        "others": "Others",
    }
    rendered: list[dict[str, str]] = []
    for row in rows:
        links = [
            value for value in row.paper.links.values()
            if include_local_links or not value.startswith("file://")
        ]
        values = {
            "Paper": row.paper.source_paper_id,
            "Paper title": row.paper.title,
            "DOI / paper link": next(iter(links), "NA"),
            "Arm ID": str(row.experiment_id),
        }
        values.update({
            formulation_labels[column]: row.formulation[column].display_value
            for column in FORMULATION_COLUMNS
        })
        values.update({
            "Target / recipient organ": row.arm_fields[
                "target_or_recipient_organ"
            ].display_value,
            "Intended target cell": row.arm_fields[
                "intended_target_cell"
            ].display_value,
            "Observed transfected cell": row.arm_fields[
                "observed_transfected_cell"
            ].display_value,
            "Legacy cell label": row.arm_fields["cell_type"].display_value,
            "Species": row.arm_fields["species"].display_value,
            "Biological model": row.arm_fields["disease_model"].display_value,
            "Payload": row.arm_fields["payload_name"].display_value,
            "Encoded product": row.arm_fields[
                "payload_encoded_product"
            ].display_value,
            "Molecular target": row.arm_fields[
                "payload_molecular_target"
            ].display_value,
            "Dose": row.arm_fields["dose"].display_value,
            "Route": row.arm_fields["route"].display_value,
            "Timepoint": row.arm_fields["timepoint"].display_value,
            "Assay": row.arm_fields["assay"].display_value,
            "Outcomes": row.outcomes_display,
            "General use": "Ready" if row.general_usable else "Not ready",
            "Nearest neighbor": (
                "Ready" if row.nearest_neighbor_ready else "Not ready"
            ),
            "COMET": "Ready" if row.comet_ready else "Not ready",
            "COMET blockers": ", ".join(row.comet_blockers) or "None",
            "Missing fields": ", ".join(row.missing_fields) or "None",
            "Automatic-resolution issues": ", ".join(
                issue.reason_code for issue in row.issues
            ) or "None",
        })
        rendered.append(values)
    return rendered


__all__ = [
    "ARM_FIELD_COLUMNS",
    "FORMULATION_COLUMNS",
    "OUTCOME_FIELD_COLUMNS",
    "BrowserArm",
    "BrowserArmRow",
    "BrowserFilters",
    "BrowserCounts",
    "BrowserSummary",
    "BrowserEvidence",
    "BrowserField",
    "BrowserFormulation",
    "BrowserIssue",
    "BrowserOutcome",
    "BrowserPaper",
    "PaperBrowserView",
    "browser_database_path",
    "combined_arm_rows_for_export",
    "default_browser_paper_id",
    "list_browser_papers",
    "list_combined_arm_rows",
    "load_paper_browser",
    "summarize_browser_database",
]
