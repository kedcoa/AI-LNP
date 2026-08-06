"""Read-only SQLite boundary for the human evidence-review workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Literal

from src.database.audit_current_database import CANONICAL_AUTHORITATIVE_DATABASE
from src.database.database_lifecycle import backup_database
from src.database.migrations import MIGRATION_VERSION
from src.database.status import (
    ArmStatusResult,
    EligibilityResult,
    RULES_VERSION,
    evaluate_arm_status,
    evaluate_eligibility,
)


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
    review_action: str
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
    state_token: str


ReviewAction = Literal[
    'accept', 'correct', 'not_reported', 'reject', 'wrong_arm', 'unresolved'
]


@dataclass(frozen=True)
class WriteReadiness:
    """A verified external backup capability for one review-writing session."""

    ready: bool
    database_path: Path
    schema_version: int | None
    backup_path: Path | None
    backup_sha256: str | None
    failure_reason: str | None = None


@dataclass(frozen=True)
class ReviewDecision:
    """One optimistic, field-scoped human-review action."""

    experiment_id: int
    field_name: str
    decision: ReviewAction
    reviewer: str
    reviewer_notes: str
    expected_review_revision_id: int
    expected_state_token: str
    write_readiness: WriteReadiness
    corrected_value: str | None = None
    evidence_id: int | None = None


@dataclass(frozen=True)
class ReviewResult:
    decision: ReviewAction
    review_revision_id: int | None
    arm_status: ArmStatusResult
    nearest_neighbor: EligibilityResult
    comet: EligibilityResult


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
          json_extract(field_link.content_json, '$.review_revision_id') IS NULL
          OR EXISTS (
              SELECT 1 FROM review_revision AS revision
              WHERE revision.review_revision_id = json_extract(
                        field_link.content_json, '$.review_revision_id'
                    )
                AND revision.decision = 'accepted'
                AND NOT EXISTS (
                    SELECT 1 FROM review_revision AS later
                    WHERE later.supersedes_review_revision_id = revision.review_revision_id
                )
          )
      )
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
        if arm.completeness_status == 'quarantined' or arm.review_status in ('blocked', 'quarantined'):
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
        display_name_by_column = {column: name for name, _label, column in _FIELD_COLUMNS}
        active_corrections = {
            display_name_by_column.get(item['field_name'], item['field_name']): item['corrected_value']
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
            item['decision'], _review_action(item['decision'], item['reviewer_notes']),
            item['reviewer'], item['reviewer_notes'], item['reviewed_at']
        ) for item in history_rows)
    return ArmWorkspace(arm, paper, fields, evidence, history, _review_state_token(connection, experiment_id))


_FIELD_COLUMN_BY_NAME = {name: column for name, _label, column in _FIELD_COLUMNS}
_REVIEWABLE_FIELDS = frozenset(_FIELD_COLUMN_BY_NAME)
_FORMULATION_COLUMNS = frozenset({'formulation_name', 'composition_raw'})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _review_action(decision: str, reviewer_notes: str | None) -> str:
    if reviewer_notes and reviewer_notes.startswith('['):
        marker, separator, _rest = reviewer_notes.partition(']')
        if separator and marker[1:] in {
            'accept', 'correct', 'not_reported', 'reject', 'wrong_arm', 'unresolved'
        }:
            return marker[1:]
    return decision


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _verify_database_safety(connection: sqlite3.Connection) -> int:
    if not connection.in_transaction:
        connection.execute('PRAGMA foreign_keys = ON')
    foreign_keys = connection.execute('PRAGMA foreign_keys').fetchone()
    if foreign_keys is None or foreign_keys[0] != 1:
        raise RuntimeError('SQLite foreign-key enforcement could not be enabled')
    if any(row[0] != 'ok' for row in connection.execute('PRAGMA integrity_check')):
        raise ValueError('SQLite integrity check failed')
    violations = connection.execute('PRAGMA foreign_key_check').fetchall()
    if violations:
        raise ValueError(f'SQLite foreign-key check failed: {violations}')
    versions = tuple(
        row[0] for row in connection.execute(
            'SELECT version FROM schema_migration ORDER BY version'
        )
    )
    expected = tuple(range(1, MIGRATION_VERSION + 1))
    if versions != expected:
        raise ValueError(
            f'Unsupported review schema migrations: expected {expected}, found {versions}'
        )
    return versions[-1]


def _verify_backup(path: Path, expected_sha256: str) -> None:
    if not path.is_file() or _sha256(path) != expected_sha256:
        raise ValueError('Verified external backup is missing or has changed')
    connection = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)
    try:
        _verify_database_safety(connection)
    finally:
        connection.close()


def prepare_writes(backup_dir: Path) -> WriteReadiness:
    """Verify the fixed database and create an externally stored backup first."""

    database_path = authoritative_database_path().resolve()
    try:
        connection = sqlite3.connect(f'{database_path.as_uri()}?mode=ro', uri=True)
        try:
            schema_version = _verify_database_safety(connection)
        finally:
            connection.close()
        backup_path = backup_database(database_path, backup_dir)
        backup_sha256 = _sha256(backup_path)
        _verify_backup(backup_path, backup_sha256)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        return WriteReadiness(
            ready=False, database_path=database_path, schema_version=None,
            backup_path=None, backup_sha256=None, failure_reason=str(error),
        )
    return WriteReadiness(
        ready=True, database_path=database_path, schema_version=schema_version,
        backup_path=backup_path, backup_sha256=backup_sha256,
    )


def _require_write_readiness(readiness: WriteReadiness, database_path: Path) -> None:
    if not readiness.ready:
        raise ValueError(readiness.failure_reason or 'Writes are not ready')
    if readiness.database_path.resolve() != database_path.resolve():
        raise ValueError('Write readiness belongs to a different database')
    if readiness.schema_version != MIGRATION_VERSION:
        raise ValueError('Write readiness has an unsupported schema version')
    if readiness.backup_path is None or readiness.backup_sha256 is None:
        raise ValueError('Write readiness has no verified external backup')
    _verify_backup(readiness.backup_path, readiness.backup_sha256)


def _current_revision_id(connection: sqlite3.Connection, experiment_id: int) -> int:
    return int(connection.execute(
        'SELECT coalesce(max(review_revision_id), 0) FROM review_revision WHERE experiment_id = ?',
        (experiment_id,),
    ).fetchone()[0])


def _review_state_token(connection: sqlite3.Connection, experiment_id: int) -> str:
    """Hash every mutable review-state row the workspace can submit against."""

    state = {
        'scientific': [tuple(row) for row in connection.execute(
            """SELECT experiment.*, formulation.formulation_name, formulation.composition_raw
               FROM experiment JOIN formulation USING (formulation_id)
               WHERE experiment.experiment_id = ?""",
            (experiment_id,),
        )],
        'paper_evidence': [tuple(row) for row in connection.execute(
            """SELECT evidence_id, paper_id, experiment_id, outcome_id, field_name,
                      evidence_text, evidence_location_type, section_name, page_number,
                      table_number, figure_number, supplement_identifier,
                      extraction_method, extraction_confidence, evidence_review_status
               FROM evidence
               WHERE paper_id = (SELECT paper_id FROM experiment WHERE experiment_id = ?)
               ORDER BY evidence_id""",
            (experiment_id,),
        )],
        'revisions': [tuple(row) for row in connection.execute(
            """SELECT review_revision_id, field_name, decision, supersedes_review_revision_id
               FROM review_revision WHERE experiment_id = ? ORDER BY review_revision_id""",
            (experiment_id,),
        )],
        'verifications': [tuple(row) for row in connection.execute(
            """SELECT field_verification_id, field_name, evidence_id, review_revision_id,
                      verification_status
               FROM field_verification WHERE experiment_id = ? ORDER BY field_verification_id""",
            (experiment_id,),
        )],
        'missing': [tuple(row) for row in connection.execute(
            """SELECT missing_field_id, field_name, resolved_by_review_revision_id
               FROM missing_field WHERE experiment_id = ? ORDER BY missing_field_id""",
            (experiment_id,),
        )],
        'reviews': [tuple(row) for row in connection.execute(
            """SELECT import_review_id, reason_code, review_status, evidence_ids_json
               FROM import_review WHERE arm_id = ? ORDER BY import_review_id""",
            (experiment_id,),
        )],
    }
    return hashlib.sha256(json.dumps(state, separators=(',', ':')).encode()).hexdigest()


def _active_revision(
    connection: sqlite3.Connection, experiment_id: int, field_name: str
) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT * FROM review_revision AS current
           WHERE current.experiment_id = ? AND current.field_name = ?
             AND current.decision = 'accepted'
             AND NOT EXISTS (
                 SELECT 1 FROM review_revision AS later
                 WHERE later.supersedes_review_revision_id = current.review_revision_id
             )
           ORDER BY current.review_revision_id DESC LIMIT 1""",
        (experiment_id, field_name),
    ).fetchone()


