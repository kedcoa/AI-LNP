# Task 1 Report: Bind Provider Execution to Exact Approved Request Bytes

## Outcome

Implemented the signed approval-byte boundary for both text and vision
missing-record runners.

- Preflight manifests remain at
  `missing-record-request-preflight-1.2.0`, sort request rows, and now carry a
  canonical `manifest_checksum`.
- `load_approved_request()` validates the manifest checksum, exact resolved
  request-row cardinality, supplied and persisted SHA-256 values, JSON request
  structure, model, prompt-bearing input, response schema, and the exact
  4,000-token output limit.
- Callable text and vision runners require `approved_request_path`,
  `approved_request_sha256`, and `confirm_paid_call`.
- Cache misses fail before cache-directory creation or provider use unless the
  paid call is confirmed. Complete cache hits remain readable without paid-call
  confirmation.
- Provider calls receive only the exact dictionary parsed from the validated
  approved bytes. The paid path no longer rebuilds a request.
- Cache fingerprints include task checksum, prompt version, exact approved
  request SHA-256, approved model, and approved output limit.
- Both CLIs validate approval before constructing `OpenAI`.

No provider, network, CodeRabbit, push, or real paid-call path was used. Tests
used local fake clients only.

## Root Cause

The prior preflight persisted and hashed request artifacts, but the callable
text and vision runners accepted mutable `model` and `max_output_tokens`
arguments and rebuilt the request immediately before provider execution.
Paid-call confirmation existed only in the CLI wrappers. Direct Python callers
could therefore bypass confirmation, and provider arguments were not
cryptographically bound to the human-reviewed artifact.

## RED Evidence

Command:

```text
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
  /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest \
  tests/test_preflight_missing_record_repairs.py \
  tests/test_missing_record_workflow.py \
  tests/test_missing_record_vision.py -q
```

Observed before production changes:

```text
10 failed, 34 passed in 0.96s
```

The failures were the expected missing-contract failures:

- no `manifest_checksum`;
- no `load_approved_request`;
- text and vision `run()` rejected the new required approval/confirmation
  keywords;
- text cache fingerprint rejected approved-request identity inputs.

No failure was caused by a malformed fixture or external dependency.

## GREEN Evidence

The first focused GREEN run after the minimal implementation was:

```text
44 passed in 0.77s
```

After self-review added checksum-tamper, cache-hit-without-confirmation,
no-directory-before-confirmation, and independent fingerprint-field coverage,
the final focused run was:

```text
46 passed in 0.71s
```

## Full-Suite Evidence

Final command:

```text
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
  /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q
```

Final result:

```text
258 passed, 5 warnings in 2.06s
```

The five warnings are SWIG import deprecation warnings and are unrelated to
these changes.

## Self-Review

- Confirmed manifest checksum covers the entire unsigned manifest after request
  rows are sorted.
- Confirmed a request path must resolve to exactly one signed row.
- Confirmed the caller-supplied SHA must match both that row and the exact file
  bytes.
- Confirmed non-integer or non-4,000 output limits cannot enter paid execution.
- Confirmed both callable boundaries reject unconfirmed cache misses before
  directory creation and before fake-client use.
- Confirmed complete cache hits perform zero provider calls without requiring
  paid-call confirmation.
- Confirmed both provider boundaries receive the approved parsed dictionary
  directly and never call `build_openai_request()` in the paid path.
- Confirmed approved bytes are rehashed immediately before their exact bytes are
  copied into the run audit directory.
- Confirmed cache identity changes independently with request SHA, model, output
  limit, and task checksum.
- Confirmed both CLIs validate the signed approval before `OpenAI`
  construction.
- Confirmed repository call-site search found no additional text/vision runner
  callers requiring migration.
- Confirmed `git diff --check` was clean before final verification.

## Concerns / Handoff

- The manifest checksum is an integrity checksum; the separately supplied
  approved request SHA-256 remains the human approval anchor.
- No external-provider behavior was exercised; fake clients cover the exact
  callable provider boundary required by this task.

## Independent Review Fix Round 1

