# Day 2 Direct Evidence Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the authoritative SQLite database with every recoverable current-corpus evidence record, including review-visible incomplete, conflicting, blocked, and quarantined records, without making paid extraction calls.

**Architecture:** All artifact-specific adapters emit one normalized `ImportBundle`; only the shared transactional importer writes SQLite. GP import, NP reconciliation, and PILOT recovery run concurrently after the bundle contract is fixed, then the authoritative empty database is backed up, migrated, populated paper-by-paper, audited, and reported.

**Tech Stack:** Python 3.14, SQLite, JSON, dataclasses/Pydantic patterns already in the repository, pytest, SHA-256 provenance, and existing local extraction artifacts.

## Global Constraints

- Make zero paid LLM, OpenAI API, Codex, or other extraction calls.
- Do not use the 62-item pilot benchmark as scientific truth or import provenance.
- Do not impute missing values or silently choose between conflicts.
- Do not commit credentials, raw provider responses, licensed PDFs, or the local database backup.
- Store every recoverable record; unsafe records remain visible with simple review tags but ineligible for nearest-neighbor and COMET.
- Use one SQLite transaction per paper and make identical reruns idempotent.
- GP-001, GP-003, and GP-009 remain screening-only with no scientific rows.
- Do not mutate `data/curated/lnp_evidence.db` until the importer, adapters, and temporary-database tests pass.

---

## Morning — Shared importer and parallel evidence preparation

### Task 1: Preflight, backup, and direct-database lifecycle

**Estimated total:** 35–45 minutes

**Files:**
- Create: `src/database/database_lifecycle.py`
- Create: `tests/test_database_lifecycle.py`

**Interfaces:**
- Produces: `preflight_authoritative_database(path)`, `backup_database(path, backup_dir)`, and `migrate_authoritative_database(path)`.

