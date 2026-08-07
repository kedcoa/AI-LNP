"""Additive SQLite migrations for the working evidence database."""

from __future__ import annotations

import re
import sqlite3


MIGRATION_VERSION = 6

PAPER_COLUMNS = {
    "source_paper_id": "TEXT",
    "import_status": "TEXT NOT NULL DEFAULT 'needs_review' CHECK (import_status IN ('ready', 'ready_with_missing_fields', 'needs_review', 'blocked', 'screening_only'))",
}

EXPERIMENT_COLUMNS = {
    "tissue_or_organ": "TEXT",
    "disease_model": "TEXT",
    "payload_encoded_product": "TEXT",
    "payload_molecular_target": "TEXT",
}

FORMULATION_COLUMNS = {
    "chemical_formulation_total": "TEXT",
    "lnp_molar_ratio": "TEXT",
}

CHEMICAL_COMPONENT_COLUMNS = {
    "component_name_normalized": "TEXT",
    "inchikey": "TEXT",
    "molar_percentage": "REAL CHECK (molar_percentage IS NULL OR (molar_percentage >= 0 AND molar_percentage <= 100))",
    "percentage_unit": "TEXT",
    "component_review_status": "TEXT NOT NULL DEFAULT 'unreviewed'",
    "identity_source": "TEXT",
    "identity_notes": "TEXT",
    "amount_value": "REAL",
    "amount_unit": "TEXT",
    "amount_raw": "TEXT",
    "composition_position": "INTEGER CHECK (composition_position IS NULL OR composition_position > 0)",
}

REVIEW_REVISION_COLUMNS = {
    "supersedes_review_revision_id": (
        "INTEGER REFERENCES review_revision(review_revision_id) "
        "ON UPDATE CASCADE ON DELETE RESTRICT"
    ),
    "review_action": (
        "TEXT CHECK (review_action IN "
        "('accept', 'correct', 'not_reported', 'reject', 'wrong_arm', 'unresolved'))"
    ),
    "evidence_id": (
        "INTEGER REFERENCES evidence(evidence_id) ON UPDATE CASCADE ON DELETE RESTRICT"
    ),
}

