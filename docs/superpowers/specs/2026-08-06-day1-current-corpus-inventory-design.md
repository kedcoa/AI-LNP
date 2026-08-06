# Day 1 Current-Corpus Inventory and Database Contract Design

**Date:** 2026-08-06

**Status:** Approved design submitted for written-spec review

**Objective:** Complete the Day 1 morning paper inventory and afternoon database-contract work in 3.5–4.5 elapsed hours through three isolated inventory lanes plus one integration/schema lane, using no paid LLM or Codex extraction calls.

## 1. Scope boundary

Day 1 determines what current paper and extraction artifacts exist, which artifact is the strongest supported import source for each paper, and how each paper should be routed on Days 2–3. It does not import arm-level evidence, rerun extraction, create new scientific answer keys, or deeply re-evaluate every extracted claim.

The work covers 14 paper IDs:

- GP-001 through GP-009;
- NP-001 and NP-002;
- PILOT-001 through PILOT-003.

GP-001, GP-003, and GP-009 remain screening-ledger-only records. The other 11 papers are candidates for supported-evidence import.

## 2. Zero-paid-call constraint

Day 1 makes zero paid LLM, OpenAI API, or Codex extraction calls. Metadata resolution uses existing local artifacts first and free bibliographic lookups only when DOI, PMID, PMCID, title, or publication metadata remain unresolved. No extraction output is regenerated.

## 3. Parallel execution model

Three inventory workers operate on non-overlapping paper groups and write lane-specific candidate manifests. The main worker builds the schema migration and deterministic validation rules concurrently, then combines the three lane outputs.

### Lane A: GP corpus

Inventory GP-001 through GP-009. Record metadata, screening disposition, local source assets, extraction artifacts, pipeline/version lineage, strongest supported artifact, import readiness, unresolved issues, and recommended Day 2–3 routing.

### Lane B: NP corpus

Inventory NP-001 and NP-002. Reconstruct their extraction and selective-vision lineage, select the strongest supported artifact, and record targeted rerun recommendations. NP-002 retains its high-priority selective-rerun flag; this lane does not perform the rerun.

### Lane C: PILOT corpus and metadata completion

Inventory PILOT-001 through PILOT-003 and reconcile missing bibliographic identifiers across all 14 papers. The Codex-authored 62-item reference remains an internal debugging artifact and is not represented as human gold or a user-visible recall denominator.

### Main lane: database contract and integration

Extend the existing relational SQLite schema without discarding the paper, formulation, component, experiment, outcome, and evidence backbone. Add storage for provenance, source artifacts, arm status, explicit missing fields, verification state, review history, screening-ledger disposition, and deterministic nearest-neighbor and COMET eligibility.

## 4. Manifest contract

The versioned current-corpus manifest is the controlled packing list for Day 2. Each paper entry records:

- stable paper ID;
- title, DOI, PMID, PMCID, and publication metadata;
- include or screening-only disposition and reason;
- available full-text/source paths and access status;
- candidate extraction artifacts and pipeline/version lineage;
- one selected strongest supported import artifact, or an explicit unresolved reason;
- import status: `ready`, `ready_with_missing_fields`, `needs_review`, `blocked`, or `screening_only`;
- rerun status: `none`, `selective`, or `blocked_pending_access`;
- rerun scope and reason when applicable;
- metadata provenance and last-checked timestamp.

The manifest controls which artifact the Day 2 importer reads. It does not assert that every claim inside an approved artifact is correct; field- and arm-level validation occurs during import and Day 3 quality control.

## 5. Strongest-artifact selection

Selection is deterministic wherever possible:

1. Reject failed, malformed, invalidated, or superseded artifacts.
2. Prefer validated merged outputs over raw provider responses.
3. Prefer evidence-preserving outputs with resolvable paper, experiment, outcome, and evidence links.
4. Prefer a newer pipeline only when it retains at least the supported evidence of the older artifact.
5. If two viable artifacts conflict, select neither automatically; mark the paper `needs_review` and list both candidates.

Runtime invocations and raw provider responses may be referenced locally but are never newly committed as part of the manifest.

## 6. Database contract additions

The migration must preserve existing data and support:

- stable textual source paper IDs alongside internal SQLite keys;
- paper screening and import dispositions;
- source artifact path, content hash, pipeline name, and pipeline version;
- arm status: `complete`, `incomplete`, `conflict`, or `quarantined`;
- explicit missing-field records rather than inferred null semantics;
- field/evidence verification status;
- additive review and correction history;
- deterministic eligibility profiles and results for nearest-neighbor and COMET use;
- migration/version metadata.

Eligibility is recalculable and is never entered as an unsupported manual opinion. The extraction run identifier remains internal and absent from the normal user-facing table.

## 7. Validation and error handling

The manifest validator must reject duplicate paper IDs, unknown dispositions, missing routing reasons, nonexistent selected artifacts, and excluded papers marked import-ready. It must report unresolved metadata without failing the entire corpus.

Migration tests run against a temporary SQLite database and prove that:

- the legacy six-table schema upgrades without data loss;
- required new tables, columns, checks, and foreign keys exist;
- the migration is idempotent;
- eligibility and review history can be stored independently;
- screening-only papers cannot become import candidates accidentally.

Lane outputs are merged only after schema validation. Disagreements become explicit review items; they are not silently resolved.

## 8. Deliverables

Day 1 is complete only when the repository contains:

1. one versioned 14-paper current-corpus manifest;
2. exactly 11 included/import-candidate dispositions and three screening-only dispositions;
3. a strongest-artifact decision or explicit unresolved reason for every included paper;
4. the migration-capable SQLite database contract;
5. deterministic manifest, migration, and eligibility tests;
6. a concise Day 1 report listing import-ready, review, rerun, blocked, and screening-only counts;
7. zero paid extraction calls recorded for the work.

## 9. Estimated elapsed time

- Preflight and automated artifact scan: 20–30 minutes.
- Three parallel inventory lanes: 60–90 minutes.
- Concurrent schema migration and eligibility contract: 90–120 minutes.
- Manifest integration and conflict resolution: 30–45 minutes.
- Full migration/manifest verification and report: 30–45 minutes.
- Contingency: 20–30 minutes.

Because inventory and schema work overlap, the expected elapsed total is 3.5–4.5 hours, not the sum of every worker's effort.

## 10. Day 2 and Day 3 boundary

Day 2 consumes the approved manifest and imports supported formulations, arms, outcomes, and evidence into SQLite. Day 3 validates the populated relationships, identifies duplicates and conflicts, recalculates eligibility, and produces the selective-rerun and human-review queues. Day 1 performs neither activity.
