# Streamlit Human-Review Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a locally runnable, interactive Streamlit review-workspace demo using fictional data and no connection to the authoritative SQLite database.

**Architecture:** A pure Python demo-state module owns fictional papers, arms, evidence, review decisions, and illustrative eligibility calculations. A separate Streamlit entrypoint renders a queue-first workspace and stores edits only in `st.session_state`; tests exercise the state module and statically enforce isolation from real database paths.

**Tech Stack:** Python 3.14, Streamlit 1.59.2, dataclasses, pytest.

## Global Constraints

- Finish the focused prototype in approximately 45–60 minutes.
- Never read from or write to `data/curated/lnp_evidence.db`.
- Make no API, Codex, LLM, DOI, publisher, or institutional-library network call.
- Use fictional paper metadata, scientific values, links, and evidence excerpts.
- Persist decisions only in Streamlit session state.
- Label the eligibility calculation as an interface simulation, not production eligibility logic.

---

### Task 1: Mock review model and interaction logic — 15–20 minutes

**Files:**
- Create: `src/ui/review_demo_state.py`
- Create: `src/ui/__init__.py`
- Create: `tests/test_review_demo_state.py`

**Interfaces:**
- Produces: `demo_papers() -> tuple[DemoPaper, ...]`, `queue_items(papers, filters) -> tuple[DemoArm, ...]`, `apply_decision(arm, field_name, action, corrected_value=None) -> DemoArm`, and `simulate_eligibility(arm) -> EligibilityPreview`.

- [ ] **Step 1 — 5 minutes: Write failing tests.** Assert three fictional queue items cover confirmation, missing, and conflict states; filters narrow the queue; accepting/correcting/not-reported/unresolved decisions change only copied mock state; eligibility reasons update; no source file contains SQLite imports or the curated database path.
- [ ] **Step 2 — 2 minutes: Run RED.**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_review_demo_state.py
```

- [ ] **Step 3 — 8 minutes: Implement the immutable demo model.** Use frozen dataclasses and `dataclasses.replace`; include mock paper-access labels, editable arm fields, evidence excerpts, status labels, and separate nearest-neighbor/COMET reason lists.
- [ ] **Step 4 — 3 minutes: Run GREEN and commit.**

```bash
git add src/ui tests/test_review_demo_state.py
git commit -m "feat: model mock evidence review"
```

### Task 2: Queue-first Streamlit workspace — 25–35 minutes

**Files:**
- Create: `src/ui/review_demo_app.py`
- Create: `tests/test_review_demo_app.py`

**Interfaces:**
- Consumes: all Task 1 functions and models.
- Produces: locally runnable app via `streamlit run src/ui/review_demo_app.py`.

- [ ] **Step 1 — 5 minutes: Write failing UI-contract tests.** Assert the entrypoint contains the demo-only warning, review queue, paper-access section, arm editor, evidence inspector, review actions, eligibility preview, and reset control; reject SQLite/API/network imports and real source paths.
- [ ] **Step 2 — 2 minutes: Run RED.**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_review_demo_app.py
```

- [ ] **Step 3 — 15 minutes: Implement the Streamlit workspace.** Use a wide layout, restrained CSS, summary cards, sidebar filters and queue, mock access buttons, editable fields, status chips, field-selected evidence, decision controls, and simulated eligibility. Store the selected arm and edited copies only in session state.
- [ ] **Step 4 — 5 minutes: Run focused tests and a headless smoke launch.**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_review_demo_state.py tests/test_review_demo_app.py
.venv/bin/streamlit run src/ui/review_demo_app.py --server.headless true --server.port 8506
```

- [ ] **Step 5 — 5 minutes: Inspect the local page in the browser.** Confirm the demo banner, queue selection, editing, evidence switching, decisions, reset, and eligibility preview work without horizontal page scrolling.
- [ ] **Step 6 — 3 minutes: Run the complete offline suite and commit.**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q
git add src/ui tests/test_review_demo_app.py
git commit -m "feat: demo evidence review workspace"
```

## Completion Criteria

The demo opens locally, visibly identifies itself as fictional and disconnected, supports interactive mock review decisions and simulated eligibility changes, contains no real paper/database integration, passes focused and full offline tests, and is ready for visual feedback rather than production use.
