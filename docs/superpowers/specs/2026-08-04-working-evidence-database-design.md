# Working Liver-LNP Evidence Database Design

**Date:** 2026-08-04

**Status:** Approved design awaiting written-spec review

**Objective:** Populate a refreshable evidence database from all existing AI-LNP extraction artifacts, selectively rerun weak papers through the current pipeline, and support low-intervention discovery and extraction of additional liver-LNP papers.

## 1. Core decision: do not invent paper-level denominators

The application will not display “the pipeline extracted X of Y total requirements from this paper” for ordinary papers. Establishing Y would require a second LLM or Codex pass to create an answer key, and an AI-authored answer key is not independent ground truth.

The existing 62-item application-pilot reference was authored and subsequently revised by Codex subagents. It may remain an internal debugging fixture, but it is not a human gold standard and must not be presented as a scientifically validated extraction-recall denominator.

For every paper, the database will instead report what is directly knowable:

- every experimental arm identified by the pipeline;
- every extracted value and its exact evidence;
- fields that are absent from the extraction as `NA`;
- an explicit list of missing fields;
- arm status: `complete`, `incomplete`, `conflict`, or `quarantined`;
- evidence verification status;
- deterministic nearest-neighbor and COMET eligibility.

An extraction-recall percentage may be shown only for a separately maintained benchmark whose reference was independently human-verified and whose provenance is recorded.

## 2. Product medium

The first working product will be a local Streamlit application backed by SQLite, with Excel export and controlled Excel import for human corrections.

- **SQLite** is the authoritative local scientific store.
- **Streamlit** provides paper browsing, dropdown filtering, evidence inspection, review queues, and update controls.
- **Excel export** supports offline review and sharing.
- **Controlled Excel import** accepts human corrections only through validated columns and preserves the previous value and provenance.
- A manual **Run discovery/update** action starts refreshes initially. Scheduled automation can be added after the workflow is stable.

The database is refreshable: new searches and extraction artifacts append or update versioned records without erasing prior evidence or human review.

## 3. Scientific data model

The existing relational backbone will be retained:

1. **Paper** — title, DOI, PMID/PMCID, journal, retrieval source, full-text status, screening status, and access links.
2. **Formulation** — reported formulation name, composition text, composition basis, and formulation ratio.
3. **Chemical component** — each lipid/component identity, normalized identity, role, percentage, and review status.
4. **Experimental arm** — one formulation-payload-model-recipient-treatment context.
5. **Outcome** — one measured endpoint linked to an experimental arm.
6. **Evidence** — exact excerpt or structured table/figure evidence supporting a field or outcome.

Internal tables will additionally preserve source-artifact and history information without cluttering the user-facing table:

- import/source pipeline and version;
- internal extraction run identifier;
- source artifact path and content hash;
- previous values and correction history;
- screening ledger for excluded papers;
- field-level review decisions.

The internal extraction run identifier will not appear in the normal user-facing table. Verification status will remain visible.

## 4. User-facing paper grouping and arm columns

The primary evidence browser will group rows by paper. Each paper heading shows:

- paper title;
- DOI as a clickable link;
- PMID/PMCID when available;
- publication year;
- full-text/access status;
- paper-level verification summary.

Each row below the heading represents one experimental arm and exposes at least:

- arm ID;
- LNP/formulation name;
- LNP components;
- formulation ratio, or `NA`;
- payload type and payload identity;
- species;
- experimental setting/delivery model (`in_vitro`, `ex_vivo`, or `in_vivo`);
- target cell;
- delivery/recipient cell;
- dose and dose unit, or `NA`;
- administration route, or `NA`;
- timepoint, or `NA`;
- assay;
- comparator;
- outcome/endpoint;
- outcome value and unit, or qualitative result;
- arm status;
- missing fields;
- verification status;
- nearest-neighbor eligibility;
- COMET eligibility.

When target cell and delivery cell are the same, the value is repeated in both columns. `NA` means the pipeline has no supported value; it never means zero and is never silently imputed.