- [ ] **Step 1 — 8 minutes: Write failing preflight tests.** Cover missing database, non-empty scientific tables, backup exclusion/location, original SHA-256 capture, and foreign-key verification.
- [ ] **Step 2 — 3 minutes: Run RED.**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_database_lifecycle.py
```

- [ ] **Step 3 — 15 minutes: Implement minimal lifecycle functions.** Backup uses SQLite backup semantics or a byte copy after closing connections, creates a timestamped non-repository artifact, and never overwrites an existing backup.
- [ ] **Step 4 — 5 minutes: Run GREEN and migration compatibility tests.**
- [ ] **Step 5 — 4 minutes: Commit.**

```bash
git add src/database/database_lifecycle.py tests/test_database_lifecycle.py
git commit -m "feat: add authoritative database lifecycle"
```

### Task 2: Normalized import bundle and transactional importer

**Estimated total:** 70–90 minutes

**Files:**
- Create: `src/database/import_contracts.py`
- Create: `src/database/import_bundle.py`
- Create: `src/database/review_tags.py`
- Create: `tests/test_import_bundle.py`
- Create: `tests/fixtures/database/import_bundle/`

**Interfaces:**
- Produces: `ImportBundle`, `PaperRecord`, `FormulationRecord`, `ComponentRecord`, `ArmRecord`, `OutcomeRecord`, `EvidenceRecord`, `FieldEvidenceLink`, `ReviewRecord`, `import_bundle(connection, bundle)`, and `derive_review_tags(bundle)`.
- `import_bundle()` returns `PaperImportResult(inserted, unchanged, conflicts, quarantined, review_tags)`.

- [ ] **Step 1 — 15 minutes: Write failing normalized-contract tests.** Reject cross-paper links, unknown evidence IDs, missing hashes, malformed numeric values, unsupported source-only claims, and unsafe eligibility states.
- [ ] **Step 2 — 5 minutes: Run RED.**
- [ ] **Step 3 — 20 minutes: Implement typed normalized records and validation.** Stable natural keys include source paper ID and artifact/evidence identity.
- [ ] **Step 4 — 15 minutes: Write failing importer tests.** Prove per-paper rollback, idempotent rerun, evidence/provenance preservation, conflict retention, and screening-only isolation.
- [ ] **Step 5 — 20 minutes: Implement the transactional importer.** Use one explicit transaction/savepoint per bundle and upsert only on stable keys/content hashes.
- [ ] **Step 6 — 10 minutes: Implement controlled plain-language review tags.** Unknown machine reasons map to `Needs human verification` rather than leaking pipeline jargon.
- [ ] **Step 7 — 5 minutes: Run GREEN and commit.**

```bash
git add src/database/import_contracts.py src/database/import_bundle.py src/database/review_tags.py tests/test_import_bundle.py tests/fixtures/database/import_bundle
git commit -m "feat: import normalized evidence bundles"
```

### Task 3: Prepare GP, NP, and PILOT bundles in parallel

**Estimated elapsed total:** 75–105 minutes in parallel

#### Lane A: GP adapter and six bundles

**Estimated:** 50–70 minutes

**Files:**
- Create: `src/database/adapters/accepted_graph.py`
- Create: `data/staging/database/day2_bundles/gp/`
- Create: `tests/test_accepted_graph_adapter.py`
- Create: `reports/database/day2_gp_preparation.md`

- [ ] **Step A1 — 10 minutes: Write failing adapter tests** for paper/formulation/arm/outcome/evidence links, unsupported nodes, missing values, conflicts, and screening-only rejection.
- [ ] **Step A2 — 20 minutes: Implement the adapter** without reading raw provider responses.
- [ ] **Step A3 — 15 minutes: Generate bundles** for GP-002/004/005/006/007/008 and validate every evidence ID/path/hash.
- [ ] **Step A4 — 10 minutes: Record counts, unresolved relations, and review tags.**
- [ ] **Step A5 — 5 minutes: Run focused tests and commit lane files.**

#### Lane B: NP-001 adapter and NP-002 deterministic reconciliation

**Estimated:** 65–90 minutes

**Files:**
- Create: `src/database/adapters/np_results.py`
- Create: `src/database/reconcile_np002.py`
- Create: `data/staging/database/day2_bundles/np/`
- Create: `tests/test_np_database_adapter.py`
- Create: `reports/database/day2_np_preparation.md`

- [ ] **Step B1 — 10 minutes: Write failing NP-001 and NP-002 reconciliation tests.**
- [ ] **Step B2 — 25 minutes: Implement NP-001 normalization and deterministic NP-002 slice union.** Retain conflicts and source-slice provenance; never synthesize missing links.
- [ ] **Step B3 — 15 minutes: Validate NP-002 formulation/recipient/arm/outcome/evidence relationships.**
- [ ] **Step B4 — 15 minutes: Generate importable or quarantined bundles** and simple review tags.
- [ ] **Step B5 — 10 minutes: Run focused tests and commit lane files.**

#### Lane C: PILOT recovery and bundle preparation

**Estimated:** 60–90 minutes

**Files:**
- Create: `src/database/recover_pilot_artifacts.py`
- Create: `src/database/adapters/pilot_results.py`
- Create: `data/staging/database/day2_bundles/pilot/`
- Create: `tests/test_pilot_database_recovery.py`
- Create: `reports/database/day2_pilot_recovery.md`

- [ ] **Step C1 — 10 minutes: Inventory safe local PILOT artifacts** across registered repository worktrees without copying raw responses or the benchmark answer key.
- [ ] **Step C2 — 10 minutes: Write failing recovery/adapter tests.**
- [ ] **Step C3 — 25 minutes: Implement hash-verified source/inventory recovery and deterministic validation.**
- [ ] **Step C4 — 20 minutes: Generate a supported bundle or blocked review bundle per PILOT paper.**
- [ ] **Step C5 — 10 minutes: Run focused tests and commit lane files.**

## Afternoon — Authoritative import, audit, and handoff

### Task 4: Integrate prepared bundles and recalculate statuses

**Estimated total:** 45–60 minutes

**Files:**
- Create: `src/database/run_current_corpus_import.py`
- Create: `tests/test_current_corpus_import.py`
- Create: `reports/database/day2_import_preflight.json`

**Interfaces:**
- Consumes: canonical Day 1 manifest and every validated Day 2 bundle.
- Produces: `run_current_corpus_import(database_path, manifest_path, bundle_root)` and a deterministic preflight/import summary.

- [ ] **Step 1 — 10 minutes: Write failing end-to-end temporary-database tests.** Assert 14 dispositions, screening isolation, paper-level rollback, tag coverage, evidence provenance, and deterministic eligibility.
- [ ] **Step 2 — 5 minutes: Run RED.**
- [ ] **Step 3 — 20 minutes: Implement ordered import orchestration.** Recalculate status and eligibility only after each successful paper transaction.
- [ ] **Step 4 — 10 minutes: Generate and inspect the exact no-call preflight.** Include database hash, backup target, paper order, bundle hashes, expected row counts, and `paid_calls=0`.
- [ ] **Step 5 — 10 minutes: Run GREEN and commit.**

```bash
git add src/database/run_current_corpus_import.py tests/test_current_corpus_import.py reports/database/day2_import_preflight.json
git commit -m "feat: orchestrate current corpus import"
```

### Task 5: Back up, migrate, and populate the authoritative SQLite database

**Estimated total:** 30–45 minutes

**Files:**
- Modify locally: `data/curated/lnp_evidence.db`
- Create locally, Git-ignored: `data/backups/lnp_evidence-pre-day2-<timestamp>.db`
- Create: `reports/database/day2_import_audit.json`

- [ ] **Step 1 — 5 minutes: Verify the authoritative DB is still empty and record its SHA-256.** Stop if scientific rows exist unexpectedly.
- [ ] **Step 2 — 5 minutes: Create and verify the local backup.** Confirm backup and original hashes match before migration.
- [ ] **Step 3 — 5 minutes: Apply the reviewed migration directly.** Verify versions and foreign keys.
- [ ] **Step 4 — 10–20 minutes: Import bundles paper-by-paper.** Record committed/rolled-back status, inserted/unchanged/conflict/quarantine counts, and review tags.
- [ ] **Step 5 — 5 minutes: Re-run identical import and prove idempotency.** No duplicate scientific rows may appear.
- [ ] **Step 6 — 5 minutes: Write the machine-readable audit.**

### Task 6: Database integrity audit, report, and final review

**Estimated total:** 50–65 minutes

**Files:**
- Create: `src/database/audit_current_database.py`
- Create: `tests/test_audit_current_database.py`
- Create: `reports/database/day2_current_evidence_import.md`
- Create conditionally: `reports/database/day2_selective_call_preflight.json`

- [ ] **Step 1 — 10 minutes: Write failing database-audit tests.** Cover foreign keys, orphans, duplicate natural keys, evidence coverage, tag coverage, eligibility consistency, manifest hashes, and all 14 dispositions.
- [ ] **Step 2 — 15 minutes: Implement the deterministic audit and run it against a temporary fixture.**
- [ ] **Step 3 — 10 minutes: Audit the authoritative database.** Report per-paper formulation, arm, outcome, evidence, missing, conflict, quarantine, and eligible-arm counts.
- [ ] **Step 4 — 5 minutes: Generate selective-call preflight only when deterministic recovery cannot access evidence likely present in source material.** It authorizes zero calls and exists solely for later human approval.
- [ ] **Step 5 — 10 minutes: Run the complete offline test suite with credentials blank.**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q
```

- [ ] **Step 6 — 10 minutes: Perform whole-branch review and verify the final database backup, integrity, idempotency, and sensitive-file staging boundaries.**
- [ ] **Step 7 — 5 minutes: Commit code, tests, manifests, and reports.** Do not commit the backup or licensed/raw sources.

## Estimated combined schedule

| Phase | Elapsed time |
|---|---:|
| Lifecycle and shared importer contracts | 1 hr 45 min–2 hr 15 min |
| Parallel GP/NP/PILOT preparation | 1 hr 15 min–1 hr 45 min |
| Integration and direct authoritative import | 1 hr 15 min–1 hr 45 min |
| Final audit, tests, report, and review | 50–65 min |
| Contingency | 30–45 min |
| **Expected elapsed total with overlap** | **4–5.5 hours** |

## Completion criteria

Day 2 is complete only when all 14 papers have database dispositions; every recoverable supported value is stored with evidence/provenance; unresolved material is visible with a plain-language review tag; unsafe records are excluded from nearest-neighbor and COMET eligibility; the direct database import is idempotent and integrity-clean; the backup is verified; the full offline suite passes; and zero paid extraction calls were made.