LOSSLESS_FACT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_artifact (
    source_artifact_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES paper(paper_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    logical_path TEXT NOT NULL CHECK(length(trim(logical_path)) > 0),
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    role TEXT NOT NULL CHECK(length(trim(role)) > 0),
    schema_family TEXT NOT NULL CHECK(length(trim(schema_family)) > 0),
    pipeline_name TEXT,
    pipeline_version TEXT,
    validation_status TEXT NOT NULL CHECK(length(trim(validation_status)) > 0),
    contributes_facts INTEGER NOT NULL CHECK(contributes_facts IN (0, 1)),
    contributes_evidence INTEGER NOT NULL CHECK(contributes_evidence IN (0, 1)),
    UNIQUE(paper_id, logical_path, sha256, role)
);

CREATE TABLE IF NOT EXISTS source_fact (
    source_fact_id INTEGER PRIMARY KEY,
    source_artifact_id INTEGER NOT NULL REFERENCES source_artifact(source_artifact_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    paper_id INTEGER NOT NULL REFERENCES paper(paper_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    json_path TEXT NOT NULL CHECK(length(trim(json_path)) > 0),
    source_record_key TEXT NOT NULL CHECK(length(trim(source_record_key)) > 0),
    record_kind TEXT NOT NULL CHECK(length(trim(record_kind)) > 0),
    source_context_key TEXT,
    subject_type TEXT NOT NULL CHECK(length(trim(subject_type)) > 0),
    subject_key TEXT NOT NULL CHECK(length(trim(subject_key)) > 0),
    field_name TEXT NOT NULL CHECK(length(trim(field_name)) > 0),
    raw_value_json TEXT NOT NULL CHECK(json_valid(raw_value_json)),
    canonical_value_json TEXT CHECK(canonical_value_json IS NULL OR json_valid(canonical_value_json)),
    fact_identity_sha256 TEXT NOT NULL CHECK(length(fact_identity_sha256) = 64),
    import_disposition TEXT NOT NULL CHECK(import_disposition IN ('projected', 'unresolved', 'quarantined', 'rejected')),
    disposition_reason TEXT,
    UNIQUE(source_artifact_id, json_path, source_record_key, field_name),
    CHECK(
        import_disposition = 'projected'
        OR length(trim(coalesce(disposition_reason, ''))) > 0
    )
);

CREATE TABLE IF NOT EXISTS source_fact_evidence (
    source_fact_evidence_id INTEGER PRIMARY KEY,
    source_fact_id INTEGER NOT NULL REFERENCES source_fact(source_fact_id) ON UPDATE CASCADE ON DELETE CASCADE,
    source_evidence_key TEXT NOT NULL CHECK(length(trim(source_evidence_key)) > 0),
    evidence_id INTEGER REFERENCES evidence(evidence_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    resolution_status TEXT NOT NULL CHECK(resolution_status IN ('resolved', 'unresolved', 'rejected')),
    resolution_reason TEXT,
    UNIQUE(source_fact_id, source_evidence_key),
    CHECK(
        (resolution_status = 'resolved' AND evidence_id IS NOT NULL)
        OR (
            resolution_status != 'resolved'
            AND length(trim(coalesce(resolution_reason, ''))) > 0
        )
    )
);

CREATE TABLE IF NOT EXISTS fact_projection (
    fact_projection_id INTEGER PRIMARY KEY,
    source_fact_id INTEGER NOT NULL REFERENCES source_fact(source_fact_id) ON UPDATE CASCADE ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES paper(paper_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('paper', 'formulation', 'component', 'chemical_component', 'arm', 'experiment', 'outcome', 'evidence')),
    entity_id INTEGER NOT NULL,
    field_name TEXT NOT NULL CHECK(length(trim(field_name)) > 0),
    canonical_fact_sha256 TEXT NOT NULL CHECK(length(canonical_fact_sha256) = 64),
    projection_status TEXT NOT NULL CHECK(projection_status IN ('active', 'superseded', 'rejected')),
    UNIQUE(source_fact_id, entity_type, entity_id, field_name, canonical_fact_sha256)
);

CREATE INDEX IF NOT EXISTS idx_source_artifact_paper ON source_artifact(paper_id);
CREATE INDEX IF NOT EXISTS idx_source_fact_artifact ON source_fact(source_artifact_id);
CREATE INDEX IF NOT EXISTS idx_source_fact_paper ON source_fact(paper_id);
CREATE INDEX IF NOT EXISTS idx_fact_projection_fact ON fact_projection(source_fact_id);

CREATE TRIGGER IF NOT EXISTS trg_source_fact_artifact_same_paper_insert
BEFORE INSERT ON source_fact
WHEN NOT EXISTS (
    SELECT 1 FROM source_artifact
    WHERE source_artifact_id = NEW.source_artifact_id
      AND paper_id = NEW.paper_id
)
BEGIN
    SELECT RAISE(ABORT, 'source fact artifact must belong to same paper');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_fact_artifact_same_paper_update
BEFORE UPDATE OF source_artifact_id, paper_id ON source_fact
WHEN NOT EXISTS (
    SELECT 1 FROM source_artifact
    WHERE source_artifact_id = NEW.source_artifact_id
      AND paper_id = NEW.paper_id
)
BEGIN
    SELECT RAISE(ABORT, 'source fact artifact must belong to same paper');
END;

CREATE TRIGGER IF NOT EXISTS trg_fact_projection_same_paper_insert
BEFORE INSERT ON fact_projection
WHEN NOT EXISTS (
    SELECT 1 FROM source_fact
    WHERE source_fact_id = NEW.source_fact_id AND paper_id = NEW.paper_id
)
OR NOT (
    (NEW.entity_type = 'paper' AND EXISTS (
        SELECT 1 FROM paper WHERE paper_id = NEW.entity_id AND paper_id = NEW.paper_id
    ))
    OR (NEW.entity_type = 'formulation' AND EXISTS (
        SELECT 1 FROM formulation WHERE formulation_id = NEW.entity_id AND paper_id = NEW.paper_id
    ))
    OR (NEW.entity_type IN ('component', 'chemical_component') AND EXISTS (
        SELECT 1 FROM chemical_component JOIN formulation USING(formulation_id)
        WHERE component_id = NEW.entity_id AND paper_id = NEW.paper_id
    ))
    OR (NEW.entity_type IN ('arm', 'experiment') AND EXISTS (
        SELECT 1 FROM experiment WHERE experiment_id = NEW.entity_id AND paper_id = NEW.paper_id
    ))
    OR (NEW.entity_type = 'outcome' AND EXISTS (
        SELECT 1 FROM outcome JOIN experiment USING(experiment_id)
        WHERE outcome_id = NEW.entity_id AND paper_id = NEW.paper_id
    ))
    OR (NEW.entity_type = 'evidence' AND EXISTS (
        SELECT 1 FROM evidence WHERE evidence_id = NEW.entity_id AND paper_id = NEW.paper_id
    ))
)
BEGIN
    SELECT RAISE(ABORT, 'fact projection target must belong to same paper');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_fact_projected_insert_requires_projection
BEFORE INSERT ON source_fact
WHEN NEW.import_disposition = 'projected'
BEGIN
    SELECT RAISE(ABORT, 'projected source fact must be linked after insertion');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_fact_projected_update_requires_projection
BEFORE UPDATE OF import_disposition ON source_fact
WHEN NEW.import_disposition = 'projected'
 AND NOT EXISTS (
     SELECT 1 FROM fact_projection
     WHERE source_fact_id = NEW.source_fact_id AND projection_status = 'active'
 )
BEGIN
    SELECT RAISE(ABORT, 'projected source fact requires active projection');
END;


CREATE TRIGGER IF NOT EXISTS trg_fact_projection_no_update
BEFORE UPDATE ON fact_projection
BEGIN
    SELECT RAISE(ABORT, 'fact projections are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_fact_projection_active_delete_guard
BEFORE DELETE ON fact_projection
WHEN OLD.projection_status = 'active'
 AND EXISTS (
     SELECT 1 FROM source_fact
     WHERE source_fact_id = OLD.source_fact_id
       AND import_disposition = 'projected'
 )
 AND NOT EXISTS (
     SELECT 1 FROM fact_projection
     WHERE source_fact_id = OLD.source_fact_id
       AND projection_status = 'active'
       AND fact_projection_id != OLD.fact_projection_id
 )
BEGIN
    SELECT RAISE(ABORT, 'projected source fact requires active projection');
END;

CREATE VIEW IF NOT EXISTS lnp_formulation_wide AS
SELECT
    formulation.formulation_name AS lnp_name,
    coalesce(
        formulation.chemical_formulation_total,
        (
            SELECT group_concat(component_name, '-')
            FROM (
                SELECT component_name_reported AS component_name
                FROM chemical_component
                WHERE formulation_id = formulation.formulation_id
                  AND component_role IN ('ionizable_lipid', 'helper_lipid', 'cholesterol', 'peg_lipid')
                ORDER BY coalesce(composition_position, component_id), component_id
            )
        )
    ) AS chemical_formulation_total,
    coalesce(
        formulation.lnp_molar_ratio,
        (
            SELECT group_concat(amount, ':')
            FROM (
                SELECT CASE
                    WHEN length(trim(coalesce(amount_raw, ''))) > 0 THEN amount_raw
                    WHEN amount_value IS NOT NULL THEN printf('%g', amount_value)
                    WHEN molar_percentage IS NOT NULL THEN printf('%g', molar_percentage)
                END AS amount
                FROM chemical_component
                WHERE formulation_id = formulation.formulation_id
                  AND component_role IN ('ionizable_lipid', 'helper_lipid', 'cholesterol', 'peg_lipid')
                  AND coalesce(amount_raw, amount_value, molar_percentage) IS NOT NULL
                ORDER BY coalesce(composition_position, component_id), component_id
            )
        )
    ) AS lnp_molar_ratio,
    (SELECT group_concat(component_name, '; ') FROM (
        SELECT component_name_reported AS component_name FROM chemical_component
        WHERE formulation_id = formulation.formulation_id AND component_role = 'ionizable_lipid'
        ORDER BY coalesce(composition_position, component_id), component_id
    )) AS ionizable_lipid,
    (SELECT group_concat(component_name, '; ') FROM (
        SELECT component_name_reported AS component_name FROM chemical_component
        WHERE formulation_id = formulation.formulation_id AND component_role = 'helper_lipid'
        ORDER BY coalesce(composition_position, component_id), component_id
    )) AS helper_lipid,
    (SELECT group_concat(component_name, '; ') FROM (
        SELECT component_name_reported AS component_name FROM chemical_component
        WHERE formulation_id = formulation.formulation_id AND component_role = 'cholesterol'
        ORDER BY coalesce(composition_position, component_id), component_id
    )) AS cholesterol,
    (SELECT group_concat(component_name, '; ') FROM (
        SELECT component_name_reported AS component_name FROM chemical_component
        WHERE formulation_id = formulation.formulation_id AND component_role = 'peg_lipid'
        ORDER BY coalesce(composition_position, component_id), component_id
    )) AS peg_lipid,
    (SELECT group_concat(component_name, '; ') FROM (
        SELECT component_name_reported AS component_name FROM chemical_component
        WHERE formulation_id = formulation.formulation_id
          AND component_role NOT IN ('ionizable_lipid', 'helper_lipid', 'cholesterol', 'peg_lipid')
        ORDER BY coalesce(composition_position, component_id), component_id
    )) AS others
FROM formulation;

INSERT OR IGNORE INTO schema_migration (version, name, applied_at)
VALUES (6, 'lossless_source_fact_ledger', '2026-08-07T00:00:00Z');
"""

CHEMICAL_COMPONENT_V6_SQL = """
CREATE TABLE chemical_component_v6 (
    component_id INTEGER PRIMARY KEY,
    formulation_id INTEGER NOT NULL,
    component_name_reported TEXT NOT NULL,
    component_name_normalized TEXT,
    component_role TEXT NOT NULL CHECK (
        component_role IN (
            'ionizable_lipid', 'helper_lipid', 'cholesterol', 'peg_lipid',
            'targeting_ligand', 'targeting_anchor', 'adjuvant',
            'small_molecule_additive', 'sort_lipid', 'other'
        )
    ),
    inchikey TEXT,
    molar_percentage REAL CHECK (
        molar_percentage IS NULL
        OR (molar_percentage >= 0 AND molar_percentage <= 100)
    ),
    percentage_unit TEXT,
    component_review_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK (
        component_review_status IN (
            'unreviewed', 'automatically_normalized', 'manually_verified',
            'ambiguous', 'conflict', 'rejected'
        )
    ),
    identity_source TEXT,
    identity_notes TEXT,
    amount_value REAL,
    amount_unit TEXT,
    amount_raw TEXT,
    composition_position INTEGER CHECK (
        composition_position IS NULL OR composition_position > 0
    ),
    FOREIGN KEY (formulation_id) REFERENCES formulation(formulation_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
"""

ADDITIVE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS record_source (
    record_source_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('paper', 'formulation', 'chemical_component', 'experiment', 'outcome', 'evidence')),
    entity_id INTEGER,
    artifact_path TEXT NOT NULL CHECK (length(trim(artifact_path)) > 0),
    artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    pipeline_name TEXT NOT NULL CHECK (length(trim(pipeline_name)) > 0),
    pipeline_version TEXT,
    extraction_run_identifier TEXT,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS review_revision (
    review_revision_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'arm',
    entity_id INTEGER,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    previous_value TEXT,
    corrected_value TEXT NOT NULL CHECK (length(trim(corrected_value)) > 0),
    evidence_excerpt TEXT NOT NULL CHECK (length(trim(evidence_excerpt)) > 0),
    evidence_location_type TEXT,
    evidence_location TEXT NOT NULL CHECK (length(trim(evidence_location)) > 0),
    reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
    decision TEXT NOT NULL DEFAULT 'accepted' CHECK (decision IN ('accepted', 'rejected', 'superseded')),
    supersedes_review_revision_id INTEGER,
    reviewer_notes TEXT,
    reviewed_at TEXT NOT NULL,
    review_action TEXT CHECK (review_action IN ('accept', 'correct', 'not_reported', 'reject', 'wrong_arm', 'unresolved')),
    evidence_id INTEGER,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (supersedes_review_revision_id) REFERENCES review_revision(review_revision_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS missing_field (
    missing_field_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    recorded_at TEXT NOT NULL,
    resolved_by_review_revision_id INTEGER,
    resolved_at TEXT,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (resolved_by_review_revision_id) REFERENCES review_revision(review_revision_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK ((resolved_by_review_revision_id IS NULL AND resolved_at IS NULL) OR (resolved_by_review_revision_id IS NOT NULL AND resolved_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS field_verification (
    field_verification_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    evidence_id INTEGER,
    review_revision_id INTEGER,
    verification_status TEXT NOT NULL CHECK (verification_status IN ('unreviewed', 'automatically_validated', 'manually_verified', 'ambiguous', 'conflict', 'rejected')),
    notes TEXT,
    verified_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (review_revision_id) REFERENCES review_revision(review_revision_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS arm_assessment (
    experiment_id INTEGER PRIMARY KEY,
    completeness_status TEXT NOT NULL CHECK (completeness_status IN ('complete', 'incomplete', 'conflict', 'quarantined')),
    missing_fields_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(missing_fields_json)),
    verification_status TEXT NOT NULL CHECK (verification_status IN ('unreviewed', 'automatically_validated', 'manually_verified', 'ambiguous', 'conflict', 'rejected')),
    nearest_neighbor_eligible INTEGER NOT NULL DEFAULT 0 CHECK (nearest_neighbor_eligible IN (0, 1)),
    comet_eligible INTEGER NOT NULL DEFAULT 0 CHECK (comet_eligible IN (0, 1)),
    quarantine_reason TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE CASCADE,
    CHECK (completeness_status != 'quarantined' OR length(trim(quarantine_reason)) > 0)
);

CREATE TABLE IF NOT EXISTS screening_event (
    screening_event_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('include', 'exclude', 'manual_review', 'screening_only')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    search_query_id TEXT,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS eligibility_result (
    experiment_id INTEGER NOT NULL,
    profile TEXT NOT NULL CHECK (profile IN ('nearest_neighbor', 'comet')),
    eligible INTEGER NOT NULL CHECK (eligible IN (0, 1)),
    reasons_json TEXT NOT NULL CHECK (json_valid(reasons_json)),
    rules_version TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY (experiment_id, profile),
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_source_paper_id
    ON paper(source_paper_id) WHERE source_paper_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_record_source_paper ON record_source(paper_id);
CREATE INDEX IF NOT EXISTS idx_missing_field_experiment ON missing_field(experiment_id);
CREATE INDEX IF NOT EXISTS idx_field_verification_experiment ON field_verification(experiment_id);
CREATE INDEX IF NOT EXISTS idx_review_revision_experiment ON review_revision(experiment_id);
CREATE INDEX IF NOT EXISTS idx_screening_event_paper ON screening_event(paper_id);

CREATE TRIGGER IF NOT EXISTS trg_review_revision_no_update
BEFORE UPDATE ON review_revision
BEGIN
    SELECT RAISE(ABORT, 'review revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_revision_no_delete
BEFORE DELETE ON review_revision
BEGIN
    SELECT RAISE(ABORT, 'review revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_screening_only_not_ready
BEFORE UPDATE OF import_status ON paper
WHEN OLD.import_status = 'screening_only'
 AND NEW.import_status IN ('ready', 'ready_with_missing_fields')
BEGIN
    SELECT RAISE(ABORT, 'screening-only papers cannot become import candidates');
END;

CREATE TRIGGER IF NOT EXISTS trg_excluded_paper_not_ready_insert
BEFORE INSERT ON paper
WHEN NEW.screening_status = 'exclude'
 AND NEW.import_status IN ('ready', 'ready_with_missing_fields')
BEGIN
    SELECT RAISE(ABORT, 'excluded papers cannot become import candidates');
END;

CREATE TRIGGER IF NOT EXISTS trg_excluded_paper_not_ready_update
BEFORE UPDATE OF screening_status, import_status ON paper
WHEN NEW.screening_status = 'exclude'
 AND NEW.import_status IN ('ready', 'ready_with_missing_fields')
BEGIN
    SELECT RAISE(ABORT, 'excluded papers cannot become import candidates');
END;

INSERT OR IGNORE INTO schema_migration (version, name, applied_at)
VALUES (1, 'working_evidence_database_contract', '2026-08-06T00:00:00Z');
"""

INTEGRITY_SCHEMA_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_revision_superseded_once
    ON review_revision(supersedes_review_revision_id)
    WHERE supersedes_review_revision_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_missing_field_resolution_matches_insert
BEFORE INSERT ON missing_field
WHEN NEW.resolved_by_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM review_revision
    WHERE review_revision_id = NEW.resolved_by_review_revision_id
      AND experiment_id = NEW.experiment_id
      AND field_name = NEW.field_name
      AND decision = 'accepted'
 )
BEGIN
    SELECT RAISE(ABORT, 'missing field resolution requires matching experiment and field');
END;

CREATE TRIGGER IF NOT EXISTS trg_missing_field_resolution_matches_update
BEFORE UPDATE OF experiment_id, field_name, resolved_by_review_revision_id
ON missing_field
WHEN NEW.resolved_by_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM review_revision
    WHERE review_revision_id = NEW.resolved_by_review_revision_id
      AND experiment_id = NEW.experiment_id
      AND field_name = NEW.field_name
      AND decision = 'accepted'
 )
BEGIN
    SELECT RAISE(ABORT, 'missing field resolution requires matching experiment and field');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_revision_supersession_matches
BEFORE INSERT ON review_revision
WHEN NEW.supersedes_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM review_revision
    WHERE review_revision_id = NEW.supersedes_review_revision_id
      AND experiment_id = NEW.experiment_id
      AND field_name = NEW.field_name
      AND decision = 'accepted'
 )
BEGIN
    SELECT RAISE(ABORT, 'supersession requires an accepted revision for the same experiment and field');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_revision_retraction_requires_target
BEFORE INSERT ON review_revision
WHEN NEW.decision IN ('rejected', 'superseded')
 AND NEW.supersedes_review_revision_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'retraction requires a superseded review revision');
END;

CREATE TRIGGER IF NOT EXISTS trg_screening_event_excludes_import
AFTER INSERT ON screening_event
WHEN NEW.disposition IN ('exclude', 'screening_only')
BEGIN
    UPDATE paper
    SET screening_status = 'exclude',
        import_status = 'screening_only'
    WHERE paper_id = NEW.paper_id;
END;

INSERT OR IGNORE INTO schema_migration (version, name, applied_at)
VALUES (2, 'review_and_screening_integrity', '2026-08-06T01:00:00Z');
"""

SCREENING_TRIGGER_CLEANUP_SQL = """
DROP TRIGGER IF EXISTS trg_screening_only_not_ready;
DROP TRIGGER IF EXISTS trg_excluded_paper_not_ready_insert;
DROP TRIGGER IF EXISTS trg_excluded_paper_not_ready_update;
"""

SCREENING_STATE_SCHEMA_SQL = """
UPDATE paper
SET import_status = 'screening_only'
WHERE screening_status = 'exclude';

INSERT OR IGNORE INTO schema_migration (version, name, applied_at)
VALUES (3, 'screening_state_and_atomic_migration', '2026-08-06T02:00:00Z');
"""

REVIEW_ENTITY_SCHEMA_SQL = """
DROP TRIGGER IF EXISTS trg_review_revision_supersession_matches;
DROP TRIGGER IF EXISTS trg_review_revision_retraction_requires_target;
DROP TRIGGER IF EXISTS trg_review_revision_entity_ownership;
DROP TRIGGER IF EXISTS trg_missing_field_resolution_matches_insert;
DROP TRIGGER IF EXISTS trg_missing_field_resolution_matches_update;

CREATE TRIGGER trg_missing_field_resolution_matches_insert
BEFORE INSERT ON missing_field
WHEN NEW.resolved_by_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM review_revision AS revision
    WHERE revision.review_revision_id = NEW.resolved_by_review_revision_id
      AND (
          revision.field_name = NEW.field_name
          OR (revision.entity_type = 'outcome' AND NEW.field_name =
              'outcome:' || revision.entity_id || ':' || revision.field_name)
      )
      AND revision.decision = 'accepted'
      AND (
          (revision.entity_type IN ('arm', 'experiment')
           AND coalesce(revision.entity_id, revision.experiment_id) = NEW.experiment_id)
          OR (revision.entity_type = 'formulation' AND EXISTS (
              SELECT 1 FROM experiment
              WHERE experiment.experiment_id = NEW.experiment_id
                AND experiment.formulation_id = revision.entity_id
          ))
          OR (revision.entity_type = 'outcome' AND revision.experiment_id = NEW.experiment_id)
      )
 )
BEGIN
    SELECT RAISE(ABORT, 'missing field resolution requires matching entity and field');
END;

CREATE TRIGGER trg_missing_field_resolution_matches_update
BEFORE UPDATE OF experiment_id, field_name, resolved_by_review_revision_id
ON missing_field
WHEN NEW.resolved_by_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM review_revision AS revision
    WHERE revision.review_revision_id = NEW.resolved_by_review_revision_id
      AND (
          revision.field_name = NEW.field_name
          OR (revision.entity_type = 'outcome' AND NEW.field_name =
              'outcome:' || revision.entity_id || ':' || revision.field_name)
      )
      AND revision.decision = 'accepted'
      AND (
          (revision.entity_type IN ('arm', 'experiment')
           AND coalesce(revision.entity_id, revision.experiment_id) = NEW.experiment_id)
          OR (revision.entity_type = 'formulation' AND EXISTS (
              SELECT 1 FROM experiment
              WHERE experiment.experiment_id = NEW.experiment_id
                AND experiment.formulation_id = revision.entity_id
          ))
          OR (revision.entity_type = 'outcome' AND revision.experiment_id = NEW.experiment_id)
      )
 )
BEGIN
    SELECT RAISE(ABORT, 'missing field resolution requires matching entity and field');
END;

CREATE TRIGGER trg_review_revision_supersession_matches
BEFORE INSERT ON review_revision
WHEN NEW.supersedes_review_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM review_revision
    WHERE review_revision_id = NEW.supersedes_review_revision_id
      AND (
          entity_type = NEW.entity_type
          OR (entity_type IN ('arm', 'experiment') AND NEW.entity_type IN ('arm', 'experiment'))
      )
      AND coalesce(entity_id, experiment_id) = coalesce(NEW.entity_id, NEW.experiment_id)
      AND field_name = NEW.field_name
      AND decision = 'accepted'
 )
