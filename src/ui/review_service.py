"""Read-only SQLite boundary for the human evidence-review workspace."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from src.database.audit_current_database import CANONICAL_AUTHORITATIVE_DATABASE
from src.database.status import RULES_VERSION


@dataclass(frozen=True)
class DashboardMetrics:
    nearest_neighbor_ready_arms: int
    comet_ready_arms: int
    automatically_validated_usable_facts: int
    manually_verified_usable_facts: int
    usable_field_facts: int


@dataclass(frozen=True)
class PaperRowCounts:
    formulations: int
    chemical_components: int
    experimental_arms: int
    outcomes: int
    evidence_excerpts: int
    usable_field_facts: int
    open_review_items: int
    review_history_revisions: int


@dataclass(frozen=True)
class PaperSummary:
    paper_id: int
    source_paper_id: str | None
    title: str
    doi: str | None
    pmid: str | None
    pmcid: str | None
    source_url: str | None
    full_text_status: str
    row_counts: PaperRowCounts


@dataclass(frozen=True)
class ReviewArm:
    experiment_id: int
    paper_id: int
    source_paper_id: str | None
    paper_title: str
    formulation: str
    target_cell: str
    species: str
    payload: str
    review_reason: str | None
    review_status: str | None
    review_reason_code: str | None
    completeness_status: str
    verification_status: str
    missing_fields: tuple[str, ...]
    comet_blockers: tuple[str, ...]
    nearest_neighbor_eligible: bool
    comet_eligible: bool


@dataclass(frozen=True)
class WorkspaceField:
    name: str
    label: str
    value: str
    is_blank: bool


@dataclass(frozen=True)
class EvidenceExcerpt:
    evidence_id: int
    field_name: str
    text: str
    location_type: str
    location: str
    modality: str
    confidence: str
    verification_status: str


@dataclass(frozen=True)
class ReviewHistory:
    review_revision_id: int
    field_name: str
    previous_value: str | None
    corrected_value: str
    decision: str
    reviewer: str
    reviewer_notes: str | None
    reviewed_at: str


@dataclass(frozen=True)
class ArmWorkspace:
    arm: ReviewArm
    paper: PaperSummary
    fields: tuple[WorkspaceField, ...]
    evidence: tuple[EvidenceExcerpt, ...]
    history: tuple[ReviewHistory, ...]


def authoritative_database_path() -> Path:
    """Return the one shared database path; callers cannot override it."""

    return CANONICAL_AUTHORITATIVE_DATABASE


def _connect() -> sqlite3.Connection:
    path = authoritative_database_path()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _latest_eligibility_condition(profile: str) -> str:
    return """
        eligibility.profile = ?
        AND eligibility.rules_version = ?
        AND NOT EXISTS (
            SELECT 1 FROM eligibility_result AS later
            WHERE later.experiment_id = eligibility.experiment_id
              AND later.profile = eligibility.profile
              AND later.rules_version = eligibility.rules_version
              AND (later.evaluated_at > eligibility.evaluated_at
                   OR (later.evaluated_at = eligibility.evaluated_at
                       AND later.rowid > eligibility.rowid))
        )
    """


_VALID_FACTS_CTE = """
WITH canonical_fact AS (
    SELECT field_link.*
    FROM import_field_evidence AS field_link
    JOIN evidence AS evidence ON evidence.evidence_id = field_link.evidence_id
                           AND evidence.paper_id = field_link.paper_id
    WHERE field_link.verification_status IN ('automatically_validated', 'manually_verified')
      AND (
          (field_link.entity_type = 'formulation' AND EXISTS (
              SELECT 1 FROM formulation AS target
              WHERE target.formulation_id = field_link.entity_id
                AND target.paper_id = field_link.paper_id
          )) OR
          (field_link.entity_type = 'component' AND EXISTS (
              SELECT 1 FROM chemical_component AS target
              JOIN formulation AS formulation ON formulation.formulation_id = target.formulation_id
              WHERE target.component_id = field_link.entity_id
                AND formulation.paper_id = field_link.paper_id
          )) OR
          (field_link.entity_type = 'arm' AND EXISTS (
              SELECT 1 FROM experiment AS target
              WHERE target.experiment_id = field_link.entity_id
                AND target.paper_id = field_link.paper_id
          )) OR
          (field_link.entity_type = 'outcome' AND EXISTS (
              SELECT 1 FROM outcome AS target
              JOIN experiment AS experiment ON experiment.experiment_id = target.experiment_id
              WHERE target.outcome_id = field_link.entity_id
                AND experiment.paper_id = field_link.paper_id
          ))
      )
      AND NOT EXISTS (
          SELECT 1 FROM import_field_evidence AS later
          WHERE later.paper_id = field_link.paper_id
            AND later.entity_type = field_link.entity_type
            AND later.entity_id = field_link.entity_id
            AND later.field_name = field_link.field_name
            AND later.evidence_id = field_link.evidence_id
            AND later.import_field_evidence_id > field_link.import_field_evidence_id
      )
)
"""


def load_dashboard() -> DashboardMetrics:
    with _connect() as connection:
        nearest = connection.execute(
            f"SELECT count(DISTINCT experiment_id) FROM eligibility_result AS eligibility WHERE {_latest_eligibility_condition('nearest_neighbor')} AND eligible = 1",
            ('nearest_neighbor', RULES_VERSION),
        ).fetchone()[0]
        comet = connection.execute(
            f"SELECT count(DISTINCT experiment_id) FROM eligibility_result AS eligibility WHERE {_latest_eligibility_condition('comet')} AND eligible = 1",
            ('comet', RULES_VERSION),
        ).fetchone()[0]
        facts = connection.execute(
            _VALID_FACTS_CTE + """
            SELECT verification_status, count(*) AS total
            FROM canonical_fact
            GROUP BY verification_status
            """
        ).fetchall()
    by_status = {row['verification_status']: int(row['total']) for row in facts}
    automated = by_status.get('automatically_validated', 0)
    manual = by_status.get('manually_verified', 0)
    return DashboardMetrics(int(nearest), int(comet), automated, manual, automated + manual)


def _paper_summaries(connection: sqlite3.Connection) -> tuple[PaperSummary, ...]:
    rows = connection.execute(
        _VALID_FACTS_CTE + """
        SELECT paper.*, 
               (SELECT count(*) FROM formulation WHERE paper_id = paper.paper_id) AS formulations,
               (SELECT count(*) FROM chemical_component AS component JOIN formulation AS formulation
                 ON formulation.formulation_id = component.formulation_id WHERE formulation.paper_id = paper.paper_id) AS components,
               (SELECT count(*) FROM experiment WHERE paper_id = paper.paper_id) AS arms,
               (SELECT count(*) FROM outcome AS outcome JOIN experiment AS experiment
                 ON experiment.experiment_id = outcome.experiment_id WHERE experiment.paper_id = paper.paper_id) AS outcomes,
               (SELECT count(*) FROM evidence WHERE paper_id = paper.paper_id) AS evidence,
               (SELECT count(*) FROM canonical_fact WHERE paper_id = paper.paper_id) AS usable_facts,
               (SELECT count(*) FROM import_review WHERE paper_id = paper.paper_id
                 AND review_status IN ('incomplete', 'conflict', 'quarantined', 'blocked')) AS open_reviews,
               (SELECT count(*) FROM review_revision AS revision JOIN experiment AS experiment
                 ON experiment.experiment_id = revision.experiment_id WHERE experiment.paper_id = paper.paper_id) AS revisions
        FROM paper
        ORDER BY coalesce(paper.source_paper_id, ''), paper.paper_id
        """
    ).fetchall()
    return tuple(
        PaperSummary(
            paper_id=int(row['paper_id']), source_paper_id=row['source_paper_id'], title=row['title'],
            doi=row['doi'], pmid=row['pmid'], pmcid=row['pmcid'], source_url=row['source_url'],
            full_text_status=row['full_text_status'], row_counts=PaperRowCounts(
                int(row['formulations']), int(row['components']), int(row['arms']), int(row['outcomes']),
                int(row['evidence']), int(row['usable_facts']), int(row['open_reviews']), int(row['revisions'])
            )
        ) for row in rows
    )


def list_paper_summaries() -> tuple[PaperSummary, ...]:
    with _connect() as connection:
        return _paper_summaries(connection)


def _latest_eligible(connection: sqlite3.Connection, experiment_id: int, profile: str) -> bool:
    row = connection.execute(
        """SELECT eligible FROM eligibility_result AS eligibility
           WHERE experiment_id = ? AND """ + _latest_eligibility_condition(profile),
        (experiment_id, profile, RULES_VERSION),
    ).fetchone()
    return bool(row['eligible']) if row else False


def _current_eligibility_reasons(
    connection: sqlite3.Connection, experiment_id: int, profile: str
) -> tuple[str, ...]:
    row = connection.execute(
        """SELECT reasons_json FROM eligibility_result AS eligibility
           WHERE experiment_id = ? AND """ + _latest_eligibility_condition(profile),
        (experiment_id, profile, RULES_VERSION),
    ).fetchone()
    if row is None:
        return ()
    payload = json.loads(row['reasons_json'])
    return tuple(value for value in payload if isinstance(value, str))


def _review_arm(connection: sqlite3.Connection, row: sqlite3.Row) -> ReviewArm:
    review = connection.execute(
        """SELECT review_tag, review_status, reason_code, field_name FROM import_review
           WHERE arm_id = ? AND review_status IN ('incomplete', 'conflict', 'quarantined', 'blocked')
           ORDER BY import_review_id DESC LIMIT 1""", (row['experiment_id'],)
    ).fetchone()
    assessment = connection.execute(
        """SELECT missing_fields_json, completeness_status, verification_status
           FROM arm_assessment WHERE experiment_id = ?""", (row['experiment_id'],)
    ).fetchone()
    missing = tuple(json.loads(assessment['missing_fields_json'])) if assessment else ()
    return ReviewArm(
        int(row['experiment_id']), int(row['paper_id']), row['source_paper_id'], row['title'],
        row['formulation_name'] or '', row['cell_type'] or '', row['species'] or '', row['payload_type'] or '',
        review['review_tag'] if review else None, review['review_status'] if review else None,
        review['reason_code'] if review else None,
        assessment['completeness_status'] if assessment else 'incomplete',
        assessment['verification_status'] if assessment else 'unreviewed', missing,
        _current_eligibility_reasons(connection, row['experiment_id'], 'comet'),
        _latest_eligible(connection, row['experiment_id'], 'nearest_neighbor'),
        _latest_eligible(connection, row['experiment_id'], 'comet'),
    )


def list_review_arms() -> tuple[ReviewArm, ...]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT experiment.*, paper.source_paper_id, paper.title, formulation.formulation_name
               FROM experiment JOIN paper USING (paper_id) JOIN formulation USING (formulation_id)"""
        ).fetchall()
        arms = [_review_arm(connection, row) for row in rows]
    def priority(arm: ReviewArm) -> int:
        if arm.completeness_status == 'complete' and arm.verification_status != 'manually_verified':
            return 0
        if arm.completeness_status == 'quarantined' or arm.review_status == 'blocked':
            return 4
        if arm.completeness_status == 'conflict' or arm.review_status == 'conflict':
            return 3
        if 1 <= len(arm.comet_blockers) <= 2:
            return 1
        if arm.review_reason_code and (
            'target_cell' in arm.review_reason_code or 'experiment_link' in arm.review_reason_code
        ):
            return 2
        return 4
    return tuple(sorted(arms, key=lambda arm: (priority(arm), arm.paper_id, arm.experiment_id)))


