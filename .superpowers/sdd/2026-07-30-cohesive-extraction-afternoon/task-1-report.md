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

- Independent review is intentionally left to the root agent, per task
  ownership.
- The manifest checksum is an integrity checksum; the separately supplied
  approved request SHA-256 remains the human approval anchor.
- No external-provider behavior was exercised; fake clients cover the exact
  callable provider boundary required by this task.
