"""Read-only data boundary for the paper/formulation evidence browser."""

from __future__ import annotations

from dataclasses import dataclass
import json
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

    return CANONICAL_AUTHORITATIVE_DATABASE


def _connect() -> sqlite3.Connection:
    path = browser_database_path().resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


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
          (SELECT count(*) FROM import_review r WHERE r.paper_id=p.paper_id)
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
    conditions = ["paper_id=?"]
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


__all__ = [
    "ARM_FIELD_COLUMNS",
    "FORMULATION_COLUMNS",
    "OUTCOME_FIELD_COLUMNS",
    "BrowserArm",
    "BrowserCounts",
    "BrowserEvidence",
    "BrowserField",
    "BrowserFormulation",
    "BrowserIssue",
    "BrowserOutcome",
    "BrowserPaper",
    "PaperBrowserView",
    "browser_database_path",
    "default_browser_paper_id",
    "list_browser_papers",
    "load_paper_browser",
]
