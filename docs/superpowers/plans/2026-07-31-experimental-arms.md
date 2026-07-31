# Experimental Arms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and preflight one human-reviewed, six-candidate Kupffer-cell extraction benchmark for NP-002, then run exactly one paid call only after separate approval.

**Architecture:** Add one pure-local module that constructs and validates precision-first experimental arms, plus one NP-002-only guarded preflight/runner that reuses the existing compact contract and immutable-call safety pattern. Keep human arm review and paid-call approval as distinct SHA-bound gates; do not add repair, vision, retry, or production-wide orchestration.

**Tech Stack:** Python 3.14, Pydantic/OpenAI strict JSON Schema, pytest, existing compact API packet and token estimator, SHA-256-bound JSON artifacts.

## Global Constraints

- Work only on branch `experimental-arms`, based on `liver-cell-pipeline`.
- Benchmark paper is `NP-002` / `PMC6816632`; target cell is Kupffer cells.
- Pass only when five or six of six arms are scientifically correct.
- Use only evidence already preserved in the NP-002 compact API packet.
- Preflight performs zero provider calls.
- Paid execution performs exactly one provider call with retries disabled.
- No duplicate, invalid, not-core, or insufficient-evidence escape disposition.
- `ambiguous` is allowed only with cited evidence and earns zero extraction credit.
- No repair, vision, or follow-up call.
- Never read credentials during tests and never stage or commit `.env`.

---

### Task 1: Precision-first NP-002 arm proposal

**Files:**
- Create: `src/extraction/experimental_arms.py`
- Create: `tests/test_experimental_arms.py`

**Interfaces:**
- Consumes: a compact packet represented as `Mapping[str, Any]`.
- Produces: `build_np002_kupffer_arm_proposal(packet: Mapping[str, Any]) -> dict[str, Any]`.
- Produces: `validate_arm_review(proposal: Mapping[str, Any], review: Mapping[str, Any]) -> dict[str, Any]`.
- Produces six ordered candidate mappings with `candidate_id`, `formulation`, `payload`, `dose`, `dose_unit`, `route`, `species`, `model`, `target_cell`, `pairing_type`, `existence_evidence_ids`, `outcome_evidence_ids`, and `confidence`.

- [ ] **Step 1: Write failing tests for the six supported arms**

Create a compact fixture containing the actual NP-002 relationship clauses:

```python
def test_builds_six_kupffer_arms_from_explicit_relationships():
    report = build_np002_kupffer_arm_proposal(np002_packet())

    assert [
        (
            row["candidate_id"],
            row["formulation"],
            row["payload"],
            row["dose"],
        )
        for row in report["proposed_arms"]
    ] == [
        ("KUP-01", "MC3", "QUANT DNA", 0.3),
        ("KUP-02", "cKK-E12", "QUANT DNA", 0.3),
        ("KUP-03", "MC3", "Cre mRNA", 1.0),
        ("KUP-04", "cKK-E12", "Cre mRNA", 1.0),
        ("KUP-05", "MC3", "Cre mRNA", 0.3),
        ("KUP-06", "cKK-E12", "Cre mRNA", 0.3),
    ]
    assert all(row["target_cell"] == "Kupffer cells" for row in report["proposed_arms"])
    assert report["quarantined_arms"] == []
```

Add tests proving every arm has nonempty existence and outcome evidence and that
the proposal is derived from packet evidence rather than prior LLM result files.

- [ ] **Step 2: Run the six-arm tests and verify they fail**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_experimental_arms.py
```

Expected: failure because `src.extraction.experimental_arms` does not exist.

- [ ] **Step 3: Write failing precision tests**

Add fixtures and assertions for:

```python
def test_does_not_cross_product_unrelated_formulation_and_dose_clauses():
    report = build_np002_kupffer_arm_proposal(unrelated_clause_packet())
    assert report["proposed_arms"] == []
    assert report["quarantined_arms"][0]["reason"] == "relationship_not_explicit"


