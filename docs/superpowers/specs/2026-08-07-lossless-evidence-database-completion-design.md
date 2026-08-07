# Lossless Evidence Database Completion Design

**Date:** 2026-08-07

**Status:** Approved through user critique and clarification

**Objective:** Rebuild the current-corpus SQLite database so every approved JSON fact and evidence item is represented, repeated normalized science is deduplicated without losing provenance, necessary selective reruns are merged, and an honest final report gives the actual usable counts.

## 1. Scope

This work covers the existing 14-paper corpus only:

- GP-001 through GP-009;
- NP-001 and NP-002;
- PILOT-001 through PILOT-003.

GP-001, GP-003, and GP-009 remain screening-only. The remaining papers are evidence-import candidates. New-paper discovery and screening are explicitly excluded; they begin in a separate afternoon workflow only after the current database is frozen.

## 2. Existing database and manifest

The authoritative path remains `data/curated/lnp_evidence.db`. Work is performed against a fresh temporary rebuild and promotes that file only after every verification gate passes. The previous database is retained as a timestamped backup with a SHA-256 hash.

The existing `config/database/current_corpus_v1.json` remains the corpus manifest. It is extended rather than replaced. A paper no longer has only one effective input. Each entry records:

- a primary extraction artifact;
- every contributing extraction, repair, reconciliation, vision, annotation, and validation artifact;
- every source XML, HTML, PDF, supplement, spreadsheet, or evidence packet needed by those artifacts;
- artifact path, SHA-256, schema family, role, validation status, and import status;
- source-fact and evidence counts before and after import;
- rerun status, bounded scope, request hashes, and returned artifact paths.

The original JSON files remain local source artifacts. SQLite does not need a second complete copy of every file. It stores immutable paths, hashes, JSON paths, raw fact values, provenance, and projection status so every database value can be traced back to the exact source bytes.

## 3. Losslessness rule

Every labeled record from every approved contributing artifact must end in exactly one visible accounting state:

1. projected into a normalized scientific field;
2. preserved as a source fact awaiting review;
3. quarantined because its relationship is unsafe;
4. rejected with a specific reason.

Silent omission is forbidden. For every artifact:

`source facts = projected facts + unresolved facts + quarantined facts + rejected facts`

Every source evidence identifier must resolve to one canonical SQLite evidence row or an explicit rejected-evidence record. The rebuild fails when either equality does not hold.

## 4. Data layers

### 4.1 Artifact layer

One row represents one immutable input file and records its paper, logical path, SHA-256, artifact role, schema family, pipeline/version, validation status, and whether it contributes facts or evidence.

### 4.2 Source-fact layer

One row represents one labeled fact occurrence in a source JSON. It records:

- artifact and JSON path;
- source record key and record kind;
- paper and source experiment/candidate identity;
- subject type and source subject key;
- field or predicate;
- raw value as JSON;
- supplied canonical value as JSON, when present;
- source evidence identifiers;
- import disposition and reason.

Repeated source occurrences remain visible here for auditability.

### 4.3 Canonical scientific layer

The existing paper, formulation, component, experiment, outcome, and evidence tables remain the application-facing representation. Canonical facts and evidence are deduplicated here. Many source facts may project to one normalized value, and one canonical evidence row may support many fields.

### 4.4 Projection layer

Every source fact links to the normalized entity, field, and canonical fact it produced. Facts that are not projected retain a review, quarantine, or rejection reason. This layer proves that conversion did not discard data.

## 5. Three source schemas

### 5.1 GP accepted graphs

Import every entity, claim, predicate, experiment, claim membership, boundary status, and evidence item. Known predicates project into normalized fields. Unknown predicates remain queryable source facts rather than being dropped. An experiment without a safe formulation relationship remains a quarantined experiment/fact group instead of disappearing.

### 5.2 NP compact results

Import every evidence-linked field from formulations, components, experiments, and outcomes. Import every unresolved item as a review fact. NP-002's three cell-scoped results all contribute; they are reconciled by stable scientific identity and never treated as competing whole-paper winners.

### 5.3 PILOT consolidated results

Import every shared fact and experiment fact, including dotted fields such as `outcome.OUT-1.endpoint`. Failed formal acceptance sets quarantine/review status but does not erase experiments, outcomes, or facts. Source recovery and validation determine promotion to accepted scientific rows.

## 6. Formulation model and counting

Formulation name, composition, and payload are separate concepts.

- **Formulation name:** reported and normalized product/formulation label, such as `alpha-CD163/LNP-FAPCAR`.
- **Composition:** components, component roles, reported amounts, units, ratio basis, targeting anchors, and surface ligands.
- **Payload:** mRNA/siRNA identity and encoded product, stored on the experimental arm rather than as a lipid component.

Named formulation variants may share one chemical composition. Final reporting therefore gives both:

- named formulation records; and
- unique chemical compositions based on a deterministic composition fingerprint.

The fingerprint uses sorted normalized component identity, role, amount, unit, ratio basis, and composition-defining surface modifications. Unknown values remain explicit. Records are not merged merely because both are called `LNP`.

## 7. Deduplication

Import precedes deduplication.

A canonical evidence identity is based on paper, source artifact hash, source locator, normalized excerpt or structured evidence, and modality. Identical text at different source locations remains distinct provenance. One canonical evidence row may support several facts.

