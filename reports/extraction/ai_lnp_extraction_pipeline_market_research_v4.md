# AI-LNP extraction pipeline: market research and v4 design

Date: 2026-07-23

## Executive decision

Do not continue the sentence-scoped v3 pipeline. Replace it with an **evidence-graph-first pipeline** that:

1. parses full papers into structured, location-addressable blocks;
2. identifies atomic experimental claims and their relations before populating database fields;
3. asks one narrow extraction question at a time;
4. validates every field against exact source spans and domain rules;
5. automatically repairs clear errors;
6. sends humans only unresolved alternatives;
7. selects models through a blinded benchmark rather than vendor preference.

No LLM pipeline can guarantee zero errors. The attainable goal is that unsupported or cross-experiment values fail closed and never enter the accepted dataset.

## What established tools teach us

| System or practice | Useful design pattern | AI-LNP implication |
|---|---|---|
| [GROBID](https://grobid.readthedocs.io/en/latest/Principles/) | Converts scientific PDFs into structured TEI with sections, paragraphs, figures, tables, formulas, and references. | Preserve paper structure instead of flattening a PDF into one text string. |
| [Docling](https://docling-project.github.io/docling/concepts/docling_document/) | Retains hierarchy, reading order, bounding boxes, tables, pictures, and provenance. | Every evidence span should retain page, block, table/figure, and character offsets. |
| [PubTator 3.0](https://pmc.ncbi.nlm.nih.gov/articles/PMC11223843/) | Separates biomedical entity recognition from relation extraction and exports standardized BioC annotations. | Detect chemicals, genes, diseases, species, cells, and relations before asking for LNP-specific records. |
| [Trialstreamer](https://pmc.ncbi.nlm.nih.gov/articles/PMC8204713/) | Uses a pipeline of specialized models for study identification, PICO elements, outcomes, and relations rather than one universal prompt. | Use separate formulation, experiment, biological-entity, and outcome extractors with explicit links. |
| [RobotReviewer](https://pmc.ncbi.nlm.nih.gov/articles/PMC5662138/) | Produces decisions together with supporting text and is designed as semi-automation. | A field is not accepted without a source span; uncertain judgments remain reviewable. |
| [Elicit evaluation](https://elicit.com/blog/how-we-evaluated-elicit-systematic-review) | Evaluates extraction against vetted gold answers and the paper text; shows supporting quotations and explanations. | Score AI-LNP against frozen human gold at the field and relation levels, not merely JSON validity. Vendor-reported accuracy should be treated as a claim, not independent proof. |
| [Covidence data-extraction guidance](https://www.covidence.org/blog/how-to-extract-study-data-for-your-systematic-review/) | Predefines extraction forms and conflict-resolution procedures and preserves reviewer disagreements. | Freeze field definitions, allowed values, and adjudication rules before evaluation; keep an audit trail. |
| [LNP Atlas](https://pmc.ncbi.nlm.nih.gov/articles/PMC12858976/) | Uses full text, a standardized JSON template, automated consistency checks, cross-referencing, and expert review for LNP formulation curation. | Abstract-only extraction is insufficient for composition; require full text and tables for formulation completeness. |
| [LNPDB](https://pmc.ncbi.nlm.nih.gov/articles/PMC12992592/) | Separates publication, formulation, experiment, composition, performance, and simulation features, including named lipid roles and ratios. | Adopt separate formulation, component, experiment, measurement, and outcome entities rather than one overloaded record. |
| [NanoParticle Ontology](https://pmc.ncbi.nlm.nih.gov/articles/PMC3042056/) and [nanomedicine informatics guidance](https://pmc.ncbi.nlm.nih.gov/articles/PMC3189420/) | Uses controlled concepts for nanoparticle composition, preparation, characterization, chemical roles, anatomy, and biological effects. | Normalize only after preserving reported text; use ChEBI/NPO/anatomy identifiers with explicit mappings. |

## Why v3 failed

The main failure was architectural, not simply model intelligence:

- A full sentence was treated as the smallest evidence unit even when it described several experiments.
- The same sentence was copied into multiple experiment prompts, allowing facts to leak between clauses.
- Human-authored boundary labels were supplied as if they were source evidence.
- The extractor generated many related fields simultaneously, so one mistaken interpretation propagated across the record.
- The verifier described corrections but the pipeline did not apply and revalidate them.
- Confidence was model-reported rather than calibrated from observed performance.
- Abstract-only input could not recover formulation details found in methods, tables, or supplements.

SenseNova also caused operational problems—429 limits, inconsistent JSON behavior, skipped required metadata, and variable reasoning—but changing providers alone would not repair the context and data-model defects.

## Proposed v4 architecture

### Layer 1: source acquisition and source quality

- Prefer publisher XML or PMC XML.
- Otherwise parse the PDF with GROBID and Docling independently.
- Reconcile reading order and tables; flag disagreements.
- Store immutable source blocks with:
  - `document_id`
  - `section_path`
  - `page`
  - `block_id`
  - `sentence_id`
  - `clause_id`
  - exact character offsets
  - bounding box
  - parser and parser confidence
- Track source availability: abstract only, main full text, supplement, or complete package.
- Do not score missing composition as an extraction failure when the required full text/table is unavailable; classify it as `source_unavailable`.

### Layer 2: atomic claim segmentation

Split sentences into minimal clauses without rewriting them. Each clause represents one predicate and its arguments.

Example:

> “mRNA-LNPs transfect hepatocytes in healthy, fibrotic, and cirrhotic liver and also tumor cells in HCC.”

becomes four source-preserving claims:

- transfects(mRNA-LNP, hepatocytes, healthy liver)
- transfects(mRNA-LNP, hepatocytes, fibrotic liver)
- transfects(mRNA-LNP, hepatocytes, cirrhotic liver)
- transfects(mRNA-LNP, tumor cells, HCC)

Each claim points to exact, possibly discontinuous, character spans. No experiment receives unrelated sibling clauses.

### Layer 3: entity registry

Create canonical paper-local entities before experiments:

- delivery system/formulation
- formulation material/component
- payload
- encoded product
- molecular target
- targeting ligand
- cell
- tissue/organ
- disease/pathology
- species/model
- intervention
- assay
- endpoint

Every entity stores:

- exact reported name;
- normalized label;
- ontology/database identifier when confidently mapped;
- evidence spans;
- mapping status: exact, synonym, inferred, or unresolved.

Rules:

- payload can never be an LNP component;
- healthy is a physiological state, never a disease;
- tissue, tumor, protein, and gene cannot occupy a cell field;
- reported text and normalized concept are separate;
- unresolved normalization does not erase the source value.

### Layer 4: relation and event graph

Build experiment events from relations, not prose summaries:

```text
Experiment
  uses_formulation -> Formulation
  carries_payload -> Payload
  administered_to -> BiologicalModel
  delivery_recipient -> CellEntity
  therapeutic_target -> CellEntity or MolecularTarget
  disease_context -> Disease
  tissue_context -> Tissue
  has_intervention -> Intervention
  measured_by -> Assay
  produces -> Outcome
```

An experiment is split only when a treatment, formulation, model, disease context, dose, route, timepoint, comparator arm, or measurement condition actually differs. Shared facts are linked once rather than copied as uncontrolled text.

### Layer 5: field-by-field extraction

For each field:

1. retrieve only eligible source clauses and linked table cells;
2. ask a narrowly worded question with positive and negative examples;
3. return one of:
   - `reported`
   - `not_reported`
   - `conflicting_reports`
   - `source_unavailable`
4. require exact span IDs;
5. forbid free-form evidence strings not anchored to stored offsets.

Multi-valued facts use arrays. A field is never forced to choose one payload when the experiment explicitly uses mRNA and siRNA.

### Layer 6: deterministic validation

Reject records automatically when:

- evidence offsets do not reproduce the quoted text;
- evidence is outside the experiment's claim subgraph;
- a field violates entity type constraints;
- a numeric value lacks a compatible unit;
- component percentages violate the stated basis or expected total;
- an outcome merges distinct predicates;
- a reference points to a nonexistent entity;
- the same clause produces contradictory roles without an explicit explanation;
- normalized values are more specific than the source;
- an abstract-only record claims full formulation completeness.

### Layer 7: adversarial verification and automatic repair

Use a second model family with no access to the first model's reasoning. Give it:

- source claim graph;
- proposed field value;
- exact evidence;
- field definition and counterexamples.

The verifier must choose:

- supported;
- unsupported;
- incomplete;
- wrong entity/experiment;
- genuinely ambiguous.

For unsupported, incomplete, or wrong-link findings, a repair stage proposes a replacement. The repaired value then passes the deterministic validator and a fresh verifier. Humans never review an error already agreed upon by machines and rules.

### Layer 8: calibrated confidence

Do not use the LLM's self-reported confidence. Compute confidence from:

- empirical precision for this field/model on frozen gold;
- agreement between independent extractors;
- verifier agreement;
- exact-span validation;
- parser/source quality;
- ontology mapping certainty;
- whether evidence comes from abstract, body, table, figure, or supplement.

Only accept automatically when the calibrated lower confidence bound meets the required precision. Otherwise abstain.

### Layer 9: minimal human adjudication

The reviewer sees only genuine unresolved alternatives:

- exact question and field definition;
- experiment ID and concise experiment structure;
- candidate A and candidate B;
- complete source clause plus surrounding paragraph;
- page/table location;
- why rules and models could not resolve it.

The reviewer does not see raw schema errors, duplicate warnings, or already-correct verifier findings.

## Model and provider evaluation

SenseNova should be treated as one candidate, not the default.

Run the same blinded tasks on at least:

- the current SenseNova extractor/verifier models;
- one strong general model from another provider;
- one biomedical or scientific model if its structured-output performance is adequate;
- deterministic biomedical NER/normalization tools such as PubTator as supporting components.

Measure separately:

- entity precision/recall;
- relation precision/recall;
- experiment-link accuracy;
- exact evidence-span precision;
- field-level precision/recall;
- abstention quality;
- invalid response rate;
- latency and cost;
- rate-limit/retry frequency.

Choose the best model per task. The best parser, entity recognizer, relation extractor, verifier, and repairer need not be the same model or provider.

## Release gates

Do not rerun G1 until:

1. field definitions and entity types are frozen;
2. full-text source availability is classified;
3. clause-level evidence spans are frozen;
4. at least two human annotators independently annotate a calibration subset;
5. disagreements are adjudicated into gold;
6. every critical field has enough positive and negative examples;
7. the pipeline passes synthetic leakage tests;
8. exact evidence-span precision is 100%;
9. critical-field precision is at least 90%, with a reported confidence interval;
10. no accepted record contains a blocking deterministic or verifier issue.

## Recommended implementation sequence

1. Freeze and document v4 ontology and field definitions.
2. Add full-text/XML/PDF ingestion with provenance.
3. Implement clause/span IDs and shared-fact representation.
4. Build the paper-local entity registry.
5. Build relation/event graph generation.
6. Add one-field-at-a-time extraction.
7. Add deterministic type, linkage, unit, and provenance validation.
8. Add verifier-repair-reverify loop.
9. Create a blinded model bake-off on the existing gold papers plus adversarial examples.
10. Generate a new review only for remaining calibrated ambiguities.

## Bottom line

The replacement is not “a better prompt” and not “read it three times.” It is a provenance-preserving scientific information-extraction system in which LLMs propose typed claims, deterministic code enforces invariants, independent models verify and repair, and humans adjudicate only irreducible ambiguity.