_FIELD_COLUMNS = (
    ('formulation', 'Formulation', 'formulation_name'), ('composition_ratio', 'Composition ratio', 'composition_raw'),
    ('target_cell', 'Target cell', 'cell_type'), ('delivery_cell', 'Delivery cell', 'cell_source'),
    ('species', 'Species', 'species'), ('biological_model', 'Biological model', 'disease_model'),
    ('delivery_setting', 'Delivery setting', 'in_vitro_in_vivo'), ('route', 'Route', 'route'),
    ('payload', 'Payload', 'payload_type'), ('payload_name', 'Payload name', 'payload_name'),
    ('dose', 'Dose', 'dose'), ('assay', 'Assay', 'assay'),
    ('timepoint', 'Timepoint', 'timepoint'),
)


def load_arm_workspace(experiment_id: int) -> ArmWorkspace:
    with _connect() as connection:
        row = connection.execute(
            """SELECT experiment.*, paper.source_paper_id, paper.title, formulation.formulation_name,
                      formulation.composition_raw
               FROM experiment JOIN paper USING (paper_id) JOIN formulation USING (formulation_id)
               WHERE experiment.experiment_id = ?""", (experiment_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f'Unknown experiment_id: {experiment_id}')
        paper = next(summary for summary in _paper_summaries(connection) if summary.paper_id == row['paper_id'])
        arm = _review_arm(connection, row)
        active_corrections = {
            item['field_name']: item['corrected_value']
            for item in connection.execute(
                """SELECT current.field_name, current.corrected_value
                   FROM review_revision AS current
                   WHERE current.experiment_id = ? AND current.decision = 'accepted'
                     AND NOT EXISTS (
                        SELECT 1 FROM review_revision AS later
                        WHERE later.supersedes_review_revision_id = current.review_revision_id
                     )""", (experiment_id,)
            )
        }
        fields = tuple(
            WorkspaceField(
                name, label,
                str(active_corrections[name]) if name in active_corrections else
                ('' if row[column] is None else str(row[column])),
                name not in active_corrections and row[column] is None,
            )
            for name, label, column in _FIELD_COLUMNS
        )
        evidence_rows = connection.execute(
            """SELECT DISTINCT evidence.* FROM evidence
               WHERE evidence.paper_id = ? AND (
                   evidence.experiment_id = ? OR evidence.outcome_id IN (
                       SELECT outcome_id FROM outcome WHERE experiment_id = ?
                   ) OR EXISTS (
                       SELECT 1 FROM import_field_evidence AS field_link
                       WHERE field_link.paper_id = ? AND field_link.evidence_id = evidence.evidence_id
                         AND (
                             (field_link.entity_type = 'arm' AND field_link.entity_id = ?) OR
                             (field_link.entity_type = 'outcome' AND field_link.entity_id IN (
                                 SELECT outcome_id FROM outcome WHERE experiment_id = ?
                             )) OR
                             (field_link.entity_type = 'formulation' AND field_link.entity_id = ?) OR
                             (field_link.entity_type = 'component' AND field_link.entity_id IN (
                                 SELECT component_id FROM chemical_component WHERE formulation_id = ?
                             ))
                         )
                   )
               ) ORDER BY evidence.evidence_id""",
            (row['paper_id'], experiment_id, experiment_id, row['paper_id'], experiment_id,
             experiment_id, row['formulation_id'], row['formulation_id']),
        ).fetchall()
        evidence = tuple(EvidenceExcerpt(
            int(item['evidence_id']), item['field_name'], item['evidence_text'], item['evidence_location_type'],
            ' · '.join(value for value in (item['section_name'], item['page_number'], item['table_number'], item['figure_number'], item['supplement_identifier']) if value),
            item['extraction_method'], item['extraction_confidence'], item['evidence_review_status']
        ) for item in evidence_rows)
        history_rows = connection.execute(
            "SELECT * FROM review_revision WHERE experiment_id = ? ORDER BY reviewed_at DESC, review_revision_id DESC", (experiment_id,)
        ).fetchall()
        history = tuple(ReviewHistory(
            int(item['review_revision_id']), item['field_name'], item['previous_value'], item['corrected_value'],
            item['decision'], item['reviewer'], item['reviewer_notes'], item['reviewed_at']
        ) for item in history_rows)
    return ArmWorkspace(arm, paper, fields, evidence, history)


__all__ = [
    'ArmWorkspace', 'DashboardMetrics', 'EvidenceExcerpt', 'PaperRowCounts', 'PaperSummary',
    'ReviewArm', 'ReviewHistory', 'WorkspaceField', 'authoritative_database_path', 'list_paper_summaries',
    'list_review_arms', 'load_arm_workspace', 'load_dashboard',
]
