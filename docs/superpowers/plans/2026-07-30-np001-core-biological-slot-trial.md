# NP-001 Core Biological Slot Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated NP-001 trial that requires every locally pre-qualified biological outcome slot to link to a scientifically compatible experiment and outcome.

**Architecture:** Add one pure-local module that builds six closed NP-001 slot specifications, qualifies them from exact evidence, constructs a dynamic no-escape schema, and validates returned links. Add one isolated runner that reuses the existing compact packet and exact-byte one-call boundary, writes a zero-call preview, and never changes production or the 36-candidate trial.

**Tech Stack:** Python 3.14, Pydantic, pytest, existing compact contracts and exact-request runner patterns.

## Global Constraints

- Trial paper is exactly `NP-001`.
- Possible slot IDs are exactly `CORE-HEPG2-TRANSFECTION`, `CORE-DC24-TRANSFECTION`, `CORE-DC24-IMMUNE`, `CORE-HPBMC-TRANSFECTION`, `CORE-HPBMC-IMMUNE`, and `CORE-MOUSE-BIODISTRIBUTION`.
- Only locally qualified slots are sent.
- Sent slots permit only `extracted` or `duplicate`; no unresolved disposition exists in the schema.
- Every sent slot requires one linked experiment ID, at least one linked outcome ID, and slot-allowed evidence IDs.
- Scientific validation, not schema validity, determines acceptance.
- Do not modify the production compact route or the 36-candidate trial.
- Do not make provider, repair, vision, or network calls during implementation.
- Do not stage generated NP-001 artifacts.

---

### Task 1: Core-slot qualification, schema, and scientific validator

**Files:**
- Create: `src/extraction/core_biological_slots.py`
- Create: `tests/test_core_biological_slots.py`
- Reference: `src/extraction/compact_contracts.py`
- Reference: `src/extraction/primary_candidate_accounting.py`

**Interfaces:**
- Consumes: a compact packet dictionary and a compact extraction response dictionary.
- Produces: `build_np001_core_slots(packet: Mapping[str, Any]) -> dict[str, Any]`, `build_core_slot_schema(core_schema: Mapping[str, Any], qualified_slots: Sequence[Mapping[str, Any]]) -> dict[str, Any]`, and `validate_core_slot_response(response: Mapping[str, Any], qualified_slots: Sequence[Mapping[str, Any]], evidence_envelope: set[str]) -> dict[str, Any]`.

- [ ] **Step 1: Write failing qualification tests**

Create compact NP-001 fixtures containing formulation/payload/model/outcome evidence for all six possible slots. Assert that the builder returns an ordered evaluation for all six, with `qualified`, `evidence_ids`, `model_family`, `outcome_family`, and an explicit exclusion reason when any of the four required evidence categories is absent. Assert SAXS, morphology, size, PDI, zeta potential, stability, and release-only evidence never qualifies a slot.

- [ ] **Step 2: Run qualification tests and confirm RED**

```bash
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_core_biological_slots.py
```

Expected: collection failure because the module does not exist.

- [ ] **Step 3: Implement the closed NP-001 slot builder**

Define immutable slot specifications with exact model aliases and outcome-family keywords. Scan evidence records deterministically, retain exact evidence IDs by category, qualify only when formulation/payload/model/outcome categories are non-empty, and return evaluated plus qualified slot lists. Do not call an LLM and do not infer arbitrary-paper slots.

- [ ] **Step 4: Run qualification tests and confirm GREEN**

Run the command from Step 2.

- [ ] **Step 5: Write failing dynamic-schema tests**

Assert the generated strict schema:

- preserves every current compact response field;
- adds required `core_slot_contract_version` and `core_slot_accounting`;
- requires exactly the qualified slot IDs;
- forbids additional slot keys and entry fields;
- permits only `extracted` and `duplicate`;
- requires `disposition`, `linked_experiment_id`, `linked_outcome_ids`, and `evidence_ids`;
- requires at least one linked outcome and one evidence ID.

- [ ] **Step 6: Implement the dynamic no-escape schema**

Use a deep copy of the existing strict compact schema. Add a closed object keyed by qualified slot IDs and a shared strict entry definition. Set the contract version to `compact-core-slot-trial-1.0.0`.

- [ ] **Step 7: Write failing scientific-validation tests**

Cover:

