# MVP Data Dictionary

## Paper table

Stores publication identity, retrieval information, and screening status.

- `paper_id`: Internal unique identifier for the paper.
- `pmid`: PubMed identifier, when available.
- `pmcid`: PubMed Central identifier, when available.
- `doi`: Digital Object Identifier, when available.
- `title`: Published article title.
- `authors`: Authors as reported by the publication database.
- `journal`: Journal name.
- `publication_year`: Year of publication.
- `source_type`: Source used to retrieve the record, such as PubMed or Europe PMC.
- `source_url`: Link to the source record or full text.
- `retrieval_date`: Date the record was retrieved.
- `search_query_id`: Identifier linking the paper to the search that found it.
- `full_text_status`: Whether usable full text is available.
- `screening_status`: `include`, `exclude`, or `manual_review`.
- `screening_reason`: Explanation for the screening decision.

## Formulation table

Stores one identifiable LNP formulation described in a paper.

- `formulation_id`: Internal unique identifier for the formulation.
- `paper_id`: Foreign key linking the formulation to its source paper.
- `formulation_name`: Name or label used for the formulation.
- `composition_raw`: Exact formulation description reported by the paper.
- `composition_basis`: Basis of the composition, such as `mol%`, `weight%`, or molar ratio.
- `np_ratio`: Reported nitrogen-to-phosphate ratio.
- `formulation_notes`: Optional information that cannot be represented in structured fields.
- `formulation_review_status`: Review status of the formulation record.

## Chemical component table

Stores the individual chemical components belonging to a formulation.

- `component_id`: Internal unique identifier for the component record.
- `formulation_id`: Foreign key linking the component to its formulation.
- `component_name_reported`: Exact component name used by the paper.
- `component_name_normalized`: Standardized component name used by the application.
- `component_role`: Role such as ionizable lipid, helper lipid, cholesterol, PEG lipid, targeting ligand, or SORT lipid.
- `inchikey`: Optional verified chemical identifier used for matching and deduplication.
- `molar_percentage`: Reported molar percentage, when available.
- `percentage_unit`: Unit or composition basis associated with the percentage.
- `component_review_status`: Status of chemical-identity review.
- `identity_source`: Source used to verify the normalized name or InChIKey.
- `identity_notes`: Explanation of ambiguous or conflicting chemical identities.

## Experiment table

Stores the biological and experimental context in which a formulation was tested.

- `experiment_id`: Internal unique identifier for the experiment.
- `paper_id`: Foreign key linking the experiment to its source paper.
- `formulation_id`: Foreign key linking the experiment to the tested formulation.
- `cell_type`: One of the four controlled liver-cell types.
- `cell_source`: Primary cell, cell line, isolated cell, or other reported source.
- `species`: Species used in the experiment.
- `in_vitro_in_vivo`: Experimental setting.
- `payload_type`: Payload category, such as mRNA, siRNA, or gene editor.
- `payload_name`: Specific payload or construct, when reported.
- `reporter`: Reporter system, such as luciferase or GFP.
- `dose`: Reported dose.
- `dose_unit`: Unit associated with the dose.
- `route`: Administration route, when applicable.
- `timepoint`: Time between treatment and measurement.
- `timepoint_unit`: Unit associated with the timepoint.
- `assay`: Method used to measure the outcome.
- `comparator_type`: Controlled comparator category.
- `comparator_description`: Exact description of the control or reference.
- `protocol_reference`: Optional reference to the paper’s Methods section or a published protocol.
- `experiment_notes`: Optional experimental details that do not fit another field.

## Outcome table

Stores each measured or reported result as a separate record.

- `outcome_id`: Internal unique identifier for the outcome.
- `experiment_id`: Foreign key linking the outcome to its experiment.
- `endpoint_family`: Broad category such as expression, uptake, knockdown, viability, or toxicity.
- `endpoint_name`: Specific measurement reported by the paper.
- `outcome_value`: Numerical value, when reported.
- `outcome_unit`: Unit or reporting basis associated with the value.
- `normalization_basis`: Comparator or reference used to normalize the value.
- `uncertainty_value`: Reported uncertainty, when available.
- `uncertainty_type`: Type of uncertainty, such as SD, SEM, or confidence interval.
- `qualitative_outcome`: Reported qualitative result when no reliable number is available.
- `value_status`: `reported`, `normalized`, `derived`, `qualitative_only`, or `missing`.
- `outcome_notes`: Optional qualification of the outcome.

## Evidence table

Stores the exact evidence supporting an extracted field or outcome.

- `evidence_id`: Internal unique identifier for the evidence record.
- `paper_id`: Foreign key linking the evidence to its paper.
- `experiment_id`: Optional foreign key linking the evidence to an experiment.
- `outcome_id`: Optional foreign key linking the evidence to an outcome.
- `field_name`: Name of the field supported by the evidence.
- `evidence_text`: Exact supporting excerpt or structured table text.
- `evidence_location_type`: Abstract, Results, Methods, table, figure, caption, or supplement.
- `section_name`: Paper section containing the evidence.
- `page_number`: PDF page containing the evidence.
- `table_number`: Table identifier, when applicable.
- `figure_number`: Figure identifier, when applicable.
- `supplement_identifier`: Supplementary file or section identifier.
- `extraction_method`: Text extraction, structured-table parsing, OCR, vision extraction, manual transcription, or figure digitization.
- `extraction_confidence`: Confidence calculated from evidence coverage and ambiguity.
- `evidence_review_status`: Review state of the extracted evidence.
- `reviewer_notes`: Explanation of corrections or unresolved concerns.

# Controlled Values

## Cell types

- `hepatocyte`
- `kupffer_cell`
- `lsec`
- `hsc`

## Component roles

- `ionizable_lipid`
- `helper_lipid`
- `cholesterol`
- `peg_lipid`
- `targeting_ligand`
- `sort_lipid`
- `other`

## Endpoint families

- `uptake`
- `functional_expression`
- `transfection`
- `gene_knockdown`
- `cre_recombination`
- `viability`
- `toxicity`
- `biodistribution`
- `therapeutic_effect`
- `other`

## Value statuses

- `reported`
- `normalized`
- `derived`
- `qualitative_only`
- `missing`

## Screening statuses

- `include`
- `exclude`
- `manual_review`

## Review statuses

- `unreviewed`
- `automatically_normalized`
- `manually_verified`
- `ambiguous`
- `conflict`
- `rejected`

## Deferred or excluded fields

- canonical_smiles: deferred from the required MVP schema
- zeta_potential: excluded
- viability_value: use outcome_value
- viability_unit: use outcome_unit
- outcome_direction: not stored for ordinary numeric outcomes
- protocol_version: use the optional protocol_reference
- COMET prediction fields: kept in a separate model-output schema and enabled
  only for a registered cell/task that passes the Track B model gates

## Viability representation

Viability is stored as an ordinary outcome row.

Example:

- endpoint_family: viability
- endpoint_name: AlamarBlue metabolic activity
- outcome_value: 87
- outcome_unit: % of untreated control
- normalization_basis: untreated cells
- value_status: reported

The efficacy result from the same experiment is stored as a separate outcome
row connected through the same experiment_id.

## Demonstration record

The initial database contains one synthetic demonstration record used to test:

- paper-to-formulation relationships;
- one formulation with multiple components;
- formulation-to-experiment relationships;
- separate efficacy and viability outcomes;
- outcome-specific evidence; and
- composition-total validation.

The demonstration record is not scientific evidence and must not be displayed
as a literature-supported result in the final application.