BEGIN
    SELECT RAISE(ABORT, 'supersession requires an accepted revision for the same entity and field');
END;

CREATE TRIGGER trg_review_revision_entity_ownership
BEFORE INSERT ON review_revision
WHEN NOT (
    (NEW.entity_type IN ('arm', 'experiment')
     AND coalesce(NEW.entity_id, NEW.experiment_id) = NEW.experiment_id)
    OR (NEW.entity_type = 'formulation' AND EXISTS (
        SELECT 1 FROM experiment
        WHERE experiment_id = NEW.experiment_id
          AND formulation_id = NEW.entity_id
    ))
    OR (NEW.entity_type = 'outcome' AND EXISTS (
        SELECT 1 FROM outcome
        WHERE outcome_id = NEW.entity_id
          AND experiment_id = NEW.experiment_id
    ))
)
BEGIN
    SELECT RAISE(ABORT, 'review revision entity must belong to the selected experiment');
END;

INSERT OR IGNORE INTO schema_migration (version, name, applied_at)
VALUES (4, 'entity_scoped_review_history', '2026-08-06T03:00:00Z');
"""

SCREENING_STATE_TRIGGER_SQL = {
    "trg_paper_screening_state_insert": """CREATE TRIGGER trg_paper_screening_state_insert
BEFORE INSERT ON paper
WHEN (
    NEW.screening_status = 'exclude'
    AND NEW.import_status != 'screening_only'
) OR (
    NEW.screening_status != 'exclude'
    AND NEW.import_status = 'screening_only'
)
BEGIN
    SELECT RAISE(
        ABORT,
        'screening exclusion requires screening_only import status'
    );
