# Day 1 Current-Corpus Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a validated 14-paper import-routing manifest and a migration-tested SQLite contract for provenance, review, completeness, and downstream eligibility without making any paid extraction calls.

**Architecture:** A deterministic local scanner establishes candidate artifacts and a strict manifest model. Three workers inventory non-overlapping GP, NP, and PILOT paper groups into separate lane files while the schema lane adds migration and eligibility support; an integrator validates and combines the lanes into the canonical manifest and Day 1 report.

**Tech Stack:** Python 3.14, dataclasses/Pydantic patterns already used in the repository, JSON, SQLite, pytest, local filesystem metadata, and optional free PubMed/OpenAlex/Europe PMC metadata lookup only for unresolved identifiers.

## Global Constraints

- Make zero paid LLM, OpenAI API, or Codex extraction calls.
- Never create or use a new scientific answer key.
- Never commit credentials, licensed PDFs, raw provider responses, or unredacted provider payloads.
- Cover exactly GP-001–GP-009, NP-001–NP-002, and PILOT-001–PILOT-003.
- Keep GP-001, GP-003, and GP-009 screening-only; exactly 11 papers remain import candidates.
- Select validated merged artifacts over raw responses; unresolved conflicts become `needs_review`.
- Do not import arm-level evidence on Day 1.
- Preserve the existing paper/formulation/component/experiment/outcome/evidence relational backbone.
- Use TDD for code changes and run tests with API credentials blank.

---

## Morning — Inventory and routing manifest

### Task 1: Manifest contract and deterministic artifact scanner

**Estimated elapsed time:** 35–50 minutes

**Files:**
- Create: `src/database/__init__.py`
- Create: `src/database/corpus_manifest.py`
- Create: `tests/test_corpus_manifest.py`
- Create: `tests/fixtures/database/corpus_manifest/valid_lane.json`

**Interfaces:**
- Produces: `CorpusEntry`, `ArtifactCandidate`, `load_lane(path)`, `validate_corpus(entries, root)`, and `scan_artifact_candidates(root, paper_ids)`.
- `CorpusEntry.import_status` is one of `ready`, `ready_with_missing_fields`, `needs_review`, `blocked`, or `screening_only`.
- `CorpusEntry.rerun_status` is one of `none`, `selective`, or `blocked_pending_access`.

- [ ] **Step 1: Write contract tests** proving valid entries load, duplicate paper IDs fail, screening-only papers cannot select an import artifact, selected artifacts must exist, rerun reasons are mandatory for non-`none` routing, and unresolved bibliographic fields remain explicit rather than fabricated.
- [ ] **Step 2: Run the focused test and confirm RED.**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_corpus_manifest.py
```

Expected: collection failure because `src.database.corpus_manifest` does not exist.

- [ ] **Step 3: Implement the minimal typed contract and scanner.** The scanner searches tracked/local artifact paths, records path, SHA-256, artifact kind, pipeline/version clue, validation clue, and modification time. It performs no scientific extraction and does not read `.env`.
- [ ] **Step 4: Run the focused tests and confirm GREEN.**
- [ ] **Step 5: Commit.**

```bash
git add src/database tests/test_corpus_manifest.py tests/fixtures/database/corpus_manifest
git commit -m "feat: define current corpus manifest"
```

### Task 2: Inventory three non-overlapping paper lanes

**Estimated elapsed time:** 60–90 minutes in parallel

**Files:**
- Create: `data/manifests/current_corpus_lanes/gp_v1.json`
- Create: `data/manifests/current_corpus_lanes/np_v1.json`
- Create: `data/manifests/current_corpus_lanes/pilot_v1.json`
- Create: `reports/database/day1_lane_gp.md`
- Create: `reports/database/day1_lane_np.md`
- Create: `reports/database/day1_lane_pilot.md`

**Interfaces:**
- Consumes: Task 1 manifest contract and all existing local source/extraction artifacts.
- Produces: three independently valid lane documents whose union contains exactly 14 unique paper IDs.

- [ ] **Step 1: Dispatch the GP lane worker.** Inventory GP-001–GP-009; enforce screening-only status for GP-001, GP-003, and GP-009; identify strongest supported artifact or an explicit unresolved reason.
- [ ] **Step 2: Dispatch the NP lane worker concurrently.** Inventory NP-001 and NP-002, reconstruct pipeline lineage, and record selective rerun scope without running extraction.
- [ ] **Step 3: Dispatch the PILOT/metadata worker concurrently.** Inventory PILOT-001–PILOT-003, reject the 62-item reference as human gold, and resolve missing identifiers locally before optional free bibliographic lookups.
- [ ] **Step 4: Each worker validates its lane with `load_lane()` and writes a concise evidence-backed report listing source paths, selected artifact rationale, unresolved metadata, and routing decisions.
- [ ] **Step 5: Review each lane for specification compliance and commit only its owned JSON/report files.**

## Afternoon — Database contract and integration

### Task 3: Migration-safe provenance, review, status, and eligibility schema

**Estimated elapsed time:** 90–120 minutes, overlapping Task 2

**Files:**
- Modify: `src/schema.sql`
- Modify: `src/init_db.py`
- Create: `src/database/migrations.py`
- Create: `src/database/status.py`
- Modify: `tests/test_schema.py`
- Create: `tests/test_database_migrations.py`
- Create: `tests/test_database_status.py`

**Interfaces:**
- Produces: `migrate_database(connection)`, `evaluate_arm_status(connection, experiment_id)`, and `evaluate_eligibility(connection, experiment_id, profile)`.
- Eligibility profiles are `nearest_neighbor` and `comet`; results are deterministic and evidence/relation based.

- [ ] **Step 1: Write failing schema and migration tests** for legacy-data preservation, idempotent migration, foreign keys, source artifacts, explicit missing fields, verification state, additive review history, screening events, and eligibility results.
- [ ] **Step 2: Write failing status tests** for `complete`, `incomplete`, `conflict`, and `quarantined`, plus nearest-neighbor and COMET eligibility transitions after an evidence-backed human correction.
- [ ] **Step 3: Run the focused tests and confirm RED.**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_schema.py tests/test_database_migrations.py tests/test_database_status.py
```