Selecting a value or its evidence control opens the supporting evidence excerpt, evidence location, source modality, and reviewer notes. Paper/formulation/arm links navigate between related views rather than exposing raw linked database tables.

## 5. Completeness and eligibility rules

### 5.1 Arm completeness

Completeness is evaluated against a fixed application schema, not an AI-generated inventory of everything the paper contains.

- `complete`: all fields required for the arm's intended use are present, supported, and non-conflicting.
- `incomplete`: the arm is scientifically useful but one or more required fields are `NA`.
- `conflict`: two supported sources or extraction artifacts disagree.
- `quarantined`: the formulation-arm-outcome relationship is unsafe or unresolved.

The UI lists the missing or conflicting fields directly. It does not convert this into a claim about total paper recall.

### 5.2 Nearest-neighbor eligibility

Nearest-neighbor eligibility is calculated deterministically from the fields required by the chosen similarity representation. At minimum, the formulation identity/composition, relevant biological context, and outcome linkage must be supported. Records with unresolved arm linkage or incompatible/missing model features are excluded from the production index but remain visible as evidence.

### 5.3 COMET eligibility

COMET eligibility requires a compatible, fully linked training row with the required formulation inputs, biological context, treatment context, outcome target, units/normalization, and accepted evidence status. A human-added value can make an arm eligible only when the human also supplies its evidence excerpt and location and the value passes the same validation rules.

Incomplete records are never imputed into COMET training. They remain available for literature browsing and may enter the human review queue.

## 6. Evidence and human correction workflow

Every material value must retain:

- the value as reported;
- normalized value when applicable;
- exact evidence excerpt or structured evidence;
- location: section/page/table/figure/supplement;
- extraction method;
- verification status;
- reviewer notes and correction history.

The human review queue prioritizes arms that are otherwise eligible but missing only one or two required COMET fields. The reviewer enters:

1. the missing value;
2. evidence excerpt or table cell text;
3. source location;
4. optional notes.

After validation, the application recalculates completeness and eligibility. Human corrections are additive and auditable; they do not overwrite the original extraction without history.

## 7. Initial corpus loading

The loader will union scientifically supported evidence from all existing extraction pipelines and artifacts, preserving the source pipeline/version for each imported claim.

### Existing paper groups

- **GP-001 through GP-009** — first nine screened/gold-set papers and their accumulated extraction artifacts.
- **NP-001 and NP-002** — later full-paper extraction papers.
- **PILOT-001 through PILOT-003** — three application-pilot papers. Their extracted evidence may be loaded, but their Codex-authored 62-item answer key is not treated as human gold.

### Excluded papers

GP-001, GP-003, and GP-009 remain in an internal screening ledger with exclusion reasons. They do not appear as scientific evidence rows and are not used as negative training examples for screening unless a later screening-learning design explicitly establishes that use.

### Selective rerun policy

- **GP-002, GP-005, GP-006:** load their strongest verified evidence; no immediate rerun unless validation reveals a material gap.
- **GP-004, GP-007:** retain partial evidence and missing-field notes; rerun only if accessible source evidence suggests the field actually exists.
- **GP-008:** route unresolved biological-role ambiguity to human review.
- **NP-001:** selectively rerun liver-relevant portions if current-pipeline fields are missing.
- **NP-002:** high-priority selective rerun because the prior output recovered only 13 of 18 expected arms in its existing paper-specific benchmark.
- **PILOT-001 through PILOT-003:** load current merged evidence without an initial rerun; do not display 40/62 or 57/62 as validated recall.

The loader keeps the best supported union across pipeline versions. It never selects a newer value merely because it is newer.

## 8. Discovery and full-text access

New-paper discovery will query PubMed, OpenAlex, and Europe PMC for all four target liver-cell groups:

- hepatocytes;
- Kupffer cells;
- liver sinusoidal endothelial cells;
- hepatic stellate cells.

Discovery results are deduplicated by DOI, PMID, PMCID, and normalized title. Screening retains the reason, query, timestamp, and source metadata.

Full-text acquisition priority:

