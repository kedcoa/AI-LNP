# Primary Forced Candidate Accounting Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated NP-001 primary extraction trial whose response schema requires an explicit disposition for every supplied atomic candidate, validate every claimed link locally, and prepare—but do not send—one exact paid-call request for human approval.

**Architecture:** Add one focused, pure-local accounting module beside the existing compact contracts. Add a separate NP-001-only trial runner that reuses the existing packet, recall support, evidence audits, exact-request approval boundary, and compact response parser without changing the production `compact-route-1.2.0` path. Persist trial artifacts under explicit trial-only roots and stop after a zero-call preflight.

**Tech Stack:** Python 3.14, Pydantic, pytest, existing compact extraction and v12 structural-validation modules.

## Global Constraints

- Do not change the default `build_openai_request()` bytes or `run_one()` behavior.
- Do not make a provider/API/network call during implementation or verification.
- Do not stage generated NP-001 data or report artifacts.
- Use test-driven development: observe each focused test fail before implementation.
- Keep the implementation focused: one accounting module and one isolated runner module; do not add an orchestrator or production migration.
- The trial must refuse papers other than `NP-001`, refuse unapproved request bytes, and refuse duplicate execution.
- All authoritative accounting and scientific-recovery counts are computed locally.

---

### Task 1: Dynamic accounting schema and deterministic validator

**Files:**

- Create: `src/extraction/primary_candidate_accounting.py`
- Create: `tests/test_primary_candidate_accounting.py`
- Reference: `src/extraction/compact_contracts.py`
- Reference: `src/extraction/v12_main_route.py`

- [ ] **Step 1: Write failing schema tests**

Add tests using two small synthetic candidates that assert:

- the wrapper preserves all required `CompactExtractionResponse` fields;
- `accounting_contract_version` and `candidate_accounting` are required;
- the exact two candidate IDs appear as required properties;
- unknown candidate keys and unknown entry fields are forbidden;
- each entry requires `disposition`, `linked_outcome_ids`, `evidence_ids`, and `reason_code`;
- disposition and reason-code enums equal the approved closed sets.

- [ ] **Step 2: Run the focused schema tests and confirm RED**

Run:

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_primary_candidate_accounting.py
```

Expected: failure because `primary_candidate_accounting` does not exist.

- [ ] **Step 3: Implement the dynamic schema builder**

In `primary_candidate_accounting.py`, add constants for:

```python
ACCOUNTING_CONTRACT_VERSION = "compact-accounting-trial-1.0.0"
TRIAL_ROUTE = "primary-candidate-accounting-trial"
TRIAL_ROUTE_VERSION = "compact-route-1.3.0-trial"
```

Implement a pure function that accepts the existing strict compact schema and ordered candidate records, deep-copies the schema, adds the two trial-only fields, constructs an exact-ID `candidate_accounting` object, and preserves `additionalProperties: false`.

- [ ] **Step 4: Run schema tests and confirm GREEN**

Run the focused test command from Step 2.

- [ ] **Step 5: Write failing parser and validator tests**

Cover:

- exact candidate-key equality;
- missing, extra, and substituted keys;
- duplicate returned outcome IDs;
- linked outcome IDs that do not exist;
- evidence IDs outside the candidate allowance or request envelope;
- extracted with a valid deterministic structural match;
- extracted with an incompatible/random outcome link;
- duplicate with a shared valid outcome and duplicate without another candidate sharing it;
- requires-visual with and without visual provenance;
- malformed/context-only `not_outcome` consistent and inconsistent with diagnostics;
- all candidates explicitly unresolved;
- authoritative summary counts and accounting completeness.

Use tiny local fixtures and monkeypatch only the existing structural comparison boundary when a full scientific fixture would obscure the accounting behavior.

- [ ] **Step 6: Run validator tests and confirm RED**

Run the focused test command and confirm failures identify missing validation behavior.

- [ ] **Step 7: Implement trial response parsing and local validation**

Implement:

- parsing that removes `accounting_contract_version` and `candidate_accounting`, then validates the remaining body with `CompactExtractionResponse`;
- exact set, outcome-ID, and evidence-envelope validation;
- disposition-specific validation;
- structural-link validation by reusing the current deterministic candidate/outcome comparison boundary;
- a JSON-serializable evaluation report containing sent, accounted, valid extracted, valid duplicates, rejected links, unresolved disposition counts, unique outcomes, structurally confirmed candidates, and explicit errors.

Invalid scientific links must be recorded as rejected and never counted as structurally confirmed.

- [ ] **Step 8: Run focused tests and confirm GREEN**

Run the focused test command.

- [ ] **Step 9: Verify production schema remains unchanged**

Add or reuse a regression assertion in `tests/test_compact_one_call.py` that the default request does not contain either trial-only field and retains route version `compact-route-1.2.0`.

Run:

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_primary_candidate_accounting.py tests/test_compact_one_call.py
```

- [ ] **Step 10: Commit Task 1**