END""",
    "trg_paper_screening_state_update": """CREATE TRIGGER trg_paper_screening_state_update
BEFORE UPDATE OF screening_status, import_status ON paper
WHEN (
    NEW.screening_status = 'exclude'
    AND NEW.import_status != 'screening_only'
) OR (
    NEW.screening_status != 'exclude'
    AND NEW.import_status = 'screening_only'
)
BEGIN
    SELECT RAISE(
        ABORT,
        'screening exclusion requires screening_only import status'
    );
END""",
}


def _add_missing_columns(
    connection: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
) -> None:
    existing = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if not existing:
        raise sqlite3.OperationalError(f"required legacy table is missing: {table}")
    for column_name, declaration in columns.items():
        if column_name not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column_name} {declaration}"
            )


def _execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute one complete SQL statement at a time without implicit commits."""

    pending: list[str] = []
    for line in script.splitlines(keepends=True):
        pending.append(line)
        statement = "".join(pending)
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            pending.clear()
    if "".join(pending).strip():
        raise sqlite3.OperationalError("incomplete migration SQL statement")


def _normalized_schema_sql(sql: str) -> str:
    return " ".join(sql.rstrip(";\n ").split())


def _ensure_screening_state_triggers(
    connection: sqlite3.Connection,
) -> None:
    for name, definition in SCREENING_STATE_TRIGGER_SQL.items():
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            (name,),
        ).fetchone()
        if row is not None and _normalized_schema_sql(
            row[0]
        ) == _normalized_schema_sql(definition):
            continue
        quoted_name = name.replace('"', '""')
        connection.execute(f'DROP TRIGGER IF EXISTS "{quoted_name}"')
        connection.execute(definition)


