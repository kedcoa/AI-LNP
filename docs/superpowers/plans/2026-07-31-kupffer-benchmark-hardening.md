# Kupffer Benchmark Four-Part Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four remaining review defects in the NP-002 Kupffer benchmark, regenerate one immutable zero-call request, and stop for explicit paid-call approval.

**Architecture:** Keep the existing Strategy A builder, human review, strict response schema, validator, and one-call runner. Harden only their existing boundaries: bind every automatic arm fact to one packet evidence context, make every post-invocation failure terminal and auditable, derive structural and scientific results independently from candidate-ID sets, and eliminate arithmetic count adjustment.

**Tech Stack:** Python 3.14, pytest, Pydantic/OpenAI Structured Outputs, existing compact packet metadata, SHA-256-bound JSON artifacts.

## Global Constraints

- Benchmark paper is `NP-002` / `PMC6816632`; the only target cell is `Kupffer cells`.
- Preserve the exact human-approved KUP-01 through KUP-06 formulation/payload/dose mapping.
- Use only evidence present in the SHA-bound NP-002 compact packet.
- Do not add orchestration, repair, retry, vision, or another LLM call.
- Automatic arm construction remains precision-first and fail-closed.
- Human arm approval and paid-call approval remain separate SHA-bound gates.
- Tests run with `OPENAI_API_KEY=` and `SENSENOVA_API_KEY=`.
- No real provider client may be constructed during Tasks 1–5; tests may use
  the existing fake client.
- The prior request SHA `38d89f5193830ad79aa69587ba0b667a65f422dc1e715bd387ab458214cb0900` is invalid and must never be dispatched.
- Do not stage or commit `.env`, the PDF, or generated review/preflight artifacts.

---

## File responsibility map

- `src/extraction/experimental_arms.py`: packet-context graph checks, automatic arm qualification, canonical arm/scientific validation, and candidate validity sets.
- `src/extraction/run_np002_kupffer_arm_benchmark.py`: scoped evidence-envelope validation, provider boundary, terminal failure artifacts, and immutable preflight/runner.
- `tests/test_experimental_arms.py`: automatic-context and structural-versus-scientific regressions.
- `tests/test_np002_kupffer_arm_benchmark.py`: malformed-response auditing and nonnegative scoped-count regressions.
- `data/staging/extraction/np002_kupffer_arm_benchmark_review/NP-002/`: regenerated signed review; generated and uncommitted.
- `data/staging/extraction/np002_kupffer_arm_benchmark_preflight/NP-002/`: regenerated immutable request; generated and uncommitted.

---

### Task 1: Bind route and model evidence to the automatic arm context

**Files:**
- Modify: `src/extraction/experimental_arms.py:90-520`
- Test: `tests/test_experimental_arms.py`

**Interfaces:**
- Consumes: packet evidence rows containing `evidence_id`, `source_ids`, `experiment_candidate_ids`, `context_before_evidence_id`, and `context_after_evidence_id`.
- Produces: automatic KUP arms only when treatment, target/outcome, route, and model evidence form one connected packet context.

- [ ] **Step 1: Write failing disconnected-route and disconnected-model tests**

Add two tests using literal evidence rows:

```python
def test_automatic_arm_rejects_route_from_disconnected_experiment():
    packet = connected_cre_packet()
    packet["evidence"][-1] = {
        "evidence_id": "E-ROUTE-OTHER",
        "text": "Mice were injected intravenously via the lateral tail vein.",
        "source_ids": ["SOURCE-OTHER"],
        "experiment_candidate_ids": ["EXP-OTHER"],
    }

    report = build_np002_kupffer_arm_proposal(packet)

    assert report["proposed_arms"] == []
    assert any(
        row["reason"] == "relationship_not_explicit"
        for row in report["quarantined_arms"]
    )


def test_automatic_cre_arm_rejects_model_from_disconnected_experiment():
    packet = connected_cre_packet()
    model = next(
        row for row in packet["evidence"]
        if row["evidence_id"] == "E-CRE-MODEL"
    )
    model["source_ids"] = ["SOURCE-OTHER"]
    model["experiment_candidate_ids"] = ["EXP-OTHER"]
    model.pop("context_before_evidence_id", None)
    model.pop("context_after_evidence_id", None)

    report = build_np002_kupffer_arm_proposal(packet)

    assert report["proposed_arms"] == []
```

