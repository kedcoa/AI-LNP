# Six-Arm Payload-Role Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a zero-call NP-002 benchmark request in which all six Kupffer-cell arms are scientifically extractable, QUANT DNA is represented as a biodistribution tracer, and every arm receives dose- and formulation-specific evidence.

**Architecture:** Extend the existing compact experiment record with one closed, evidence-grounded `payload_role` field. Keep the LLM responsible for scientific facts and extend the existing deterministic arm validator to derive delivery-evidence and RNA-recommendation eligibility per confirmed candidate. Reuse the existing human-review, strict-schema, evidence-envelope, SHA-binding, and one-call runner; change no ingestion or orchestration code.

**Tech Stack:** Python 3.14, Pydantic, OpenAI Structured Outputs, pytest, SHA-256-bound JSON artifacts.

## Global Constraints

- Keep canonical candidate IDs KUP-01 through KUP-06.
- KUP-01/02 are QUANT-DNA biodistribution-tracer arms.
- KUP-03/04 are 1.0 mg/kg Cre-mRNA reporter arms.
- KUP-05/06 are 0.3 mg/kg Cre-mRNA reporter arms.
- The LLM reports payload role; deterministic code derives platform eligibility.
- Do not modify ingestion, add an orchestrator, or add repair/vision/retry calls.
- Tests run with `OPENAI_API_KEY=` and `SENSENOVA_API_KEY=`.
- Do not contact a provider during implementation or preflight.
- Do not commit generated review/preflight/run artifacts, the PDF, or `.env`.

---

### Task 1: Add the payload-role extraction fact

**Files:**
- Modify: `src/extraction/compact_contracts.py`
- Modify: `src/extraction/compact_prompt_v1.py`
- Modify: `tests/test_compact_contracts.py`
- Modify: compact-response fixtures that instantiate `ExperimentRecord`

**Interfaces:**
- Consumes: existing evidence-grounded `ExperimentRecord`.
- Produces: required `payload_role: ReportedField[Literal["therapeutic", "reporter", "biodistribution_tracer", "screening_barcode"]]`.

- [ ] **Step 1: Write failing contract tests**

Add a reported `payload_role` to the valid fixture and test that the four
allowed roles validate while an invented role fails. Add a schema assertion
that the strict experiment schema requires `payload_role`.

- [ ] **Step 2: Run the focused contract tests and verify RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_compact_contracts.py
```

Expected: the fixture or schema assertion fails because `payload_role` is not
part of `ExperimentRecord`.

- [ ] **Step 3: Implement the minimal contract and prompt change**

Add the required reported field after `payload_name`. Update the compact prompt
to allow directly reported RNA and validated tracer/barcode payloads, require
the exact role, and forbid treating tracer evidence as therapeutic RNA
evidence. Bump `PROMPT_VERSION`; do not change ingestion.

- [ ] **Step 4: Update existing test fixtures mechanically**

For every compact response fixture, add an evidence-grounded role consistent
with its payload. Use `reporter` for reporter mRNA fixtures unless the fixture
explicitly represents therapy; use `biodistribution_tracer` for QUANT DNA.

- [ ] **Step 5: Run compact-contract and prompt-route tests**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_compact_contracts.py tests/test_compact_prompt_route.py
```

- [ ] **Step 6: Commit Task 1**

```bash
git add src/extraction/compact_contracts.py src/extraction/compact_prompt_v1.py tests
git commit -m "feat: classify extracted payload roles"
```

### Task 2: Validate payload role and derive policy eligibility

**Files:**
- Modify: `src/extraction/experimental_arms.py`
- Modify: `tests/test_experimental_arms.py`

**Interfaces:**
- Consumes: linked experiment records containing `payload_type`, `payload_name`, and `payload_role`.
- Produces: `extractable_delivery_candidate_ids`, `rna_recommendation_eligible_candidate_ids`, and per-candidate eligibility flags in the existing validation report.

- [ ] **Step 1: Write failing six-arm policy tests**

Extend the valid six-arm response so QUANT DNA reports
`biodistribution_tracer` and Cre mRNA reports `reporter`. Assert all six are
scientifically confirmed and extractable, but only KUP-03 through KUP-06 are
RNA-recommendation eligible.

Add negative tests:

- QUANT DNA reported as `therapeutic` produces `payload_role_mismatch`.
- Cre mRNA reported as `biodistribution_tracer` produces
  `payload_role_mismatch`.
- A policy-ineligible DNA arm remains scientifically confirmable and
  extractable.

- [ ] **Step 2: Run the policy tests and verify RED**

Expected: the report has no payload-role or derived-policy fields.

