# Six Isolated NP-001 Core Calls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate, audit, and sequentially execute six one-slot NP-001 extraction requests.

**Architecture:** Reuse the approved core-slot builder, compact evidence selection, dynamic schema, exact-byte guard, and scientific validator. Add one focused sequential runner whose preflight emits six independent manifests and whose execution stops on provider ambiguity.

**Tech Stack:** Python 3.14, pytest, OpenAI Responses API, existing compact/core-slot modules.

## Global Constraints

- Exactly six named slots in the approved order.
- One slot and only `extracted` per request.
- No batching, retries, repair, vision, or automatic merging.
- Distinct exact hashes and durable markers per call.
- At most six provider calls.

---

### Task 1: One-slot preflight and sequential runner

**Files:**
- Create: `src/extraction/run_isolated_core_slot_calls.py`
- Create: `tests/test_isolated_core_slot_calls.py`

**Interfaces:**
- Produces `preflight_isolated_core_calls(...)` and `run_approved_isolated_core_calls(...)`.
- Reuses `build_np001_core_slots`, compact packet selection, dynamic schema,
  exact-byte verification, and `validate_core_slot_response`.

- [ ] Write failing tests proving six ordered, one-slot, extracted-only exact requests.
- [ ] Implement preflight and confirm each schema/evidence/hash audit passes.
- [ ] Write fake-provider tests proving strictly sequential dispatch, six-call cap, durable per-call markers, stop on ambiguity, and local validation.
- [ ] Implement the minimal runner with `max_retries=0` supplied by the caller.
- [ ] Run focused and relevant regression tests with credentials cleared.
- [ ] Commit source/test only.
- [ ] Generate the six real request JSON files and verify zero provider calls.
- [ ] Execute the six user-approved calls sequentially and persist every result.
