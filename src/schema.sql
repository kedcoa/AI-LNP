PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS paper (
    paper_id INTEGER PRIMARY KEY,
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
    screening_reason TEXT
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