1. open Europe PMC/PMC structured full text;
2. open publisher HTML/XML/PDF;
3. institutional-access link presented to the signed-in user;
4. user-uploaded licensed PDF stored locally and never committed;
5. abstract-only record or access-required review state.

The application may open institutional links, but it will not store institutional credentials or bypass publisher access controls. A user-supplied licensed PDF can enter the same ingestion pipeline after local validation.

## 9. Low-call extraction policy

Extraction calls are minimized according to scientific structure, without a rigid hard cap.

- **Gate A:** normally one whole-paper mapping call per paper.
- **Gate B:** normally two to three coherent experiment-group calls per paper.
- **Selective vision:** invoked only when a required relationship or value is present only in a figure or image-based table.
- No Codex audit call is part of the standard route.
- No silent retries or automatic paid repair loops.
- Before a paid batch, show the paper list, exact call count, estimated input/output tokens, and request hashes.
- If paper complexity requires materially more calls, pause and show the reason before provider dispatch.

The system minimizes repeated full-paper context by sending a compact paper map plus only the evidence needed for each coherent experiment group.

## 10. Expansion targets and readiness checkpoints

The initial expansion target is approximately ten eligible new papers for each of the four liver-cell groups, subject to actual literature availability.

Progress is measured by usable arms, not paper count alone:

- nearest-neighbor checkpoint: at least 30 fully verified, representation-compatible arms per cell group;
- COMET feasibility checkpoint: at least 100 compatible arms for one coherent cell/outcome family;
- extraction-process reassessment: if fewer than 30% of extracted arms become fully verified/eligible, diagnose the dominant missing fields before scaling calls further.

These are capacity/readiness checkpoints, not claims that a model is ready or scientifically valid.

## 11. Refresh workflow

The manual update action executes an observable sequence:

1. query discovery sources;
2. deduplicate against papers and screening ledger;
3. screen candidates;
4. resolve or request full text;
5. build local evidence inventories;
6. show paid-call/token preflight;
7. run approved extraction calls;
8. validate and merge records;
9. load new evidence with provenance;
10. recalculate completeness and eligibility;
11. publish a refresh summary and review queue.

Failures are recorded per paper and do not corrupt previously accepted records. The user can rerun a failed paper after correcting access or source issues.

## 12. Validation and testing

Implementation must include fixture-driven tests for:

- idempotent paper and evidence imports;
- deduplication across DOI/PMID/PMCID/title;
- preservation of evidence and source pipeline/version;
- union merge without unsupported overwrites;
- correct `NA` and missing-field behavior;
- completeness state transitions;
- nearest-neighbor eligibility rules;
- COMET eligibility before and after a validated human correction;
- exclusion-ledger isolation;
- licensed-file and credential non-persistence;
- paid-call preflight and no silent retry behavior;
- Excel export/import round trips;
- Streamlit filters for liver cell, payload, species, delivery model, and outcome.

No unit test may make a paid provider call. Approved end-to-end extraction runs are separately logged benchmarks.

## 13. Explicit non-goals for the first release

- Creating a new LLM/Codex answer key for every paper.
- Claiming near-100% paper-level recall without independent human gold.
- Reintroducing Codex auditing into the ordinary extraction path.
- Imputing missing scientific values.
- Automatically training COMET before data-readiness gates pass.
- Fully autonomous institutional login or licensed-content retrieval.
- Background scheduling before the manual refresh workflow is stable.

## 14. Acceptance criteria

The first working release is acceptable when:

1. all current included papers and all supported experimental arms from existing artifacts are visible and grouped by paper;
2. every material displayed value links to evidence and provenance;
3. missing values are explicit and no paper-level denominator is shown;
4. verification, completeness, nearest-neighbor eligibility, and COMET eligibility are deterministic and visible;
5. selected weak papers are flagged or rerun according to policy;
6. a user can add a missing value with evidence and see eligibility recalculate;
7. discovery can identify and stage new papers across the four cell groups;
8. full-text access supports open sources, institutional links, and local PDF upload;
9. every paid extraction batch is preceded by a call/token estimate;
10. the database can be exported to Excel and refreshed without losing history.