def _chemical_component_needs_role_rebuild(
    connection: sqlite3.Connection,
) -> bool:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chemical_component'"
    ).fetchone()
    return row is not None and "'targeting_anchor'" not in (row[0] or "")


def _migrate_chemical_component_roles(connection: sqlite3.Connection) -> None:
    if not _chemical_component_needs_role_rebuild(connection):
        return
    columns = [
        row[1]
        for row in connection.execute("PRAGMA table_info(chemical_component)")
    ]
    expected = [
        "component_id",
        "formulation_id",
        "component_name_reported",
        "component_name_normalized",
        "component_role",
        "inchikey",
        "molar_percentage",
        "percentage_unit",
        "component_review_status",
        "identity_source",
        "identity_notes",
        "amount_value",
        "amount_unit",
        "amount_raw",
        "composition_position",
    ]
    if set(columns) != set(expected):
        raise RuntimeError(
            "chemical_component columns are not ready for the v6 role migration"
        )
    quoted = ", ".join(f'"{column}"' for column in expected)
    _execute_sql_script(connection, CHEMICAL_COMPONENT_V6_SQL)
    connection.execute(
        f"INSERT INTO chemical_component_v6 ({quoted}) "
        f"SELECT {quoted} FROM chemical_component"
    )
    connection.execute("DROP TABLE chemical_component")
    connection.execute(
        "ALTER TABLE chemical_component_v6 RENAME TO chemical_component"
    )


