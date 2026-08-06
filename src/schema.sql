PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS paper (
    paper_id INTEGER PRIMARY KEY,
    source_paper_id TEXT UNIQUE,
    pmid TEXT UNIQUE,
    pmcid TEXT UNIQUE,
    doi TEXT UNIQUE,
    title TEXT NOT NULL,
    authors TEXT,
    journal TEXT,
    publication_year INTEGER,
    source_type TEXT NOT NULL,
    source_url TEXT,
    retrieval_date TEXT NOT NULL,
    search_query_id TEXT,
    full_text_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (
            full_text_status IN (
                'unknown',
                'abstract_only',
                'open_full_text',
                'pdf_available',
                'unavailable'
            )
        ),
    screening_status TEXT NOT NULL DEFAULT 'manual_review'
        CHECK (
            screening_status IN (
                'include',
                'exclude',
                'manual_review'
            )
        ),
    screening_reason TEXT,
    import_status TEXT NOT NULL DEFAULT 'needs_review'
        CHECK (
            import_status IN (
                'ready',
                'ready_with_missing_fields',
                'needs_review',
                'blocked',
                'screening_only'
            )
        )
);

CREATE TABLE IF NOT EXISTS formulation (
    formulation_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    formulation_name TEXT,
    composition_raw TEXT,
    composition_basis TEXT
        CHECK (
            composition_basis IS NULL
            OR composition_basis IN (
                'mol%',
                'weight%',
                'molar_ratio',
                'mass_ratio',
                'not_reported',
                'other'
            )
        ),
    np_ratio REAL,
    formulation_notes TEXT,
    formulation_review_status TEXT NOT NULL DEFAULT 'unreviewed',
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS chemical_component (
    component_id INTEGER PRIMARY KEY,
    formulation_id INTEGER NOT NULL,
    component_name_reported TEXT NOT NULL,
    component_name_normalized TEXT,
    component_role TEXT NOT NULL
        CHECK (
            component_role IN (
                'ionizable_lipid',
                'helper_lipid',
                'cholesterol',
                'peg_lipid',
                'targeting_ligand',
                'sort_lipid',
                'other'
            )
        ),
    inchikey TEXT,
    molar_percentage REAL
        CHECK (
            molar_percentage IS NULL
            OR (
                molar_percentage >= 0
                AND molar_percentage <= 100
            )
        ),
    percentage_unit TEXT,
    component_review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (
            component_review_status IN (
                'unreviewed',
                'automatically_normalized',
                'manually_verified',
                'ambiguous',
                'conflict',
                'rejected'
            )
        ),
    identity_source TEXT,
    identity_notes TEXT,
    FOREIGN KEY (formulation_id) REFERENCES formulation(formulation_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS experiment (
    experiment_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    formulation_id INTEGER NOT NULL,
    cell_type TEXT NOT NULL
        CHECK (
            cell_type IN (
                'hepatocyte',
                'kupffer_cell',
                'lsec',
                'hsc'
            )
    ),
    cell_source TEXT,
    tissue_or_organ TEXT,
    species TEXT,
    disease_model TEXT,
    in_vitro_in_vivo TEXT
        CHECK (
            in_vitro_in_vivo IS NULL
            OR in_vitro_in_vivo IN (
                'in_vitro',
                'ex_vivo',
                'in_vivo',
                'not_reported'
            )
        ),
    payload_type TEXT,
    payload_name TEXT,
    payload_encoded_product TEXT,
    payload_molecular_target TEXT,
    reporter TEXT,
    dose REAL,
    dose_unit TEXT,
    route TEXT,
    timepoint REAL,
    timepoint_unit TEXT,
    assay TEXT,
    comparator_type TEXT,
    comparator_description TEXT,
    protocol_reference TEXT,
    experiment_notes TEXT,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (formulation_id) REFERENCES formulation(formulation_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS outcome (
    outcome_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    endpoint_family TEXT NOT NULL
        CHECK (
            endpoint_family IN (
                'uptake',
                'functional_expression',
                'transfection',
                'gene_knockdown',
                'cre_recombination',
                'viability',
                'toxicity',
                'biodistribution',
                'therapeutic_effect',
                'other'
            )
        ),
    endpoint_name TEXT NOT NULL,
    outcome_value REAL,
    outcome_unit TEXT,
    normalization_basis TEXT,
    uncertainty_value REAL,
    uncertainty_type TEXT
        CHECK (
            uncertainty_type IS NULL
            OR uncertainty_type IN (
                'sd',
                'sem',
                'confidence_interval',
                'range',
                'other'
            )
        ),
    qualitative_outcome TEXT,
    value_status TEXT NOT NULL
        CHECK (
            value_status IN (
                'reported',
                'normalized',
                'derived',
                'qualitative_only',
                'missing'
            )
        ),
    outcome_notes TEXT,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CHECK (
        outcome_value IS NOT NULL
        OR qualitative_outcome IS NOT NULL
        OR value_status = 'missing'
    )
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    experiment_id INTEGER,
    outcome_id INTEGER,
    field_name TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    evidence_location_type TEXT NOT NULL
        CHECK (
            evidence_location_type IN (
                'abstract',
                'results',
                'methods',
                'table',
                'figure',
                'figure_caption',
                'supplement',
                'other'
            )
        ),
    section_name TEXT,
    page_number TEXT,
    table_number TEXT,
    figure_number TEXT,
    supplement_identifier TEXT,
    extraction_method TEXT NOT NULL
        CHECK (
            extraction_method IN (
                'manual',
                'text_extraction',
                'structured_table',
                'ocr',
                'vision',
                'figure_digitization'
            )
        ),
    extraction_confidence TEXT NOT NULL
        CHECK (
            extraction_confidence IN (
                'high',
                'medium',
                'low'
            )
        ),
    evidence_review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (
            evidence_review_status IN (
                'unreviewed',
                'manually_verified',
                'ambiguous',
                'conflict',
                'rejected'
            )
        ),
    reviewer_notes TEXT,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (outcome_id) REFERENCES outcome(outcome_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_paper_screening
    ON paper(screening_status);

CREATE INDEX IF NOT EXISTS idx_component_formulation
    ON chemical_component(formulation_id);

CREATE INDEX IF NOT EXISTS idx_component_inchikey
    ON chemical_component(inchikey);

CREATE INDEX IF NOT EXISTS idx_experiment_cell
    ON experiment(cell_type);

CREATE INDEX IF NOT EXISTS idx_experiment_formulation
    ON experiment(formulation_id);

CREATE INDEX IF NOT EXISTS idx_outcome_experiment
    ON outcome(experiment_id);

CREATE INDEX IF NOT EXISTS idx_outcome_endpoint
    ON outcome(endpoint_family);

CREATE INDEX IF NOT EXISTS idx_evidence_outcome
    ON evidence(outcome_id);

CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS record_source (
    record_source_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL
        CHECK (
            entity_type IN (
                'paper',
                'formulation',
                'chemical_component',
                'experiment',
                'outcome',
                'evidence'
            )
        ),
    entity_id INTEGER,
    artifact_path TEXT NOT NULL CHECK (length(trim(artifact_path)) > 0),
    artifact_sha256 TEXT NOT NULL
        CHECK (length(artifact_sha256) = 64),
    pipeline_name TEXT NOT NULL CHECK (length(trim(pipeline_name)) > 0),
    pipeline_version TEXT,
    extraction_run_identifier TEXT,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS review_revision (
    review_revision_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'experiment',
    entity_id INTEGER,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    previous_value TEXT,
    corrected_value TEXT NOT NULL CHECK (length(trim(corrected_value)) > 0),
    evidence_excerpt TEXT NOT NULL CHECK (length(trim(evidence_excerpt)) > 0),
    evidence_location_type TEXT,
    evidence_location TEXT NOT NULL CHECK (length(trim(evidence_location)) > 0),
    reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
    decision TEXT NOT NULL DEFAULT 'accepted'
        CHECK (decision IN ('accepted', 'rejected', 'superseded')),
    reviewer_notes TEXT,
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS missing_field (
    missing_field_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    recorded_at TEXT NOT NULL,
    resolved_by_review_revision_id INTEGER,
    resolved_at TEXT,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (resolved_by_review_revision_id)
        REFERENCES review_revision(review_revision_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CHECK (
        (resolved_by_review_revision_id IS NULL AND resolved_at IS NULL)
        OR
        (resolved_by_review_revision_id IS NOT NULL AND resolved_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS field_verification (
    field_verification_id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL,
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    evidence_id INTEGER,
    review_revision_id INTEGER,
    verification_status TEXT NOT NULL
        CHECK (
            verification_status IN (
                'unreviewed',
                'automatically_validated',
                'manually_verified',
                'ambiguous',
                'conflict',
                'rejected'
            )
        ),
    notes TEXT,
    verified_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (review_revision_id)
        REFERENCES review_revision(review_revision_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS arm_assessment (
    experiment_id INTEGER PRIMARY KEY,
    completeness_status TEXT NOT NULL
        CHECK (
            completeness_status IN (
                'complete',
                'incomplete',
                'conflict',
                'quarantined'
            )
        ),
    missing_fields_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(missing_fields_json)),
    verification_status TEXT NOT NULL
        CHECK (
            verification_status IN (
                'unreviewed',
                'automatically_validated',
                'manually_verified',
                'ambiguous',
                'conflict',
                'rejected'
            )
        ),
    nearest_neighbor_eligible INTEGER NOT NULL DEFAULT 0
        CHECK (nearest_neighbor_eligible IN (0, 1)),
    comet_eligible INTEGER NOT NULL DEFAULT 0
        CHECK (comet_eligible IN (0, 1)),
    quarantine_reason TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CHECK (
        completeness_status != 'quarantined'
        OR length(trim(quarantine_reason)) > 0
    )
);

CREATE TABLE IF NOT EXISTS screening_event (
    screening_event_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    disposition TEXT NOT NULL
        CHECK (
            disposition IN (
                'include',
                'exclude',
                'manual_review',
                'screening_only'
            )
        ),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    search_query_id TEXT,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS eligibility_result (
    experiment_id INTEGER NOT NULL,
    profile TEXT NOT NULL
        CHECK (profile IN ('nearest_neighbor', 'comet')),
    eligible INTEGER NOT NULL CHECK (eligible IN (0, 1)),
    reasons_json TEXT NOT NULL CHECK (json_valid(reasons_json)),
    rules_version TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY (experiment_id, profile),
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_record_source_paper
    ON record_source(paper_id);

CREATE INDEX IF NOT EXISTS idx_missing_field_experiment
    ON missing_field(experiment_id);

CREATE INDEX IF NOT EXISTS idx_field_verification_experiment
    ON field_verification(experiment_id);

CREATE INDEX IF NOT EXISTS idx_review_revision_experiment
    ON review_revision(experiment_id);

CREATE INDEX IF NOT EXISTS idx_screening_event_paper
    ON screening_event(paper_id);