Implementation commit:

```text
5ef3e4016ca9ceffb52dfcda9fba2977d47c852e
```

### Findings Resolved

1. Approved rows are now bound to the current task checksum, paper, and runner
   route. Text requires `route == "text"` and vision requires
   `route == "vision"`. Both callable runners enforce this before cache
   directory creation or provider use.
2. Every generated preflight row above the 6,000 estimated-input-token ceiling
   now emits `input_token_cap_exceeded`, making local preflight fail. Approval
   loading independently requires an integer row estimate in `[0, 6_000]` and
   rejects any manifest whose signed `local_preflight_passed` value is not
   `true`.
3. Both CLIs now load the task and validate request SHA, signed row scope,
   signed token estimate, and local preflight status before constructing
   `OpenAI`.

Exact approved dictionary execution is unchanged:
`client.responses.create(**approved_request)`.

### Root Cause

Preflight already wrote `paper_id`, `route`, `task_checksum`, and
`estimated_input_tokens` into each checksummed request row, but
`load_approved_request()` discarded those fields after selecting the row by
path and validating its SHA. The runners therefore fingerprinted the current
task and approved request together without first proving that the signed row
authorized that pairing.

Separately, `_request_row()` treated the input-token estimate as informational:
it recorded values above 6,000 without emitting a preflight issue.
`load_approved_request()` also accepted the row without inspecting its estimate
or the signed local-preflight verdict.

### Round 1 RED Evidence

Focused command:

```text
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
  /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest \
  tests/test_preflight_missing_record_repairs.py \
  tests/test_missing_record_workflow.py \
  tests/test_missing_record_vision.py -q
```

Initial round result:

```text
9 failed, 46 passed in 0.80s
```

The failures proved that:

- a 6,001-token generated row still left local preflight passing;
- text and vision runners reached their exploding fake providers for signed
  task-checksum, paper, route, and token-budget mismatches.

The task/paper/route fix was then isolated:

```text
6 passed, 37 deselected in 0.62s
```

Before the token-budget fix, the focused token/local-preflight tests produced:

```text
4 failed, 52 deselected in 0.70s
```

### Round 1 GREEN Evidence

Token/local-preflight tests:

```text
4 passed, 52 deselected in 0.60s
```

Final focused suite:

```text
57 passed in 0.71s
```

Final full repository suite:

```text
269 passed, 5 warnings in 2.07s
```

The five warnings remain unrelated SWIG import deprecations.

Bytecode compilation of all three modified production modules succeeded, and
`git diff --check` was clean.

### Files Changed in Round 1

- `src/extraction/preflight_missing_record_repairs.py`
- `src/extraction/run_missing_record_repair.py`
- `src/extraction/run_missing_record_vision.py`
- `tests/test_preflight_missing_record_repairs.py`
- `tests/test_missing_record_workflow.py`
- `tests/test_missing_record_vision.py`
- `.superpowers/sdd/2026-07-30-cohesive-extraction-afternoon/task-1-report.md`

### Round 1 Self-Review

- Text and vision have symmetric negative coverage for task checksum, paper,
  and route mismatch.
- Every mismatch test uses a real signed manifest and request, asserts zero fake
  provider calls, and asserts no run directory was created.
- Text and vision have symmetric provider-boundary coverage for a signed
  6,001-token row.
- The exact 6,000-token boundary is accepted; 6,001 is rejected.
- A generated over-budget row invalidates local preflight.
- A checksum-valid manifest with `local_preflight_passed: false` cannot
  authorize execution.
- Callable cache misses validate scope and budget before directory creation and
  provider use. Cache hits continue to validate the signed approval artifact.
- CLI scope and budget validation occurs before `OpenAI` construction.
- Paid execution still sends the exact dictionary parsed from approved bytes
  and never rebuilds the request.
- Unrelated/untracked v7 artifacts were not read, modified, staged, or committed.

### Remaining Concerns

- No provider or network call was made; all provider-boundary checks use local
  fakes.
- The five full-suite warnings are pre-existing SWIG deprecation warnings.