def migrate_database(connection: sqlite3.Connection) -> None:
    """Upgrade a legacy six-table database without replacing existing rows.

    The migration is purely local and additive. Repeated calls converge on the
    same schema and single migration-version record.
    """

    rebuild_cell_type = _experiment_needs_cell_type_rebuild(connection)
    if rebuild_cell_type and connection.in_transaction:
        raise RuntimeError("cell-type migration requires no active transaction")
    if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise RuntimeError(
            "SQLite foreign-key enforcement must be enabled before migration"
        )
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("foreign-key violations before migration")
    if rebuild_cell_type:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA legacy_alter_table = ON")
    savepoint = "working_evidence_database_migration"
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        if rebuild_cell_type:
            _migrate_experiment_cell_type(connection)
        _add_missing_columns(connection, "paper", PAPER_COLUMNS)
        _add_missing_columns(connection, "experiment", EXPERIMENT_COLUMNS)
        _add_missing_columns(connection, "formulation", FORMULATION_COLUMNS)
        _add_missing_columns(
            connection, "chemical_component", CHEMICAL_COMPONENT_COLUMNS
        )
        _migrate_chemical_component_roles(connection)
        _execute_sql_script(connection, ADDITIVE_SCHEMA_SQL)
        _add_missing_columns(
            connection,
            "review_revision",
            REVIEW_REVISION_COLUMNS,
        )
        _execute_sql_script(connection, INTEGRITY_SCHEMA_SQL)
        _execute_sql_script(connection, SCREENING_TRIGGER_CLEANUP_SQL)
        _ensure_screening_state_triggers(connection)
        _execute_sql_script(connection, SCREENING_STATE_SCHEMA_SQL)
        version_four_applied = connection.execute(
            "SELECT 1 FROM schema_migration WHERE version = 4"
        ).fetchone() is not None
        if not version_four_applied:
            connection.execute("DROP TRIGGER IF EXISTS trg_review_revision_no_update")
            _add_missing_columns(connection, "review_revision", REVIEW_REVISION_COLUMNS)
            connection.execute(
                """UPDATE review_revision
                   SET entity_type = CASE
                       WHEN field_name IN ('formulation_name', 'composition_raw')
                       THEN 'formulation' ELSE 'arm' END,
                       entity_id = CASE
                       WHEN field_name IN ('formulation_name', 'composition_raw')
                       THEN (SELECT formulation_id FROM experiment
                             WHERE experiment.experiment_id = review_revision.experiment_id)
                       ELSE experiment_id END,
                       review_action = coalesce(
                           CASE
                               WHEN reviewer_notes LIKE '[accept]%' THEN 'accept'
                               WHEN reviewer_notes LIKE '[correct]%' THEN 'correct'
                               WHEN reviewer_notes LIKE '[not_reported]%' THEN 'not_reported'
                               WHEN reviewer_notes LIKE '[reject]%' THEN 'reject'
                               WHEN reviewer_notes LIKE '[wrong_arm]%' THEN 'wrong_arm'
                               WHEN reviewer_notes LIKE '[unresolved]%' THEN 'unresolved'
                           END,
                           CASE
                               WHEN decision = 'accepted' AND coalesce(previous_value, '') = corrected_value
                               THEN 'accept'
                               WHEN decision = 'accepted' THEN 'correct'
                               ELSE 'reject'
                           END
                       ),
                       evidence_id = coalesce(
                           evidence_id,
                           (SELECT verification.evidence_id
                            FROM field_verification AS verification
                            WHERE verification.review_revision_id = review_revision.review_revision_id
                              AND verification.evidence_id IS NOT NULL
                            ORDER BY verification.field_verification_id DESC LIMIT 1)
                       )"""
            )
            connection.execute(
                """CREATE TRIGGER trg_review_revision_no_update
                   BEFORE UPDATE ON review_revision
                   BEGIN
                       SELECT RAISE(ABORT, 'review revisions are immutable');
                   END"""
            )
            _execute_sql_script(connection, REVIEW_ENTITY_SCHEMA_SQL)
        version_five_applied = connection.execute(
            "SELECT 1 FROM schema_migration WHERE version = 5"
        ).fetchone() is not None
        if not version_five_applied:
            connection.execute(
                """UPDATE field_verification
                   SET field_name = (
                       SELECT 'outcome:' || revision.entity_id || ':' || revision.field_name
                       FROM review_revision AS revision
                       WHERE revision.review_revision_id = field_verification.review_revision_id
                         AND revision.entity_type = 'outcome'
                   )
                   WHERE field_name NOT LIKE 'outcome:%'
                     AND EXISTS (
                       SELECT 1 FROM review_revision AS revision
                       WHERE revision.review_revision_id = field_verification.review_revision_id
                         AND revision.entity_type = 'outcome'
                     )"""
            )
            connection.execute(
                """UPDATE missing_field
                   SET field_name = (
                       SELECT 'outcome:' || revision.entity_id || ':' || revision.field_name
                       FROM review_revision AS revision
                       WHERE revision.experiment_id = missing_field.experiment_id
                         AND revision.entity_type = 'outcome'
                         AND revision.field_name = missing_field.field_name
                       ORDER BY revision.review_revision_id DESC LIMIT 1
                   )
                   WHERE field_name NOT LIKE 'outcome:%'
                     AND 1 = (
                       SELECT count(DISTINCT revision.entity_id)
                       FROM review_revision AS revision
                       WHERE revision.experiment_id = missing_field.experiment_id
                         AND revision.entity_type = 'outcome'
                         AND revision.field_name = missing_field.field_name
                     )"""
            )
            connection.execute(
                """UPDATE missing_field
                   SET field_name = 'outcome:ambiguous:' || field_name,
                       reason = 'ambiguous outcome ownership; ' || reason
                   WHERE field_name NOT LIKE 'outcome:%'
                     AND 1 < (
                       SELECT count(DISTINCT revision.entity_id)
                       FROM review_revision AS revision
                       WHERE revision.experiment_id = missing_field.experiment_id
                         AND revision.entity_type = 'outcome'
                         AND revision.field_name = missing_field.field_name
                     )"""
            )
            _execute_sql_script(connection, REVIEW_ENTITY_SCHEMA_SQL)
            connection.execute(
                """INSERT INTO schema_migration (version, name, applied_at)
                   VALUES (5, 'entity_review_trigger_repair', '2026-08-06T04:00:00Z')"""
            )
        _execute_sql_script(connection, LOSSLESS_FACT_SCHEMA_SQL)
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("foreign-key violations during migration")
    except BaseException:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        if rebuild_cell_type:
            connection.execute("PRAGMA legacy_alter_table = OFF")
            connection.execute("PRAGMA foreign_keys = ON")
        raise
    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
    if rebuild_cell_type:
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("foreign-key violations after cell-type migration")