Stage only the two implementation/test files and any focused regression-test edit. Commit:

```text
feat: add forced primary candidate accounting
```

### Task 2: NP-001-only exact-request preflight and guarded runner

**Files:**

- Create: `src/extraction/run_primary_accounting_trial.py`
- Create: `tests/test_primary_accounting_trial.py`
- Reference: `src/extraction/run_compact_one_call.py`
- Reference: `src/extraction/preflight_compact_requests.py`
- Reference: `src/extraction/v12_main_route.py`

- [ ] **Step 1: Write failing isolated-request tests**

Test with temporary packet/output roots and a fake provider:

- only `NP-001` is accepted;
- the current compact packet and ordered atomic candidates build the trial schema;
- the request uses trial route/version and the existing core contract version;
- the request output cap is 12,000;
- the request contains all candidate facts and exact dynamic schema;
- the default production request remains unchanged;
- the request manifest binds packet checksum, candidate-facts checksum, dynamic-schema checksum, model, route/version, and exact request SHA-256.

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_primary_accounting_trial.py
```

- [ ] **Step 3: Implement the isolated trial request builder**

Reuse existing compact request construction helpers where they are pure, but expose a separate explicit trial entry point. Build recall support once, preserve the ordered 36-candidate inventory, include concise instructions defining all dispositions, and bind the exact request dictionary and checksums in a trial-only manifest.

Do not add flags to silently switch the production route.

- [ ] **Step 4: Run request tests and confirm GREEN**

Run the focused test command.

- [ ] **Step 5: Write failing preflight and execution-boundary tests**

Test:

- preflight writes exact request JSON, audits, human-readable preview, and signed manifest with `provider_calls: 0`;
- preview reports request path, SHA-256, estimated input tokens, 12,000 output cap, 36 candidates, and proposed paid calls `1`;
- preflight refuses any paper other than NP-001;
- execution refuses absent approval, mismatched approval SHA, modified request bytes, and an existing completed call;
- a fake approved provider receives exactly the approved request dictionary once;
- no automatic retry, repair, or vision call occurs;
- fake response is parsed and evaluated through Task 1’s validator into trial-only artifacts.

- [ ] **Step 6: Run boundary tests and confirm RED**

Run the focused test command.

- [ ] **Step 7: Implement preflight and guarded execution**

Add CLI subcommands or explicit functions:

```text
preflight --paper-id NP-001 --packet ... --output-root ...
run-approved --paper-id NP-001 --manifest ... --approved-request-sha256 ...
```

The default action must be preflight. `run-approved` must verify the saved bytes and approval SHA before invoking the provider exactly once. It must refuse duplicate completed execution and must not invoke repair or vision routes.

- [ ] **Step 8: Run focused tests and confirm GREEN**

Run the focused test command.

- [ ] **Step 9: Run the relevant regression suite**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_primary_candidate_accounting.py tests/test_primary_accounting_trial.py tests/test_compact_one_call.py tests/test_preflight_compact_requests.py tests/test_v12_main_route.py
```

Confirm no network/provider call is possible because credentials are cleared and all provider behavior is faked.

- [ ] **Step 10: Commit Task 2**

Stage only the isolated runner and its test file. Commit:

```text
feat: add guarded NP-001 accounting trial
```

### Task 3: Produce and inspect the zero-call NP-001 approval preview

**Files:**

- Generate, do not commit: trial-only preflight artifacts beneath a new explicit `data/staging/extraction/np001_primary_accounting_trial_preflight/` root
- Inspect: current NP-001 packet and candidate inventory

- [ ] **Step 1: Run the local preflight**

Invoke the new preflight for NP-001 using the existing compact API packet. Do not invoke `run-approved`.

- [ ] **Step 2: Inspect the persisted manifest and request**

Verify locally:

- `provider_calls` is exactly `0`;
- sent candidate count is exactly `36`;
- candidate keys equal the current ordered inventory;
- the schema requires exactly those 36 accounting keys;
- the request and manifest SHA-256 values agree;
- output cap is 12,000;
- route/version and accounting version match the design;
- no production artifact was modified.

- [ ] **Step 3: Run full verification before claiming readiness**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_primary_candidate_accounting.py tests/test_primary_accounting_trial.py tests/test_compact_one_call.py tests/test_preflight_compact_requests.py tests/test_v12_main_route.py
git diff --check
git status --short
```

- [ ] **Step 4: Request independent code review**

Ask a fresh reviewer to check the complete branch against the approved design, focusing on production isolation, schema enforcement, scientific-link validation, exact-byte approval, duplicate-call refusal, and accidental provider calls. Resolve verified issues using systematic debugging and rerun verification.

- [ ] **Step 5: Stop for human approval**

Present:

- exact request path;
- exact request SHA-256;
- candidate count;
- estimated input tokens;
- 12,000-token output cap;
- proposed paid calls: 1;
- confirmation that provider calls so far remain 0.

Do not make the paid call until the user explicitly approves that exact preview.
