# Assay Alias and Experimental Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct ddPCR normalization and represent experimental animal models independently from disease models before preparing the next NP-002 request.

**Architecture:** Extend the compact experiment contract with one backward-compatible field, require it in new strict API schemas, update prompt semantics, and validate approved arm models against that field. Keep disease-model semantics unchanged.

**Tech Stack:** Python 3.14, Pydantic, OpenAI strict JSON schema, pytest

## Global Constraints

- Do not call any paid API.
- Do not treat generic PCR or qPCR as ddPCR.
- Do not place Ai14 Cre-reporter mice in `disease_model`.
- Pause after preflight and token estimation for explicit human approval.

---

### Task 1: Normalize ddPCR assay names

**Files:**
- Modify: `src/extraction/experimental_arms.py`
- Test: `tests/test_experimental_arms.py`

- [ ] Write parameterized failing tests for `digital droplet PCR` and `droplet digital PCR`, plus a retained rejection test for `qPCR`.
- [ ] Run the focused tests and verify RED.
- [ ] Add a narrow assay canonicalizer and use it in the QUANT arm check.
- [ ] Run the focused tests and verify GREEN.

### Task 2: Separate experimental and disease models

**Files:**
- Modify: `src/extraction/compact_contracts.py`
- Modify: `src/extraction/compact_prompt_v1.py`
- Modify: `src/extraction/experimental_arms.py`
- Test: `tests/test_compact_contracts.py`
- Test: `tests/test_experimental_arms.py`
- Test: `tests/test_np002_kupffer_arm_benchmark.py`

- [ ] Write failing tests requiring `experimental_model` in the strict schema and matching approved arms against it while allowing a missing disease model.
- [ ] Run the focused tests and verify RED.
- [ ] Add the backward-compatible contract field, prompt distinction, evidence projection, and validator mapping.
- [ ] Update controlled test responses to return the approved experimental model.
- [ ] Run the focused tests and verify GREEN.

### Task 3: Verify and prepare approval artifacts

**Files:**
- Read: existing signed NP-002 review artifacts
- Create: a new versioned NP-002 preflight directory

- [ ] Run the full local test suite.
- [ ] Revalidate a locally corrected copy of the saved response to isolate the two intended changes without modifying the original artifact.
- [ ] Generate a fresh preflight request from the signed review without invoking the provider.
- [ ] Report request hash, estimated input tokens, maximum output tokens, and one-call scope.
- [ ] Stop for explicit human approval.