def test_respectively_uses_paired_correspondence_not_cross_product():
    report = build_np002_kupffer_arm_proposal(respectively_packet())
    assert len(report["proposed_arms"]) == 2
    assert {
        row["pairing_type"] for row in report["proposed_arms"]
    } == {"paired_correspondence"}
```

Also require direct target-cell and experimental-model evidence; background
mentions of Kupffer cells must not qualify.

- [ ] **Step 4: Implement the minimal arm builder**

In `src/extraction/experimental_arms.py`, define:

```python
ARM_PROPOSAL_VERSION = "np002-kupffer-arm-proposal-1.0.0"
PAIRING_TYPES = {"single_statement", "cross_product", "paired_correspondence"}


def build_np002_kupffer_arm_proposal(
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    ...
```

Use evidence IDs and explicit NP-002 experimental relationship patterns. Permit
cross-product expansion only when one clause explicitly binds alternative
formulations or doses to the same payload/experiment. Return quarantined
relationships instead of guessing.

- [ ] **Step 5: Implement immutable human review validation**

Define a review format:

```json
{
  "review_version": "np002-kupffer-arm-review-1.0.0",
  "proposal_sha256": "...",
  "decisions": [
    {"candidate_id": "KUP-01", "decision": "accept", "reason": "direct evidence"}
  ]
}
```

`validate_arm_review` must require exactly one decision for every proposed arm,
reject unknown or duplicate IDs, and return the approved arms plus a
JSON-serializable validation report. Corrections/additions must contain the
complete arm and cited packet evidence.

- [ ] **Step 6: Run focused tests**

Run the Task 1 pytest command. Expected: all tests pass with provider credentials
cleared.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/extraction/experimental_arms.py tests/test_experimental_arms.py
git commit -m "feat: propose precision-first experimental arms"
```

---

### Task 2: Exact candidate-accounting schema and scientific validator

**Files:**
- Modify: `src/extraction/experimental_arms.py`
- Modify: `tests/test_experimental_arms.py`

**Interfaces:**
- Consumes: the six approved arm mappings and the base
  `CompactExtractionResponse` strict schema.
- Produces: `build_experimental_arm_schema(core_schema: Mapping[str, Any], approved_arms: Sequence[Mapping[str, Any]]) -> dict[str, Any]`.
- Produces: `validate_experimental_arm_response(response: Mapping[str, Any], approved_arms: Sequence[Mapping[str, Any]], evidence_envelope: set[str]) -> dict[str, Any]`.

- [ ] **Step 1: Write failing exact-accounting schema tests**

Require an object keyed by the six IDs:

```python
schema = build_experimental_arm_schema(base_schema(), approved_arms())
accounting = schema["properties"]["experimental_arm_accounting"]

assert accounting["required"] == [
    "KUP-01", "KUP-02", "KUP-03", "KUP-04", "KUP-05", "KUP-06"
]
assert accounting["additionalProperties"] is False
for candidate_id in accounting["required"]:
    assert accounting["properties"][candidate_id]["$ref"].endswith(
        "ExperimentalArmAccountingEntry"
    )
```

The accounting entry disposition enum must be exactly `["extracted",
"ambiguous"]`. Arrays of formulations, experiments, and outcomes remain
variable-length because one returned record may support only one approved arm.

- [ ] **Step 2: Run the schema tests and verify they fail**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_experimental_arms.py -k 'schema or accounting'
```

Expected: failure because the schema function is absent.

- [ ] **Step 3: Implement the strict dynamic schema**

Add `ExperimentalArmAccountingEntry` with:

```json
{
  "disposition": "extracted | ambiguous",
  "linked_experiment_ids": ["..."],
  "linked_outcome_ids": ["..."],
  "evidence_ids": ["..."],
  "reason_code": "extracted | conflicting_evidence | candidate_not_grounded",
  "explanation": "..."
}
```

For `extracted`, schema and local validation require at least one experiment and
one outcome link. For `ambiguous`, record links must be empty and evidence plus
a non-extracted reason code are required.

- [ ] **Step 4: Write failing scientific-link validation tests**

Test rejection of:

- missing, invented, or repeated candidate IDs;
- `duplicate`, `invalid`, `not_core`, or `insufficient_evidence`;
- extracted arm without a returned experiment and linked outcome;
- wrong formulation, payload, dose, target cell, route, or model;
- QUANT arm missing six-hour timepoint or ddPCR measurement;
- Cre arm missing three-day timepoint or tdTomato flow-cytometry measurement;
- citation outside the allowed evidence envelope;
- one outcome reused across incompatible arm identities.

Test that `ambiguous` is accounted but not scientifically confirmed.

- [ ] **Step 5: Implement the validator**

Normalize only harmless aliases such as `mice`/`mouse`, `intravenous`/`IV`, and
`cKK-E12 LNP`/`cKK-E12`. Do not normalize away payload, dose, assay, timepoint,
or target-cell differences.

Return:

```json
{
  "sent": 6,
  "accounted": 6,
  "structurally_valid_extracted": 6,
  "scientifically_confirmed": 6,
  "ambiguous": 0,
  "confirmed_candidate_ids": ["KUP-01", "..."],
  "errors": []
}
```

- [ ] **Step 6: Run Task 2 tests**

Run the full `tests/test_experimental_arms.py`. Expected: all pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/extraction/experimental_arms.py tests/test_experimental_arms.py
git commit -m "feat: enforce exact experimental arm accounting"
```

---

### Task 3: Human-review preflight and guarded one-call runner

**Files:**
- Create: `src/extraction/run_np002_kupffer_arm_benchmark.py`
- Create: `tests/test_np002_kupffer_arm_benchmark.py`

**Interfaces:**
- Consumes: NP-002 compact packet, validated review JSON, model name, and output roots.
- Produces: `prepare_arm_review(paper_id: str, *, packet_root: Path, output_root: Path) -> dict[str, Any]`.
- Produces: `preflight_kupffer_benchmark(paper_id: str, *, model: str, review_path: Path, packet_root: Path, output_root: Path) -> dict[str, Any]`.
- Produces: `run_approved_kupffer_benchmark(*, manifest_path: Path, approval_sha256: str, output_root: Path, client: Any | None = None) -> dict[str, Any]`.

- [ ] **Step 1: Write failing zero-call review-preparation tests**

Require `prepare_arm_review` to:

- accept only `NP-002`;
- call the local arm builder;
- write `proposal.json`, `review_template.json`, and
  `experimental_arms_review.md`;
- record `provider_calls: 0`;
- include human-readable evidence text for every arm;
- leave every review decision explicitly pending.

Use a fake client that raises if touched.

- [ ] **Step 2: Run and verify the tests fail**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_np002_kupffer_arm_benchmark.py
```

Expected: failure because the benchmark module does not exist.

- [ ] **Step 3: Implement review preparation**

Reuse:

- `load_packet` from `src.extraction.run_compact_one_call`;
- `estimate_tokens` from `src.rag.compact_api_packet`;
- `_canonical_json`, `_sha256`, and durable marker patterns from
  `src.extraction.run_core_slot_trial`.

Do not import or reuse the NP-001-specific slot builder.

- [ ] **Step 4: Write failing preflight request tests**

Require preflight to reject:

- pending or invalid review decisions;
- review SHA mismatch;
- fewer or more than six approved arms;
- a modified proposal;
- a paper other than NP-002.

For a valid review, assert:

- exactly six arm packets are included in one request;
- the dynamic schema requires all six candidate keys;
- dispositions are only extracted/ambiguous;
- provider calls remain zero;
- request bytes, SHA-256, estimated input tokens, output cap, model, and packet
  checksum are persisted.

- [ ] **Step 5: Implement immutable preflight**

Use output root:

```text
data/staging/extraction/np002_kupffer_arm_benchmark_preflight/NP-002/
```

Persist `request.json`, `manifest.json`, and `preview.txt`. Set
`max_output_tokens` to 12,000 and reasoning effort to low. Include an instruction
that every candidate must be independently interpreted; copying one outcome to
incompatible dose/payload arms is forbidden.

- [ ] **Step 6: Write failing guarded-runner tests**

With a fake provider, prove:

- missing or mismatched approval hash causes zero calls;
- modified request bytes cause zero calls;
- exactly one request is sent;
- retries are disabled;
- invocation marker is durably written before dispatch;
- a second execution is refused;
- no repair or vision module is invoked;
- raw response, parsed result, validation, usage, and hashes are persisted.

- [ ] **Step 7: Implement the one-call runner**

Use output root:

```text
data/staging/extraction/np002_kupffer_arm_benchmark_run/NP-002/
```

Call `client.responses.create(**request)` exactly once. Validate the response
with `validate_experimental_arm_response`. Do not automatically continue when
the response fails.

- [ ] **Step 8: Run Task 3 tests**

Run the full `tests/test_np002_kupffer_arm_benchmark.py`. Expected: all pass.

- [ ] **Step 9: Commit Task 3**

```bash
git add \
  src/extraction/run_np002_kupffer_arm_benchmark.py \
  tests/test_np002_kupffer_arm_benchmark.py
git commit -m "feat: add guarded Kupffer arm benchmark"
```

---

### Task 4: Verification, NP-002 PDF, and human gates

**Files:**
- Generate, do not commit until reviewed:
  `data/staging/extraction/np002_kupffer_arm_benchmark_review/NP-002/`
- Generate, do not commit until reviewed:
  `data/staging/extraction/np002_kupffer_arm_benchmark_preflight/NP-002/`
- Download for user review:
  `data/staging/new_papers/NP-002/PMC6816632.pdf`

**Interfaces:**
- Consumes: completed Tasks 1–3.
- Produces: a human-readable arm proposal, local PDF, and later an immutable
  zero-call paid-request preview.

- [ ] **Step 1: Run focused verification**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_experimental_arms.py \
tests/test_np002_kupffer_arm_benchmark.py
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete suite**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q
```

Expected: the complete suite passes with zero provider calls.

- [ ] **Step 3: Download and verify the NP-002 PDF**

Download the canonical PMC PDF for `PMC6816632` to:

```text
data/staging/new_papers/NP-002/PMC6816632.pdf
```

Verify:

```bash
file data/staging/new_papers/NP-002/PMC6816632.pdf
pdfinfo data/staging/new_papers/NP-002/PMC6816632.pdf
```

Expected: a valid PDF whose title and PMCID match NP-002. Provide the user a
clickable local-file link.

- [ ] **Step 4: Generate the six-arm human-review artifact**

Run the review-preparation CLI with provider credentials cleared. Confirm:

- six proposed arms;
- zero quarantined arms, or explicitly report any quarantine;
- every arm displays its exact proof and outcome evidence;
- provider calls remain zero.

Present the arm table and proposal SHA-256 to the user. Wait for approval or
corrections before creating the paid request.

- [ ] **Step 5: Apply the approved human review and preflight the paid call**

After approval, persist the exact review decisions and run preflight with
credentials cleared. Report:

- request path and SHA-256;
- exact estimated input tokens;
- maximum output tokens;
- model;
- proposed calls: one;
- provider calls: zero.

Wait for a separate explicit paid-call approval.

- [ ] **Step 6: Run the one-call benchmark only after approval**

Execute once with the approved request SHA-256. Preserve all artifacts.

- [ ] **Step 7: Evaluate the stop/continue gate**

Report:

- accounted out of six;
- structurally valid extracted out of six;
- scientifically correct out of six;
- per-arm errors;
- actual input, output, reasoning, and total tokens.

If scientifically correct is zero through four, stop and do not plan Phase 2.
If it is five or six, report that Strategy A passed and ask before planning
further automation.

- [ ] **Step 8: Final verification and commit**

Run the focused and complete suites again, scan staged files for `.env` and
credential-shaped values, then commit only reviewed code, tests, plan, and
approved benchmark artifacts.

