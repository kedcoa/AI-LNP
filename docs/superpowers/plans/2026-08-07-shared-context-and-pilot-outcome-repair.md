# Shared Context and Pilot Outcome Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the authoritative SQLite database so source-backed shared organ, cell, model, timepoint, formulation, and outcome facts reach every applicable arm without false readiness.

**Architecture:** Fix canonical field projection in the NP and PILOT adapters, recover only evidence-bound pilot outcomes from the existing consolidated extraction, and use the existing fail-closed source-repair layer for paper-specific shared context. Recalculate readiness only after all projections and preserve field-level provenance.

**Tech Stack:** Python, dataclasses/Pydantic contracts, SQLite, pytest, JSON source manifests.

## Global Constraints

- No paid API calls.
- Never infer a value without source evidence.
- Shared context may propagate only to explicitly applicable arms.
- Biological model remains optional for readiness; mandatory fields follow `readiness_profiles_v3.json`.
- Every populated canonical field and outcome must retain evidence provenance.
- No CodeRabbit CLI.

---

### Task 1: Canonical organ and transfected-cell projection

**Files:**
- Modify: `src/database/adapters/np_results.py`
- Modify: `src/database/adapters/pilot_map_results.py`
- Test: `tests/test_np_database_adapter.py`
- Test: `tests/test_pilot_map_database_merge.py`

- [ ] Write failing tests proving reported organ and delivery-recipient cells populate the canonical recipient-organ and observed-transfected-cell fields.
- [ ] Run focused tests and confirm the expected failures.
- [ ] Implement the minimal evidence-linked projections.
- [ ] Run focused tests and confirm they pass.

### Task 2: Recover evidence-bound PILOT outcomes

**Files:**
- Modify: `src/database/adapters/pilot_map_results.py`
- Modify: `src/database/run_current_corpus_import.py`
- Test: `tests/test_pilot_map_database_merge.py`
- Test: `tests/test_current_corpus_import.py`

- [ ] Write failing tests requiring existing normalized outcome facts to be attached to the map context with matching evidence IDs.
- [ ] Run focused tests and confirm the expected failures.
- [ ] Parse outcome fact groups from `application_pilot_final.json`, require a matching map candidate and evidence intersection, and project supported fields into `OutcomeRecord` rows.
- [ ] Preserve nonprojected facts in the ledger and leave genuinely unsupported outcome fields unresolved.
- [ ] Run focused tests and confirm they pass.

### Task 3: Repair source-backed shared context and chemistry

**Files:**
- Modify: `config/database/source_backed_arm_repairs_v1.json`
- Modify: `src/database/adapters/accepted_graph.py`
- Test: `tests/test_current_corpus_import.py`
- Test: `tests/test_accepted_graph_lossless_adapter.py`

- [ ] Write failing database assertions for NP-002, GP-005, GP-006, GP-007, and GP-008.
- [ ] Run focused tests and confirm the expected failures.
- [ ] Add exact-source arm repairs for NP-002 and GP-006/GP-008 shared context.
- [ ] Correct GP-007 chemistry semantics without fabricating an unreported lipid ratio.
- [ ] Split/project GP-005 and propagate GP-008 shared lipid chemistry only where supported.
- [ ] Run focused tests and confirm they pass.

### Task 4: Enforce recurring mistake-pattern invariants

**Files:**
- Create: `docs/database/shared-context-projection-invariants.md`
- Modify: `tests/test_current_corpus_import.py`

- [ ] Document the source-to-canonical-field failure patterns and safe propagation rules.
- [ ] Add corpus regression checks for inconsistent paper-wide organ/protocol fields, outcome-loss, and readiness with missing mandatory fields.
- [ ] Run the focused database suite.

### Task 5: Rebuild and verify the authoritative database

**Files:**
- Regenerate: `data/curated/lnp_evidence.db`
- Regenerate: `reports/database/final_current_corpus_report.json`
- Regenerate: `reports/database/final_current_corpus_report.md`

- [ ] Run the fresh deterministic rebuild.
- [ ] Verify SQLite integrity, arm/outcome counts, mandatory-field readiness, and representative rows for every repaired paper.
- [ ] Run the complete test suite.
- [ ] Confirm the Streamlit service reads the rebuilt database without errors.