- [ ] **Step 3: Add payload-role science validation**

Include `payload_role` in scientific evidence coverage. Require:

```python
expected_role = (
    "biodistribution_tracer"
    if arm["payload"] == "QUANT DNA"
    else "reporter"
)
```

A mismatch is a scientific error, not a structural-linkage error.

- [ ] **Step 4: Derive policy results from confirmed candidate IDs**

After final structural/scientific validation:

```python
extractable = confirmed_candidate_ids
rna_eligible = [
    candidate_id
    for candidate_id in confirmed_candidate_ids
    if arm_by_id[candidate_id]["payload"] == "Cre mRNA"
]
```

Return sorted ID lists and a closed per-candidate map containing
`extractable_delivery_evidence` and `rna_recommendation_eligible`. Never accept
these flags from the LLM response.

- [ ] **Step 5: Run all experimental-arm tests**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_experimental_arms.py
```

- [ ] **Step 6: Commit Task 2**

```bash
git add src/extraction/experimental_arms.py tests/test_experimental_arms.py
git commit -m "feat: derive payload recommendation eligibility"
```

### Task 3: Correct the six human-reviewed evidence envelopes

**Files:**
- Modify through regeneration: `data/staging/extraction/np002_kupffer_arm_benchmark_review/NP-002/approved_review.json`
- Test: `tests/test_np002_kupffer_arm_benchmark.py`

**Interfaces:**
- Consumes: exact evidence IDs from `data/staging/rag/compact_api_packets_v1/NP-002.json`.
- Produces: six approved arms with formulation- and dose-specific evidence envelopes.

- [ ] **Step 1: Write failing evidence-envelope assertions**

Build an approved-review fixture with these invariants:

- KUP-01 outcome evidence includes `NP-002-E-7dba55b961c9fe1a` and excludes
  `NP-002-E-1c82bf3a77fad899`.
- KUP-02 outcome evidence includes `NP-002-E-1c82bf3a77fad899` and excludes
  `NP-002-E-7dba55b961c9fe1a`.
- KUP-03/04 include the 1.0 mg/kg treatment, three-day endpoint,
  `NP-002-E-b3a4760121f32ac5`, and the dose comparison
  `NP-002-E-3fc62774b28c2dff`; they exclude the 0.3-only
  `NP-002-E-8db53352513724f5`.
- KUP-05/06 include formulation identity
  `NP-002-E-b630414e4abef2d1`, the 0.3 mg/kg repeat/decrease evidence, the dose
  comparison, and the 0.3 mg/kg Kupffer outcome.

- [ ] **Step 2: Verify RED against the current approved review**

Expected: KUP-01/02 share both outcomes, KUP-03/04 contain 0.3-only evidence,
and KUP-05/06 omit formulation identity.

- [ ] **Step 3: Regenerate the signed approved review locally**

Use the unchanged packet and proposal. Replace all six addition arms with the
approved mappings and corrected evidence IDs, set `confidence` to
`human_confirmed`, recompute `review_sha256`, and validate with
`_load_signed_review`. This is artifact generation and makes zero provider
calls.

- [ ] **Step 4: Run runner/preflight tests**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_np002_kupffer_arm_benchmark.py
```

Generated artifacts remain uncommitted.

### Task 4: Verify, review, and regenerate the zero-call request

**Files:**
- Generated only: `data/staging/extraction/np002_kupffer_arm_benchmark_preflight/NP-002/`

**Interfaces:**
- Consumes: tested code and signed six-arm review.
- Produces: one immutable request SHA for explicit human approval.

- [ ] **Step 1: Run focused and full tests**

Run the compact-contract, prompt, arm, and runner suites, followed by the full
repository suite with API keys blank.

- [ ] **Step 2: Request independent code review**

Review the implementation diff for payload semantics, deterministic-policy
derivation, dose/formulation evidence isolation, strict-schema compatibility,
and accidental provider calls. Fix all Critical and Important findings.

- [ ] **Step 3: Regenerate preflight**

Run `preflight_kupffer_benchmark` with model `gpt-5.6-terra`, the corrected
signed review, and `data/staging/rag/compact_api_packets_v1`. Provider calls
must remain zero.

- [ ] **Step 4: Independently verify the immutable request**

Check request byte hash, rebuild equality, six canonical arm mappings, required
`payload_role`, no `oneOf`, no type-less enum/const nodes, estimated tokens,
and `provider_calls == 0`.

- [ ] **Step 5: Stop for approval**

Report the exact request SHA, token estimate, six arm mappings, test results,
and review result. Do not dispatch the request without explicit approval of
that SHA.
