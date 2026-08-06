# Day 2 Direct Evidence Import Design

**Date:** 2026-08-06

**Status:** Approved design submitted for written-spec review

**Objective:** Populate the authoritative SQLite database with every recoverable current-corpus evidence record, including incomplete, conflicting, and quarantined material, while keeping unsafe records out of nearest-neighbor and COMET eligibility.

## 1. Scope and execution model

Morning and afternoon work form one continuous implementation run. The seven papers with selected artifacts begin importing while NP-002 reconciliation and PILOT-001–003 source recovery proceed in parallel. Recovered papers enter the same importer and validation gates later in the run.

Day 2 consumes the approved Day 1 manifest and does not rescreen the corpus. It makes zero paid LLM, OpenAI API, or Codex extraction calls. Existing local artifacts are exhausted first. If a paper still needs model extraction, Day 2 produces a separate call/token preflight for human approval rather than dispatching it.

## 2. Authoritative database and safety

The existing empty `data/curated/lnp_evidence.db` is the authoritative database. Day 2 does not build a replacement database.

Before mutation, the workflow:

1. verifies that the database contains zero scientific records;
2. creates a timestamped local backup excluded from Git;
3. records the original SHA-256;
4. applies the reviewed migration directly;
5. verifies foreign keys and migration versions.

Each paper imports inside an independent SQLite transaction. Failure rolls back that paper only. Previously committed papers remain intact. Re-running an identical import is idempotent.

## 3. Parallel lanes

### Lane A: GP evidence import

Import supported evidence from the selected accepted graphs for GP-002, GP-004, GP-005, GP-006, GP-007, and GP-008. GP-001, GP-003, and GP-009 create screening-ledger records only and never create scientific evidence rows.

### Lane B: NP import and reconciliation

Import NP-001 from its selected validated artifact. Reconcile NP-002’s three validated recipient-cell-scoped slices deterministically into a source-evidence-preserving intermediate artifact. Import NP-002 only if paper, formulation, experiment, outcome, and evidence relationships validate; otherwise persist its recoverable material as quarantined review records with explicit reasons.

### Lane C: PILOT source recovery

Search existing local repository/worktree artifacts for PILOT-001–003 source HTML/PDF-derived inventories and validated extraction outputs. Restore only safe source-derived artifacts needed for reproducible import. Do not treat the Codex-authored 62-item benchmark as scientific truth or import provenance.

If sufficient artifacts are recovered, rebuild or validate merged records deterministically and import them. If not, create paper and review records showing why evidence remains blocked. Missing source files do not trigger an LLM call.

### Main lane: importer and database integration

Implement shared adapters, stable identifiers, evidence-preserving normalization, paper transactions, idempotency, provenance, status calculation, and final reporting. Lane-specific code must emit the same normalized import bundle rather than writing directly to SQLite independently.

## 4. Import policy

Day 2 stores every recoverable record rather than only training-ready rows:

- supported and complete;
- supported but incomplete;
- supported but conflicting;
- structurally unresolved or unsupported material as quarantined review records.

No value is imputed. Missing values remain null and receive explicit missing-field records. Conflicting values are stored independently with their own evidence; the importer does not choose a winner silently.

Every material scientific value must link to:

- paper;
- formulation and experimental arm when applicable;
- outcome when applicable;
- exact evidence text or structured evidence representation;
- source location and modality;
- source artifact path and hash;
- pipeline/version lineage;
- verification state.

## 5. Plain-language review tags

Quarantined, conflicting, blocked, and incomplete records remain visible in the database and later UI. Each receives at least one controlled plain-language tag selected from:

- `Missing dose`
- `Missing formulation ratio`
- `Missing outcome value`
- `Missing evidence excerpt`
- `Source file unavailable`
- `Conflicting formulation`
- `Conflicting target cell`
- `Conflicting outcome`
- `Experiment link unclear`
- `Outcome link unclear`
- `Unsupported value`
- `Needs human verification`

The stored machine-readable reason code remains available internally. The user-visible tag must be short and understandable without pipeline terminology.

## 6. Eligibility and visibility

After every paper transaction, deterministic rules recalculate:

- arm status: `complete`, `incomplete`, `conflict`, or `quarantined`;
- verification status;
- nearest-neighbor eligibility;
- COMET eligibility.

Incomplete, conflicting, and quarantined records remain visible for browsing and review. They are excluded from nearest-neighbor and COMET datasets unless later evidence-backed correction makes them eligible.

The database stores eligibility reasons so exclusion is explainable. Eligibility never depends on an LLM judgment or the 62-item benchmark.

## 7. Import adapters

Adapters may differ by source artifact shape but must produce one normalized bundle contract containing papers, formulations, components, arms, outcomes, evidence, field links, source artifacts, missing fields, and review tags.

Adapters are required for:

- accepted-graph GP artifacts;
- NP-001 validated result;
- reconciled NP-002 slices;
- recovered PILOT merged/inventory artifacts when available;
- blocked-paper review records when source evidence is unavailable.

Adapters reject unknown evidence identifiers, cross-paper links, missing source hashes, malformed scientific values, and raw provider-response-only claims.

## 8. Validation and error handling

Tests and runtime checks must prove:

- migration and direct import preserve the database on failure;
- importing the same paper twice creates no duplicates;
- one paper’s failure does not roll back another paper;
- screening-only papers create no formulations, arms, outcomes, or evidence;
- every imported value has resolvable evidence and provenance;
- incomplete/conflicting/quarantined records have plain-language review tags;
- unsafe records remain ineligible;
- evidence-backed corrections can later change eligibility without destroying history;
- source-artifact hashes match the Day 1 manifest;
- no paid call or silent retry occurs.

The final SQLite checks include `foreign_key_check`, uniqueness audits, orphan audits, per-paper counts, eligibility consistency, review-tag coverage, and source-hash reconciliation.

## 9. Outputs

Day 2 produces:

1. the migrated and populated `data/curated/lnp_evidence.db`;
2. a local pre-import backup excluded from Git;
3. deterministic NP-002 reconciliation output or a quarantined reconciliation report;
4. PILOT recovery manifests for each paper;
5. a machine-readable import audit;
6. a human-readable paper-by-paper import report;
7. a separate selective-call preflight only if remaining gaps genuinely require extraction.

The report distinguishes imported scientific rows, incomplete rows, conflicts, quarantined rows, screening-only papers, blocked papers, and training-eligible arms.

## 10. Completion criteria

Day 2 is complete when:

- every one of the 14 manifest papers has a database disposition;
- every recoverable supported value from the seven selected artifacts is stored with evidence and provenance;
- NP-002 is either imported after deterministic reconciliation or represented by evidence-backed quarantined records;
- each PILOT paper is either recovered/imported or represented by a clear blocked review record;
- incomplete, conflicting, and quarantined evidence is visible with a simple review tag;
- nearest-neighbor and COMET eligibility exclude unsafe records deterministically;
- the final database passes integrity, idempotency, provenance, and full offline tests;
- zero paid extraction calls were made.

## 11. Estimated elapsed time

- Direct-import preflight, backup, and migration: 20–30 minutes.
- Shared normalized bundle and transactional importer: 60–90 minutes.
- GP import lane: 45–75 minutes in parallel.
- NP reconciliation/import lane: 60–90 minutes in parallel.
- PILOT recovery lane: 45–90 minutes in parallel.
- Integrated import, eligibility calculation, and review tags: 45–60 minutes.
- Database audits, full tests, report, and review: 45–60 minutes.
- Contingency for malformed or missing artifacts: 30–45 minutes.

With parallel execution, expected elapsed time is approximately 4–5.5 hours.