def _field_value(connection: sqlite3.Connection, experiment_id: int, column: str) -> str:
    if column in _FORMULATION_COLUMNS:
        value = connection.execute(
            f'''SELECT formulation.{column}
                FROM formulation JOIN experiment USING (formulation_id)
                WHERE experiment.experiment_id = ?''',
            (experiment_id,),
        ).fetchone()[0]
    else:
        value = connection.execute(
            f'SELECT {column} FROM experiment WHERE experiment_id = ?', (experiment_id,)
        ).fetchone()[0]
    return '' if value is None else str(value)


def _owned_evidence(
    connection: sqlite3.Connection,
    experiment_id: int,
    paper_id: int,
    evidence_id: int,
    *,
    require_current_arm: bool,
) -> sqlite3.Row:
    evidence = connection.execute(
        'SELECT * FROM evidence WHERE evidence_id = ?', (evidence_id,)
    ).fetchone()
    if evidence is None:
        raise ValueError(f'Unknown evidence_id: {evidence_id}')
    if evidence['paper_id'] != paper_id:
        raise ValueError('Supporting evidence must belong to the same paper')
    if require_current_arm:
        linked_outcome = evidence['outcome_id'] is not None and connection.execute(
            'SELECT 1 FROM outcome WHERE outcome_id = ? AND experiment_id = ?',
            (evidence['outcome_id'], experiment_id),
        ).fetchone()
        formulation_link = connection.execute(
            """SELECT 1 FROM import_field_evidence AS link
               JOIN experiment AS experiment ON experiment.formulation_id = link.entity_id
               WHERE link.evidence_id = ? AND link.paper_id = ?
                 AND link.entity_type = 'formulation' AND experiment.experiment_id = ?""",
            (evidence_id, paper_id, experiment_id),
        ).fetchone()
        if (
            evidence['experiment_id'] != experiment_id
            and linked_outcome is None
            and formulation_link is None
        ):
            raise ValueError('Supporting evidence must belong to the selected arm')
    return evidence