A canonical fact identity is based on paper, normalized subject/context, field, normalized value, and scientific arm/formulation/outcome ownership. Two conflicting values are retained as a conflict, not deduplicated.

Repeated NP-002 component rows collapse to one formulation-component row while retaining links to all three source slices. Source-fact occurrences remain available for audit, while final counts use deduplicated canonical facts and evidence.

## 8. Existing local evidence closure

Before any rerun, all local artifacts are re-imported and checked. In particular:

- GP-002 restores the supported SM-102:DSPC:cholesterol:DMG-PEG2000 `50:10:38.5:1.5` composition;
- GP-008 restores the supplement-supported `45:30:23.5:1.5` base ratio, ionizable-lipid identity, DSPE-PEG-maleimide anchor, anti-CD163 ligand, and reported antibody:LNP ratio;
- NP-002 reconciles its three validated cell-scoped result files and removes repeated normalized components;
- PILOT source facts enter the ledger even when they remain quarantined.

Only gaps remaining after this closure may create rerun requests.

## 9. Supplement handling for the current corpus

Supplement processing is generalized from the original nine-paper loop to accept any paper entry in the current-corpus manifest. It does not start new-paper screening.

Acquisition order is:

1. inspect existing local directories and package manifests;
2. inspect downloaded XML/HTML for declared supplementary assets;
3. use PMC and Europe PMC linked-asset/package endpoints;
4. use an interactive publisher-page fallback only when a JavaScript-rendered page hides the lawful link;
5. record path, URL, hash, retrieval method, and access status.

Only scientific supplementary assets are fetched, not every hyperlink. Text PDFs use PyMuPDF, complex tables use Docling, image-only tables/figures use selective vision, and spreadsheet assets use a spreadsheet parser. Every extracted item retains supplement filename, page, table/figure locator, and file hash.

## 10. Selective reruns

Reruns are bounded by the post-import gap audit:

- GP-002: only any gap remaining after local composition restoration;
- GP-004: unresolved missing-record text and formulation context;
- GP-005: remaining selective-vision and endpoint adjudication;
- GP-006: remaining supplement/text gaps and selective vision;
- GP-008: only gaps not already answered by its local supplement;
- NP-001: only unresolved formulation-specific transfection, composition, and HepG2 assay fields;
- NP-002: only unresolved assay, endpoint, qualitative-outcome, and comparator fields after local reconciliation;
- PILOT-001 through PILOT-003: recover sources, validate existing facts, then re-extract only unsafe or genuinely absent relationships.

GP-007 receives no default paid rerun. Every paid request requires an exact request path, SHA-256, model, estimated tokens/cost, and explicit human approval. There are no silent retries.

Every returned result is added to the existing manifest as another contributing artifact, imported through the same fact ledger, deduplicated, and re-audited.

## 11. Verification and promotion

The rebuilt database is promoted only when all of the following pass:

- SQLite integrity and foreign-key checks;
- schema migrations are idempotent;
- every manifest artifact exists and matches its hash;
- every source fact and evidence ID is accounted for;
- zero silent omissions;
- zero orphan formulations, components, arms, outcomes, evidence, or projections;
- no duplicate canonical evidence, facts, or formulation-components;
- conflicts remain explicit;
- every populated material field has supporting evidence;
- supplement locators resolve to real hashed files;
- screening-only papers have no scientific rows;
- rebuilding twice from the same manifest produces identical scientific content and counts;
- nearest-neighbor and COMET eligibility are reproducible from versioned rules.

## 12. Honest final report

The final report identifies its database hash, schema version, manifest hash, artifact set, rerun history, unresolved blockers, and rules version. It reports separately:

- papers;
- named formulation records;
- unique chemical formulations;
- complete versus incomplete formulations;
- components;
- source fact occurrences and deduplicated canonical facts;
- experimental arms;
- outcomes;
- source evidence occurrences and deduplicated evidence records;
- nearest-neighbor-ready arms;
- COMET-ready arms;
- unresolved review items.

Counts are split by paper and verification status. No count is described as usable unless it passes the applicable deterministic eligibility rule.

## 13. Explicit non-goals

- Do not discover or screen new papers.
- Do not start the afternoon screening pipeline.
- Do not create a second competing corpus manifest.
- Do not store redundant full JSON blobs in SQLite when immutable local paths and hashes are available.
- Do not rerun a complete paper when a bounded repair is sufficient.
- Do not present source occurrences, named formulations, chemical compositions, arms, or papers as interchangeable counts.

## 14. Time estimate

Assuming all local files remain available, tests run normally, publisher access is not blocked, and paid-call approvals are immediate:

- baseline consolidation and manifest expansion: 30–45 minutes;
- lossless schema, import accounting, and deduplication: 2–3 hours;
- three-schema adapter correction and local rebuild: 1.5–2.5 hours;
- current-corpus supplement and gap audit: 45–75 minutes;
- rerun preflight, approved calls, validation, and merge: 1.5–3 hours;
- final verification and honest report: 60–90 minutes.

Expected elapsed time is **7–11 hours**. The best case is about **6–7 hours** if most apparent gaps close locally and few paid repairs remain. Publisher-access problems, slow approvals, or difficult human adjudication add time. It is therefore possible but not safe to promise that both complete database repair and afternoon screening start will happen the same day; this design protects database correctness rather than meeting the clock by silently dropping evidence.
