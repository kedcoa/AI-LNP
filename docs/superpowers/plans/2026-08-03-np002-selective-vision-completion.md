# NP-002 Selective-Vision Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete NP-002 with two qualitative selective-vision calls, merge their outcomes with the v5.2 paper map, and calculate a full-paper benchmark score.

**Architecture:** Add one narrow NP-002 benchmark module that prepares immutable Figure 2 and Figure 4 requests from source evidence, validates exact slot accounting, dispatches only explicitly approved request bytes, and merges validated responses. Reuse the committed paper map and hidden evaluator; do not add a general orchestration layer or repeat the paper-map call.

**Tech Stack:** Python 3.14, Pydantic, PyMuPDF, OpenAI Responses API, pytest, existing full-paper evaluator.

## Global Constraints

- Exactly two independently hashed requests: Figure 2 and Figure 4.
- Figure 2 has six source-derived slots: two formulations by three recipient cell classes.
- Figure 4 has twelve source-derived slots: two formulations by two doses by three recipient cell classes.
- Extract qualitative outcomes and exact values only when explicitly printed; never estimate a number from an axis or bar height.
- Every slot is accounted for exactly once as `extracted` or `not_explicit`.
- Evidence citations are restricted to the crop, caption, referring Results passages, and Methods context supplied in that request.
- The hidden answer key is never loaded by preparation, execution, validation, or merge code; only the final evaluator loads it.
- Preflight makes zero provider calls. Paid calls run sequentially, only for exact approved SHA-256 values, with no retries.

---

### Task 1: Build immutable two-figure preflights and strict response validation

**Files:**
- Create: `src/extraction/run_np002_selective_outcomes.py`
- Create: `tests/test_np002_selective_outcomes.py`

**Interfaces:**
- Produces: `prepare(output_root: Path, model: str) -> dict[str, Any]`
- Produces: `validate_visual_response(response: Mapping[str, Any], task: Mapping[str, Any]) -> None`
- Produces: two request JSON files, two task JSON files, two crop PNGs, and one zero-call manifest.

- [ ] **Step 1: Write failing contract tests**

Add tests proving preparation creates Figure 2 and Figure 4 tasks with exactly
six and twelve unique slot IDs; both Cre doses are present; no gold path or gold
content is accessed; preparation uses a fake client that raises if called; and
every request has a deterministic SHA-256.

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```bash
OPENAI_API_KEY= PYTHONPATH=.:/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_np002_selective_outcomes.py
```

Expected: failure because `run_np002_selective_outcomes` does not exist.

- [ ] **Step 3: Implement source-grounded task preparation**

Implement Pydantic models for slots, outcome rows, accounting entries, and
figure responses. Render verified Figure 2 and Figure 4 crops from the committed
PDF using PyMuPDF. Select captions, Results passages, and Methods context from
the committed HTML/source-native inventory. Build strict JSON schemas whose
`slot_accounting` object requires the exact task slot IDs. The prompts must state
that qualitative comparisons are desired and visually estimated numbers are
forbidden.

- [ ] **Step 4: Add adversarial validation tests**

Test rejection of missing slots, invented slots, duplicate returned outcome
links, unaccounted returned rows, changed formulation/payload/dose/recipient,
unknown evidence IDs, numeric values without `exact_printed_support`, and
`not_explicit` entries that link outcomes.

- [ ] **Step 5: Implement minimal validation and make tests GREEN**

Validate response schema, exact accounting, identity preservation, evidence
envelopes, and numeric safety. Persist canonical request bytes, SHA-256, crop
checksums, estimated text/image input usage, and output caps. Use 4,000 output
tokens for Figure 2 and 6,000 for Figure 4.

- [ ] **Step 6: Run focused and related tests**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.:/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_np002_selective_outcomes.py tests/test_day4_afternoon_selective_vision.py tests/test_full_paper_benchmark.py
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/extraction/run_np002_selective_outcomes.py tests/test_np002_selective_outcomes.py
git commit -m "feat: prepare NP-002 qualitative vision calls"
```

### Task 2: Execute approved calls, merge, and evaluate

**Files:**
- Modify: `src/extraction/run_np002_selective_outcomes.py`
- Modify: `tests/test_np002_selective_outcomes.py`

**Interfaces:**
- Produces: `run_approved(manifest_path: Path, approvals: Mapping[str, str], output_root: Path, client: Any | None = None) -> dict[str, Any]`
- Produces: `merge_validated(manifest_path: Path, run_root: Path, output_path: Path) -> dict[str, Any]`

- [ ] **Step 1: Write failing execution-boundary tests**

Use a fake Responses client to prove that request bytes must match the approved
SHA-256, calls run Figure 2 then Figure 4, existing invocation markers prevent
duplicates, provider exceptions stop without retry, and a failed Figure 2 call
prevents Figure 4 dispatch.

- [ ] **Step 2: Implement the approval boundary**

Re-read immutable request bytes immediately before each call, verify the
approved SHA-256 and crop checksum, create an exclusive invocation marker,
dispatch with `OpenAI(max_retries=0)`, persist raw response and usage, parse and
validate the structured result, then proceed to the next call only after the
first is valid.

- [ ] **Step 3: Write failing merge tests**

Prove the merger attaches each visual outcome to its exact formulation,
payload, dose, recipient, assay, endpoint, comparison, and evidence; retains
shared paper facts from the v5.2 map; represents qualitative-only measurements
with a null numeric value; and does not read the answer key.

- [ ] **Step 4: Implement merge and local benchmark adapter**

Write one merged extraction artifact compatible with
`evaluate_full_paper_benchmark.evaluate()`. Keep shared ratios paper-level and
do not infer the exact QUANT formulation recipe onto Cre arms. The CLI may run
the hidden evaluator only as a distinct final command after the merged artifact
exists.

- [ ] **Step 5: Run focused tests and full verification**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.:/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q
```

Expected: complete suite passes with no provider calls.

- [ ] **Step 6: Prepare real NP-002 requests with zero calls**

Run the preflight CLI, inspect both crop PNGs, verify exact slot counts, and
report for each call: model, crop, request SHA-256, estimated input tokens,
output cap, and maximum total tokens. Confirm the manifest reports
`provider_calls: 0`.

- [ ] **Step 7: Pause for explicit paid-call approval**

Do not dispatch either call until the human explicitly approves the displayed
request hashes. Approval of this implementation plan is not paid-call approval.

- [ ] **Step 8: After approval, execute sequentially and evaluate**

Run the exact approved requests, merge validated outputs, then execute the
hidden evaluator locally. Report actual provider usage, extracted qualitative
outcomes, overall/shared/experiment/complete-arm recall, precision, unsupported
inventions, wrong-arm links, and any `not_explicit` slots.

- [ ] **Step 9: Commit Task 2 artifacts and code**

```bash
git add src/extraction/run_np002_selective_outcomes.py tests/test_np002_selective_outcomes.py data/staging/extraction/np002_selective_outcomes_preflight data/staging/extraction/np002_selective_outcomes_run reports/extraction
git commit -m "feat: complete NP-002 selective vision extraction"
```