The fixture must give the treatment, target/outcome, route, and model rows a
shared `source_id`, shared `experiment_candidate_id`, or reciprocal neighbor
chain before mutating the one row under test.

- [ ] **Step 2: Run the two tests and verify RED**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
tests/test_experimental_arms.py -k \
'rejects_route_from_disconnected_experiment or rejects_model_from_disconnected_experiment'
```

Expected: both tests fail because unrelated route/model rows are currently
accepted.

- [ ] **Step 3: Implement one evidence-context connectivity predicate**

Add one pure helper and reuse it for treatment, outcome, route, and model:

```python
def _evidence_rows_connected(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    left_sources = set(left.get("source_ids", []))
    right_sources = set(right.get("source_ids", []))
    left_experiments = set(left.get("experiment_candidate_ids", []))
    right_experiments = set(right.get("experiment_candidate_ids", []))
    reciprocal_neighbors = (
        left.get("context_after_evidence_id") == right.get("evidence_id")
        and right.get("context_before_evidence_id") == left.get("evidence_id")
    ) or (
        left.get("context_before_evidence_id") == right.get("evidence_id")
        and right.get("context_after_evidence_id") == left.get("evidence_id")
    )
    return bool(
        left_sources & right_sources
        or left_experiments & right_experiments
        or reciprocal_neighbors
    )
```

Build the connected evidence component from the treatment-binding rows. Require
at least one route row, model row, and direct Kupffer outcome row to connect to
that component. Do not treat shared keywords as connectivity. Quarantine the
family when any required fact is disconnected.

- [ ] **Step 4: Run focused automatic-builder tests**

Run the Task 1 tests plus the existing real-packet KUP-03/04 proposal test.
Expected: disconnected fixtures are quarantined and the real packet behavior
remains unchanged.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/extraction/experimental_arms.py tests/test_experimental_arms.py
git commit -m "fix: bind automatic arms to experiment context"
```

---

### Task 2: Audit every malformed or contract-invalid provider response

**Files:**
- Modify: `src/extraction/run_np002_kupffer_arm_benchmark.py:594-850`
- Test: `tests/test_np002_kupffer_arm_benchmark.py`

**Interfaces:**
- Consumes: provider exception or response `output_text`.
- Produces: exactly one terminal success/failure manifest after the invocation marker, with all hashes available at the point of failure; never retries.

- [ ] **Step 1: Write failing valid-JSON scalar/list audit tests**

Parameterize `[]`, `"text"`, `42`, and `null`:

```python
@pytest.mark.parametrize("output_text", ["[]", '"text"', "42", "null"])
def test_non_object_json_response_leaves_terminal_audit(
    tmp_path, output_text
):
    manifest_path, approval_sha = prepared_preflight(tmp_path)
    client = fake_client(output_text=output_text)

    with pytest.raises(ValueError, match="JSON object"):
        run_kupffer_benchmark(
            manifest_path=manifest_path,
            approval_sha256=approval_sha,
            client=client,
            output_root=tmp_path / "run",
        )

    failure = json.loads(
        (tmp_path / "run" / "NP-002" / "failure_manifest.json").read_text()
    )
    assert failure["status"] == "failed_provider_response_validation"
    assert failure["failure_classification"] == "non_object_json"
    assert failure["raw_response_sha256"]
    assert failure["paid_api_requests"] == 1
```

Add a separate assertion that an object-shaped Pydantic failure manifest
contains `trial_response_sha256`.

- [ ] **Step 2: Run the new audit tests and verify RED**

Expected: scalar/list cases raise before writing a manifest, and the Pydantic
failure manifest lacks the parsed-response hash.

- [ ] **Step 3: Move all post-response parsing into one guarded boundary**

After raw response and usage artifacts are persisted:

```python
try:
    trial_response = json.loads(response.output_text)
except json.JSONDecodeError as exc:
    write_terminal_failure("invalid_json", available_hashes)
    raise ValueError("provider output is not valid JSON") from exc

if not isinstance(trial_response, dict):
    trial_response_bytes, trial_response_sha256 = _artifact(
        run_dir / "trial_response.json",
        trial_response,
    )
    write_terminal_failure(
        "non_object_json",
        {**available_hashes, "trial_response_sha256": trial_response_sha256},
    )
    raise ValueError("provider output must be a JSON object")
```

Use the same terminal writer for provider exceptions, invalid JSON, non-object
JSON, paper-ID mismatch, Pydantic failure, and unexpected local-validation
exceptions. Pass optional hashes explicitly; never recompute missing artifacts
and never call the provider again. A successfully computed validation report
with structural or scientific errors is a completed benchmark result, not a
runner failure; preserve and score it normally.

- [ ] **Step 4: Run all runner audit/one-call tests**

Expected: every post-marker path has one terminal manifest, one paid request at
most, and no retry.

- [ ] **Step 5: Commit Task 2**

```bash
git add \
  src/extraction/run_np002_kupffer_arm_benchmark.py \
  tests/test_np002_kupffer_arm_benchmark.py
git commit -m "fix: audit every benchmark response failure"
```

---

### Task 3: Separate structural validity from scientific accuracy

**Files:**
- Modify: `src/extraction/experimental_arms.py:1460-1760`
- Test: `tests/test_experimental_arms.py`

**Interfaces:**
- Consumes: strict response plus approved arms and evidence envelope.
- Produces: independent `structurally_valid_candidate_ids` and `scientifically_confirmed_candidate_ids`, with counts derived from those sets.

- [ ] **Step 1: Write failing structural/scientific separation tests**

Start from a structurally linked six-arm valid response, then mutate only one
scientific field:

```python
@pytest.mark.parametrize(
    ("candidate_id", "field_path", "bad_value", "error_code"),
    [
        ("KUP-01", ("outcomes", 0, "assay", "value"), "qPCR",
         "quant_ddpcr_required"),
        ("KUP-03", ("experiments", 0, "timepoint", "value"), 1.0,
         "cre_timepoint_required"),
    ],
)
def test_scientific_error_does_not_reduce_structural_count(
    candidate_id, field_path, bad_value, error_code
):
    response, approved_arms, evidence_ids = valid_six_arm_response()
    set_path(response, field_path, bad_value)

    report = validate_experimental_arm_response(
        response, approved_arms, evidence_ids
    )

    assert report["accounted"] == 6
    assert report["structurally_valid_extracted"] == 6
    assert report["scientifically_confirmed"] == 5
    assert any(row["code"] == error_code for row in report["errors"])
```

Add the converse: an invalid experiment/outcome link must reduce both structural
and scientific sets.

- [ ] **Step 2: Run separation tests and verify RED**

Expected: wrong assay/timepoint currently reduces the structural count.

- [ ] **Step 3: Split structural and scientific invalid-ID sets**

Use explicit sets:

```python
structural_valid_ids = set(extracted_candidate_ids)
scientific_valid_ids = set(extracted_candidate_ids)

for error in structural_errors:
    structural_valid_ids.discard(error["candidate_id"])
    scientific_valid_ids.discard(error["candidate_id"])

for error in scientific_errors:
    scientific_valid_ids.discard(error["candidate_id"])
```

Classify accounting, missing/unknown links, incompatible outcome reuse,
duplicate outcome identity, evidence-envelope errors, and missing required
fields as structural. A present route/model/target field can therefore satisfy
the output shape and linkage requirement while still containing the wrong
scientific value. Classify incorrect assay, timepoint, route, model, target,
comparator, and outcome meaning as scientific. Return both sorted ID lists and
derive their counts only at the end.

- [ ] **Step 4: Run all experimental-arm validator tests**

Expected: structural linkage regressions still fail closed; scientific-only
mutations preserve the structural count.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/extraction/experimental_arms.py tests/test_experimental_arms.py
git commit -m "fix: separate structural and scientific arm validity"
```

---

### Task 4: Prevent negative scoped validity counts

**Files:**
- Modify: `src/extraction/run_np002_kupffer_arm_benchmark.py:506-575`
- Test: `tests/test_np002_kupffer_arm_benchmark.py`

**Interfaces:**
- Consumes: core validation report plus candidate-specific allowed evidence sets.
- Produces: a final structural candidate-ID set whose count is always between zero and six.

- [ ] **Step 1: Write a failing double-removal regression**

```python
def test_scoped_envelope_double_failure_never_makes_count_negative():
    response, approved_arms, arm_evidence = one_extracted_arm_response()
    response["experimental_arm_accounting"]["KUP-01"]["evidence_ids"] = [
        "E-OUTSIDE"
    ]

    report = _validate_scoped_arm_response(
        response, approved_arms, arm_evidence
    )

    assert report["structurally_valid_extracted"] == 0
    assert report["structurally_valid_candidate_ids"] == []
```

Add a six-arm case in which two independent errors remove the same candidate
and the count remains five, not four.

- [ ] **Step 2: Run scoped-count tests and verify RED**

Expected: the current integer decrement can produce `-1` or double-remove one
candidate.

- [ ] **Step 3: Replace integer adjustment with set subtraction**

```python
valid_ids = set(report["structurally_valid_candidate_ids"])
for candidate_id in invalid_candidates:
    valid_ids.discard(candidate_id)
report["structurally_valid_candidate_ids"] = sorted(valid_ids)
report["structurally_valid_extracted"] = len(valid_ids)
```

Apply the same removal to `scientifically_confirmed_candidate_ids` because a
candidate outside its approved evidence envelope cannot be scientifically
confirmed. Never increment or decrement either aggregate count directly.

- [ ] **Step 4: Run scoped and full focused benchmark tests**

Expected: every count is within `0..6`, duplicate removal is idempotent, and
candidate-specific evidence violations remain reported.

- [ ] **Step 5: Commit Task 4**

```bash
git add \
  src/extraction/run_np002_kupffer_arm_benchmark.py \
  tests/test_np002_kupffer_arm_benchmark.py
git commit -m "fix: derive scoped validity from candidate sets"
```

---

### Task 5: Verify, independently review, and regenerate the zero-call request

**Files:**
- Generate, do not commit: `data/staging/extraction/np002_kupffer_arm_benchmark_review/NP-002/`
- Generate, do not commit: `data/staging/extraction/np002_kupffer_arm_benchmark_preflight/NP-002/`
- Verify: `docs/superpowers/specs/2026-07-31-strategy-a-kupffer-arm-benchmark-design.md`

**Interfaces:**
- Consumes: reviewed Tasks 1–4 and the existing six human-approved arms.
- Produces: one new immutable request and approval packet with zero provider calls.

- [ ] **Step 1: Run focused verification with credentials cleared**

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

Expected: zero failures and zero provider calls.

- [ ] **Step 3: Request independent whole-change code review**

The reviewer must explicitly verdict:

- route/model context binding;
- scalar/list/invalid/object-contract terminal audits and hashes;
- structural/scientific separation;
- nonnegative, idempotent candidate-set counting;
- preservation of exactly one provider call with retries disabled.

Resolve every Critical or Important finding before proceeding.

- [ ] **Step 4: Regenerate the signed review from the same six approved arms**

Regenerate the proposal because packet-context code changes alter its SHA.
Reapply the already approved KUP-01 through KUP-06 inventory with the same
formulation/payload/dose and corrected Figure 4b/4c evidence. Validate the
review locally.

- [ ] **Step 5: Generate a new immutable preflight with zero credentials**

Call `preflight_kupffer_benchmark(...)` for `NP-002` using
`gpt-5.6-terra`. Confirm:

- approved arm IDs are exactly KUP-01 through KUP-06;
- provider calls are zero;
- proposed calls are one;
- request SHA matches the saved request bytes;
- schema contains no `oneOf`;
- exact input-token estimate and output cap are recorded.

- [ ] **Step 6: Present the new approval packet and stop**

Report the exact request path, SHA-256, model, estimated input tokens, maximum
output tokens, proposed calls, and provider calls. Explicitly state that no
paid call has occurred. Wait for the user's separate approval of that exact
SHA-256.