def _evidence_location(evidence: sqlite3.Row) -> str:
    return ' · '.join(
        str(value) for value in (
            evidence['section_name'], evidence['page_number'], evidence['table_number'],
            evidence['figure_number'], evidence['supplement_identifier'],
        ) if value
    ) or evidence['evidence_location_type']


def _insert_verification(
    connection: sqlite3.Connection, request: ReviewDecision, field_name: str,
    status: str, review_revision_id: int | None,
) -> int:
    cursor = connection.execute(
        """INSERT INTO field_verification (
               experiment_id, field_name, evidence_id, review_revision_id,
               verification_status, notes, verified_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (request.experiment_id, field_name, request.evidence_id, review_revision_id,
         status, request.reviewer_notes.strip(), _utc_now()),
    )
    return int(cursor.lastrowid)


def _canonical_entity(
    connection: sqlite3.Connection, experiment_id: int, field_name: str
) -> tuple[str, int]:
    if field_name in _FORMULATION_COLUMNS:
        formulation_id = connection.execute(
            'SELECT formulation_id FROM experiment WHERE experiment_id = ?', (experiment_id,)
        ).fetchone()[0]
        return 'formulation', int(formulation_id)
    return 'arm', experiment_id


def _record_canonical_field_evidence(
    connection: sqlite3.Connection, request: ReviewDecision, paper_id: int,
    field_name: str, evidence_id: int, review_revision_id: int,
) -> None:
    """Promote one human-verified arm/evidence link into dashboard fact accounting."""

    entity_type, entity_id = _canonical_entity(connection, request.experiment_id, field_name)
    payload = json.dumps({
        'evidence_id': evidence_id,
        'field_name': field_name,
        'review_revision_id': review_revision_id,
        'verification_status': 'manually_verified',
    }, sort_keys=True)
    connection.execute(
        """INSERT INTO import_field_evidence (
               paper_id, entity_type, entity_id, field_name, evidence_id,
               verification_status, notes, natural_key, content_sha256, content_json
           ) VALUES (?, ?, ?, ?, ?, 'manually_verified', ?, ?, ?, ?)""",
        (paper_id, entity_type, entity_id, field_name, evidence_id, request.reviewer_notes.strip(),
         f'human-review:{review_revision_id}', hashlib.sha256(payload.encode()).hexdigest(), payload),
    )


def _record_rejected_field_evidence(
    connection: sqlite3.Connection, request: ReviewDecision, paper_id: int,
    field_name: str, evidence_id: int, verification_id: int,
) -> None:
    """Append a rejected canonical link so it supersedes the prior field/evidence status."""

    entity_type, entity_id = _canonical_entity(connection, request.experiment_id, field_name)
    payload = json.dumps({
        'evidence_id': evidence_id,
        'field_name': field_name,
        'field_verification_id': verification_id,
        'verification_status': 'rejected',
    }, sort_keys=True)
    connection.execute(
        """INSERT INTO import_field_evidence (
               paper_id, entity_type, entity_id, field_name, evidence_id,
               verification_status, notes, natural_key, content_sha256, content_json
           ) VALUES (?, ?, ?, ?, ?, 'rejected', ?, ?, ?, ?)""",
        (paper_id, entity_type, entity_id, field_name, evidence_id, request.reviewer_notes.strip(),
         f'human-review-rejection:{verification_id}', hashlib.sha256(payload.encode()).hexdigest(), payload),
    )


def _mark_missing(
    connection: sqlite3.Connection, experiment_id: int, field_name: str, reason: str,
    revision_id: int | None,
) -> None:
    if revision_id is None:
        connection.execute(
            """INSERT INTO missing_field (experiment_id, field_name, reason, recorded_at)
               VALUES (?, ?, ?, ?)""",
            (experiment_id, field_name, reason, _utc_now()),
        )
        return
    unresolved = connection.execute(
        """SELECT missing_field_id FROM missing_field
           WHERE experiment_id = ? AND field_name = ?
             AND resolved_by_review_revision_id IS NULL
           ORDER BY missing_field_id DESC LIMIT 1""",
        (experiment_id, field_name),
    ).fetchone()
    if unresolved is not None:
        connection.execute(
            """UPDATE missing_field SET resolved_by_review_revision_id = ?, resolved_at = ?
               WHERE missing_field_id = ?""",
            (revision_id, _utc_now(), unresolved[0]),
        )


def _insert_review_revision(
    connection: sqlite3.Connection, request: ReviewDecision, field_name: str,
    previous_value: str, corrected_value: str, evidence: sqlite3.Row | None,
    decision: str, supersedes_revision_id: int | None, reviewer_notes: str | None = None,
) -> int:
    is_evidence_row = evidence is not None and 'evidence_text' in evidence.keys()
    evidence_excerpt = (
        evidence['evidence_text'] if is_evidence_row
        else evidence['evidence_excerpt'] if evidence is not None
        else f'Reviewer confirmed that {request.field_name} is not reported.'
    )
    evidence_location_type = (
        evidence['evidence_location_type'] if is_evidence_row
        else evidence['evidence_location_type'] if evidence is not None
        else 'human_review'
    )
    evidence_location = (
        _evidence_location(evidence) if is_evidence_row
        else evidence['evidence_location'] if evidence is not None
        else 'human review record'
    )
    cursor = connection.execute(
        """INSERT INTO review_revision (
               experiment_id, field_name, previous_value, corrected_value, evidence_excerpt,
               evidence_location_type, evidence_location, reviewer, decision,
               supersedes_review_revision_id, reviewer_notes, reviewed_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (request.experiment_id, field_name, previous_value, corrected_value,
         evidence_excerpt, evidence_location_type, evidence_location,
         request.reviewer.strip(), decision, supersedes_revision_id,
         f'[{request.decision}] {(reviewer_notes or request.reviewer_notes).strip()}', _utc_now()),
    )
    return int(cursor.lastrowid)


def _recalculate(connection: sqlite3.Connection, experiment_id: int) -> tuple[
    ArmStatusResult, EligibilityResult, EligibilityResult
]:
    status = evaluate_arm_status(connection, experiment_id)
    nearest = evaluate_eligibility(connection, experiment_id, 'nearest_neighbor')
    comet = evaluate_eligibility(connection, experiment_id, 'comet')
    return status, nearest, comet


def _verify_review_consistency(connection: sqlite3.Connection, experiment_id: int) -> None:
    """Reject a transaction if its linked review state is internally inconsistent."""

    invalid_verification = connection.execute(
        """SELECT 1 FROM field_verification AS verification
           WHERE verification.experiment_id = ?
             AND verification.review_revision_id IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM review_revision AS revision
                 WHERE revision.review_revision_id = verification.review_revision_id
                   AND revision.experiment_id = verification.experiment_id
                   AND revision.field_name = verification.field_name
             )""",
        (experiment_id,),
    ).fetchone()
    if invalid_verification is not None:
        raise ValueError('Field verification is inconsistent with review history')
def apply_review_decision(request: ReviewDecision) -> ReviewResult:
    """Atomically apply one validated decision to the fixed authoritative database."""

    database_path = authoritative_database_path().resolve()
    _require_write_readiness(request.write_readiness, database_path)
    if request.decision not in {
        'accept', 'correct', 'not_reported', 'reject', 'wrong_arm', 'unresolved'
    }:
        raise ValueError(f'Unsupported review decision: {request.decision}')
    if not request.reviewer.strip() or not request.reviewer_notes.strip():
        raise ValueError('A reviewer and reviewer note are required for every decision')
    if request.field_name not in _REVIEWABLE_FIELDS:
        raise ValueError(f'Unsupported review field: {request.field_name}')
    field_name = _FIELD_COLUMN_BY_NAME[request.field_name]
    connection = sqlite3.connect(database_path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        _verify_database_safety(connection)
        connection.execute('BEGIN IMMEDIATE')
        experiment = connection.execute(
            'SELECT * FROM experiment WHERE experiment_id = ?', (request.experiment_id,)
        ).fetchone()
        if experiment is None:
            raise KeyError(f'Unknown experiment_id: {request.experiment_id}')
        current_revision_id = _current_revision_id(connection, request.experiment_id)
        if current_revision_id != request.expected_review_revision_id:
            raise ValueError('Review submission is stale; reload the arm workspace')
        if _review_state_token(connection, request.experiment_id) != request.expected_state_token:
            raise ValueError('Review submission is stale; reload the arm workspace')
        active = _active_revision(connection, request.experiment_id, field_name)
        revision_id: int | None = None
        if request.decision in {'accept', 'correct'}:
            if request.decision == 'correct' and not (request.corrected_value or '').strip():
                raise ValueError('A corrected value is required')
            if request.evidence_id is None:
                raise ValueError('Supporting evidence is required for an accepted correction')
            evidence = _owned_evidence(
                connection, request.experiment_id, experiment['paper_id'], request.evidence_id,
                require_current_arm=True,
            )
            corrected_value = (
                request.corrected_value.strip() if request.decision == 'correct'
                else (active['corrected_value'] if active is not None else _field_value(
                    connection, request.experiment_id, field_name
                ))
            )
            if not corrected_value.strip():
                raise ValueError('An empty extracted value cannot be accepted')
            revision_id = _insert_review_revision(
                connection, request, field_name, _field_value(connection, request.experiment_id, field_name),
                corrected_value, evidence, 'accepted',
                int(active['review_revision_id']) if active is not None else None,
            )
            _insert_verification(connection, request, field_name, 'manually_verified', revision_id)
            _record_canonical_field_evidence(
                connection, request, experiment['paper_id'], field_name, request.evidence_id, revision_id
            )
            _mark_missing(connection, request.experiment_id, field_name, '', revision_id)
        elif request.decision == 'reject':
            if request.evidence_id is None and active is None:
                raise ValueError('Evidence is required to reject original extraction')
            evidence = (
                _owned_evidence(
                    connection, request.experiment_id, experiment['paper_id'], request.evidence_id,
                    require_current_arm=True,
                ) if request.evidence_id is not None else active
            )
            if active is not None:
                revision_id = _insert_review_revision(
                    connection, request, field_name, active['corrected_value'], active['corrected_value'],
                    evidence, 'rejected', int(active['review_revision_id']),
                )
            verification_id = _insert_verification(
                connection, request, field_name, 'rejected', revision_id
            )
            if request.evidence_id is not None:
                _record_rejected_field_evidence(
                    connection, request, experiment['paper_id'], field_name,
                    request.evidence_id, verification_id,
                )
            _mark_missing(connection, request.experiment_id, field_name, 'rejected during human review', None)
        elif request.decision == 'not_reported':
            _insert_verification(connection, request, field_name, 'rejected', None)
            _mark_missing(connection, request.experiment_id, field_name, 'not reported', None)
        elif request.decision == 'unresolved':
            _insert_verification(connection, request, field_name, 'ambiguous', None)
            _mark_missing(connection, request.experiment_id, field_name, request.decision.replace('_', ' '), None)
        else:
            if request.evidence_id is None:
                raise ValueError('Evidence is required to flag a wrong arm')
            evidence = _owned_evidence(
                connection, request.experiment_id, experiment['paper_id'], request.evidence_id,
                require_current_arm=False,
            )
            if evidence['experiment_id'] in (None, request.experiment_id):
                raise ValueError('Wrong-arm evidence must be linked to another arm')
            content = json.dumps({
                'experiment_id': request.experiment_id, 'field_name': field_name,
                'evidence_id': request.evidence_id, 'notes': request.reviewer_notes.strip(),
            }, sort_keys=True)
            content_sha256 = hashlib.sha256(content.encode()).hexdigest()
            connection.execute(
                """INSERT INTO import_review (
                       paper_id, natural_key, arm_id, reason_code, review_status, review_tag,
                       field_name, notes, evidence_ids_json, content_sha256
                   ) VALUES (?, ?, ?, 'wrong_arm_evidence', 'conflict', 'Experiment link unclear',
                             ?, ?, ?, ?)""",
                (experiment['paper_id'], f'wrong-arm:{request.experiment_id}:{request.evidence_id}:{field_name}',
                 request.experiment_id, field_name, request.reviewer_notes.strip(),
                 json.dumps([request.evidence_id]), content_sha256),
            )
            _insert_verification(connection, request, field_name, 'conflict', None)
            if active is not None:
                revision_id = _insert_review_revision(
                    connection, request, field_name, active['corrected_value'], active['corrected_value'],
                    evidence, 'rejected', int(active['review_revision_id']),
                    request.reviewer_notes,
                )
            _mark_missing(connection, request.experiment_id, field_name, 'evidence belongs to another arm', None)
        status, nearest, comet = _recalculate(connection, request.experiment_id)
        _verify_review_consistency(connection, request.experiment_id)
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQLite foreign-key check failed after decision')
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    return ReviewResult(request.decision, revision_id, status, nearest, comet)


__all__ = [
    'ArmWorkspace', 'DashboardMetrics', 'EvidenceExcerpt', 'PaperRowCounts', 'PaperSummary',
    'ReviewArm', 'ReviewDecision', 'ReviewHistory', 'ReviewResult', 'WorkspaceField', 'WriteReadiness',
    'apply_review_decision', 'authoritative_database_path', 'list_paper_summaries', 'list_review_arms',
    'load_arm_workspace', 'load_dashboard', 'prepare_writes',
]
