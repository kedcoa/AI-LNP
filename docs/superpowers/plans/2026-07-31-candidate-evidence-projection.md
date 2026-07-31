# Candidate Evidence Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate each experimental arm against evidence inside its own approved packet without rejecting harmless extra citations carried by shared records.

**Architecture:** Keep the raw extraction unchanged. Project each linked scientific evidence group into the candidate's allowed envelope, require in-envelope support for every group, and make top-level accounting citations supplementary rather than duplicative.

**Tech Stack:** Python 3.14, pytest, JSON benchmark artifacts

## Global Constraints

- Do not invoke an API client or modify the saved LLM response.
- Preserve rejection when a required scientific field has only wrong-arm evidence.
- Do not change extraction prompts, response schemas, or approved arm definitions.

---

### Task 1: Candidate-specific evidence validation

**Files:**
- Modify: `src/extraction/experimental_arms.py`
- Modify: `src/extraction/run_np002_kupffer_arm_benchmark.py`
- Test: `tests/test_experimental_arms.py`
- Test: `tests/test_np002_kupffer_arm_benchmark.py`

**Interfaces:**
- Consumes: linked formulation, experiment, and outcome evidence groups plus `arm_evidence[candidate_id]`
- Produces: confirmation only when every required group intersects the candidate envelope

- [ ] **Step 1: Write failing regression tests**

Add tests proving that a short accounting list passes when linked fields are supported, shared records may carry harmless extra approved citations, and exclusively wrong-arm evidence still fails.

- [ ] **Step 2: Run focused tests and verify RED**

Run:
`OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_experimental_arms.py tests/test_np002_kupffer_arm_benchmark.py`

Expected: the new short-accounting and shared-record tests fail under the current flat-list rules.

- [ ] **Step 3: Implement the minimal projection**

Pass an optional candidate evidence envelope into scientific validation. For every required evidence group, require an intersection with the candidate envelope. Remove the requirement that accounting citations intersect every group. In the scoped wrapper, reject only evidence groups with no in-envelope support, not records containing any extra citation.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the focused command from Step 2. Expected: all tests pass.

- [ ] **Step 5: Commit**

Commit the validator and regression tests with message:
`fix: project scientific evidence by candidate`

### Task 2: Saved-response replay and regression verification

**Files:**
- Modify only if needed: `src/extraction/run_np002_kupffer_arm_benchmark.py`
- Read: `data/staging/extraction/np002_kupffer_arm_benchmark_run/NP-002/trial_response.json`
- Read: approved NP-002 preflight artifacts

**Interfaces:**
- Consumes: the existing saved API response and approved six-arm evidence envelopes
- Produces: a fresh local validation report without an API request

- [ ] **Step 1: Run the validator directly over the saved response**

Use the benchmark's existing validation functions and approved preflight data; do not call `client.responses.create`.

- [ ] **Step 2: Inspect all remaining validation errors**

Confirm that any remaining rejection identifies a scientifically missing or wrong-arm field rather than citation duplication.

- [ ] **Step 3: Run the full test suite**

Run:
`OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 4: Report exact replay counts**

Report accounted, structurally valid, scientifically confirmed, tracer-extractable, and RNA-recommendation-eligible counts, plus the exact evidence for any remaining failure.
