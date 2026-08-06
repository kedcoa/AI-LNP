# SQLite Human-Review Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fictional Streamlit state with a safe service over the authoritative SQLite database, including real metrics, persistent review decisions, immutable history, and immediate eligibility recalculation.

**Architecture:** A pure `review_service` module is the only UI-facing database boundary. Reads use fixed-path read-only SQLite connections; writes use short transactions, optimistic stale-state checks, evidence-ownership validation, immutable `review_revision` inserts, field verification updates, and the existing deterministic status/eligibility engine. The Streamlit entrypoint renders service DTOs and never executes SQL.

**Tech Stack:** Python 3, SQLite, Streamlit, pytest, existing `src.database.status` evaluators.

## Global Constraints

- Use `/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db` as the only authoritative database.
- Make zero API, LLM, Codex CLI, DOI, or publisher calls.
- Preserve original extraction and evidence; corrections are additive review revisions.
- Require a reviewer note for every decision and supporting evidence for corrections.
- Refuse writes unless integrity, schema, foreign keys, and an external verified backup pass.

---

### Task 1: Read-only review service and exact metrics

**Files:**
- Create: `src/ui/review_service.py`
- Test: `tests/test_review_service.py`

**Interfaces:**
- Produces: `authoritative_database_path() -> Path`, `load_dashboard() -> DashboardMetrics`, `list_paper_summaries() -> tuple[PaperSummary, ...]`, `list_review_arms() -> tuple[ReviewArm, ...]`, and `load_arm_workspace(experiment_id: int) -> ArmWorkspace`.

- [ ] Write fixture-backed tests for canonical database-path resolution, COMET/nearest-neighbor counts, deduplicated usable facts split by verification status, exact per-paper physical row counts, queue ordering, explicit blank fields, linked evidence, and history.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_review_service.py` and confirm the missing service fails.
- [ ] Implement immutable DTOs and parameterized read-only queries; verify evidence belongs to the selected paper and use the latest eligibility row.
- [ ] Run the focused test and confirm it passes.

### Task 2: Transactional review decisions and eligibility refresh

**Files:**
- Modify: `src/ui/review_service.py`
- Modify: `tests/test_review_service.py`

**Interfaces:**
- Produces: `prepare_writes(backup_dir: Path) -> WriteReadiness` and `apply_review_decision(request: ReviewDecision) -> ReviewResult`.

- [ ] Add failing tests for accept, correct, not-reported, rejected, wrong-arm, and unresolved decisions; original evidence preservation; immutable history; supersession; stale state; cross-paper evidence; rollback; and eligibility recalculation.
- [ ] Run the focused tests and confirm each new behavior fails for the expected missing implementation.
- [ ] Implement one `BEGIN IMMEDIATE` transaction per decision, validated revision/history writes, verification/missing-field updates, existing deterministic status and eligibility recalculation, consistency checks, and rollback on failure.
- [ ] Add and test a write-readiness gate using SQLite integrity, schema version, foreign keys, and a verified external backup marker.
- [ ] Run the focused test and confirm it passes.

### Task 3: Connect the approved Streamlit workspace

**Files:**
- Create: `src/ui/review_app.py`
- Test: `tests/test_review_app.py`

**Interfaces:**
- Consumes: all Task 1 and Task 2 review-service interfaces.

- [ ] Write failing static/UI-contract tests proving the page uses only the service layer and includes real dashboard metrics, per-paper row counts, queue filters, links, arm fields, evidence inspector, reviewer/note inputs, six decisions, history, and post-save eligibility.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_review_app.py` and confirm failure.
- [ ] Adapt the approved demo layout to real DTOs, replace fictional warnings with database/readiness status, and disable submit until review requirements are satisfied.
- [ ] Run the focused UI tests and confirm they pass.

### Task 4: Authoritative preflight and end-to-end verification

**Files:**
- Modify if required: `src/ui/review_service.py`
- Modify if required: `src/ui/review_app.py`
- Test: `tests/test_review_service.py`
- Test: `tests/test_review_app.py`

- [ ] Run read-only preflight against the authoritative database and record the two requested totals plus every paper's row counts without changing the database.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_review_service.py tests/test_review_app.py tests/test_database_status.py tests/test_database_migrations.py`.
- [ ] Launch Streamlit on port 8506 and inspect dashboard, filters, arm selection, evidence, history, disabled unsafe writes, and one fixture-backed review flow.
- [ ] Run the complete offline suite with all provider keys blank and report any unrelated pre-existing failures separately.

## Completion Gate

The work is complete when the UI reads the fixed authoritative SQLite database, shows exact COMET-ready and usable-fact totals plus per-paper row counts, persists valid decisions with immutable history, recalculates eligibility atomically, rejects unsafe/stale submissions, passes focused verification, and makes zero paid extraction calls.