def _experiment_needs_cell_type_rebuild(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'experiment'"
    ).fetchone()
    if row is None:
        return False
    cell_segment = row[0].split("cell_type", 1)[1].split("cell_source", 1)[0]
    return "CHECK" in cell_segment.upper() and "'not_reported'" not in cell_segment


def _migrate_experiment_cell_type(connection: sqlite3.Connection) -> None:
    """Allow explicit unknown/other targets without fabricating a liver cell type."""

    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'experiment'"
    ).fetchone()
    if row is None or not _experiment_needs_cell_type_rebuild(connection):
        return
    old_sql = row[0]
    new_sql, replacements = re.subn(
        r"('hsc')(\s*\))",
        r"\1,\n                'not_reported',\n                'other'\2",
        old_sql,
        count=1,
    )
    if replacements != 1:
        raise RuntimeError("unrecognized experiment cell_type constraint")
    columns = [row[1] for row in connection.execute("PRAGMA table_info(experiment)")]
    quoted = ", ".join(f'"{column}"' for column in columns)
    connection.execute("ALTER TABLE experiment RENAME TO experiment_cell_type_v1")
    connection.execute(new_sql)
    connection.execute(
        f"INSERT INTO experiment ({quoted}) SELECT {quoted} FROM experiment_cell_type_v1"
    )
    connection.execute("DROP TABLE experiment_cell_type_v1")