- exact slot-key equality;
- nonexistent experiment/outcome IDs;
- duplicate outcome IDs in the compact response;
- outcome linked to a different experiment;
- HepG2/DC2.4/hPBMC/mouse cross-links;
- transfection/immune/biodistribution cross-family links;
- evidence outside the slot or request envelope;
- formulation/payload evidence incompatibility;
- valid extracted records;
- duplicate accepted only when another valid slot shares the record;
- invalid claims never counted as confirmed.

- [ ] **Step 8: Implement response parsing and scientific validation**

Strip the two trial-only fields and validate the core body with `CompactExtractionResponse`. Normalize model and outcome-family aliases locally. Return a JSON-serializable report with sent, accounted, scientifically confirmed, valid duplicates, rejected links, confirmed slot IDs, and explicit errors.

- [ ] **Step 9: Run focused and production-isolation tests**

```bash
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_core_biological_slots.py tests/test_primary_candidate_accounting.py tests/test_compact_one_call.py
```

- [ ] **Step 10: Commit Task 1**

Stage only the new module/test and commit `feat: add NP-001 core biological slots`.

### Task 2: Exact-request core-slot trial and NP-001 zero-call preview

**Files:**
- Create: `src/extraction/run_core_slot_trial.py`
- Create: `tests/test_core_slot_trial.py`
- Reference: `src/extraction/run_primary_accounting_trial.py`
- Generate, do not commit: `data/staging/extraction/np001_core_slot_trial_preflight/NP-001/`

**Interfaces:**
- Consumes: Task 1 functions and the existing NP-001 compact API packet.
- Produces: `preflight_core_slot_trial(...) -> dict[str, Any]` and `run_approved_core_slot_trial(...) -> dict[str, Any]`.

- [ ] **Step 1: Write failing request/preflight tests**

Using temporary packet/output roots, assert:

- papers other than NP-001 are refused;
- all six possible slots receive a local qualification decision;
- only qualified slots appear in the request and dynamic schema;
- each slot gets a compact exact evidence packet;
- manifest binds packet checksum, slot qualification checksum, schema checksum, model, route/version, and exact request SHA;
- preview shows qualified/excluded slots, input estimate, output cap, one proposed call, and `provider_calls: 0`;
- preflight never instantiates or invokes a provider.

- [ ] **Step 2: Implement isolated request construction and preflight**

Use route `primary-core-biological-slot-trial`, route version `compact-route-1.4.0-trial`, preflight version `compact-core-slot-preflight-1.0.0`, and a separate preflight root. Reuse existing prompt/core-contract helpers only where doing so cannot alter production behavior.

- [ ] **Step 3: Write failing guarded-execution tests**

With fake providers, assert:

- missing approval or mismatched SHA is refused;
- modified request bytes are refused;
- the fake provider receives the exact saved request once;
- a durable exclusive invocation marker is written before dispatch;
- provider failure preserves the marker and blocks another dispatch;
- successful output is parsed through Task 1 validation;
- no retry, repair, or vision call exists;
- completed execution cannot run again.

- [ ] **Step 4: Implement the guarded execution boundary**

Use separate preflight and run roots. Verify every manifest binding and the exact saved bytes before writing the invocation marker. Invoke `client.responses.create(**request)` once. Persist raw response, trial response, compact core result, scientific-validation report, usage, and completed manifest.

- [ ] **Step 5: Run regression verification**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_core_biological_slots.py tests/test_core_slot_trial.py tests/test_primary_candidate_accounting.py tests/test_primary_accounting_trial.py tests/test_compact_one_call.py tests/test_preflight_compact_requests.py tests/test_v12_main_route.py
git diff --check
```

- [ ] **Step 6: Commit Task 2**

Stage only the runner/test and commit `feat: add guarded NP-001 core-slot trial`.

- [ ] **Step 7: Generate the real zero-call NP-001 preview**

Run only the preflight command against the existing NP-001 compact API packet. Verify:

- provider calls equal zero;
- every evaluated slot has a decision;
- every sent slot meets the four-part threshold;
- schema required keys exactly equal qualified slot IDs;
- request bytes match the manifest SHA;
- no run invocation marker or response exists.

- [ ] **Step 8: Request independent whole-branch review**

Review production isolation, qualification accuracy, no-escape schema, scientific compatibility checks, exact-byte approval, at-most-one dispatch, and fake-provider test coverage. Fix verified findings and rerun Step 5.

- [ ] **Step 9: Stop for explicit paid-call approval**

Present exact qualified/excluded slots, request path, SHA-256, estimated input tokens, output cap, proposed calls `1`, and provider calls so far `0`. Do not call the provider.