- [ ] **Step 4: Implement the minimal migration and deterministic evaluators.** Do not modify `data/curated/lnp_evidence.db`; tests use temporary databases.
- [ ] **Step 5: Run the focused tests and confirm GREEN.**
- [ ] **Step 6: Commit.**

```bash
git add src/schema.sql src/init_db.py src/database/migrations.py src/database/status.py tests/test_schema.py tests/test_database_migrations.py tests/test_database_status.py
git commit -m "feat: add working evidence database contract"
```

### Task 4: Integrate and validate the canonical current-corpus manifest

**Estimated elapsed time:** 30–45 minutes

**Files:**
- Create: `config/database/current_corpus_v1.json`
- Create: `src/database/build_current_corpus.py`
- Create: `tests/test_build_current_corpus.py`
- Create: `reports/database/day1_current_corpus_inventory.json`
- Create: `reports/database/day1_current_corpus_inventory.md`

**Interfaces:**
- Consumes: the three Task 2 lane files and Task 1 validation functions.
- Produces: `build_current_corpus_manifest(root, lane_paths, output_path)` and the canonical Day 2 routing input.

- [ ] **Step 1: Write failing integration tests** asserting 14 unique papers, 11 import candidates, three screening-only records, no selected raw provider response, every included paper having a selected artifact or explicit reason, and zero paid calls.
- [ ] **Step 2: Run the focused test and confirm RED.**
- [ ] **Step 3: Implement deterministic lane merge, stable ordering, content hashes, summary counts, and append-safe report generation.** Conflicting lane claims must become validation errors rather than last-write-wins behavior.
- [ ] **Step 4: Generate the real canonical manifest and Day 1 report.**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m src.database.build_current_corpus --root . --output config/database/current_corpus_v1.json --report-root reports/database
```

Expected: 14 total, 11 included, three screening-only, zero paid calls.

- [ ] **Step 5: Run focused tests and commit.**

```bash
git add config/database/current_corpus_v1.json src/database/build_current_corpus.py tests/test_build_current_corpus.py reports/database/day1_current_corpus_inventory.json reports/database/day1_current_corpus_inventory.md
git commit -m "feat: inventory current paper corpus"
```

### Task 5: Day 1 verification and handoff

**Estimated elapsed time:** 30–45 minutes plus 20–30 minutes contingency

**Files:**
- Modify if necessary: `reports/database/day1_current_corpus_inventory.md`

**Interfaces:**
- Consumes: canonical manifest, schema migration, status rules, and all tests.
- Produces: an evidence-backed Day 1 completion decision and Day 2 import queue.

- [ ] **Step 1: Validate every selected artifact path and SHA-256 against the filesystem.**
- [ ] **Step 2: Apply the migration twice to a temporary copy of the legacy six-table schema and confirm identical schema/data after the second run.**
- [ ] **Step 3: Run the complete offline test suite with paid credentials blank.**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q
```

- [ ] **Step 4: Confirm the working database remains unmodified and no raw provider or licensed source files were staged.**
- [ ] **Step 5: Perform whole-branch review, address load-bearing findings, and record the final verified counts and remaining Day 2/Day 3 work in the report.**

## Estimated Day 1 schedule

| Window | Parallel work | Elapsed time |
|---|---|---:|
| Morning preflight | Baseline tests, scanner/contract setup | 20–30 min |
| Morning inventory | GP, NP, and PILOT lanes concurrently | 60–90 min |
| Morning–afternoon overlap | Schema migration/status work begins during inventories | 90–120 min |
| Afternoon integration | Merge lanes, validate 14-paper manifest, resolve conflicts | 30–45 min |
| Afternoon verification | Migration tests, full suite, report and review | 30–45 min |
| Contingency | Missing metadata or artifact conflicts | 20–30 min |
| **Expected elapsed total** | Overlapping execution | **3.5–4.5 hours** |

## Completion criteria

Day 1 is complete only when the canonical manifest reports exactly 14 paper dispositions, exactly 11 import candidates, exactly three screening-only records, a selected supported artifact or explicit unresolved reason for every included paper, a passing idempotent database migration, deterministic eligibility/status tests, and zero paid extraction calls.
