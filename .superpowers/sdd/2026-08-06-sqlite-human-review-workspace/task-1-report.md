# Task 1 report: read-only review service

## Delivered

- Added `src/ui/review_service.py`, the UI-facing, read-only SQLite boundary.
- Added immutable DTOs for dashboard metrics, paper row counts/summaries, queue arms,
  workspace fields, evidence excerpts, and review history.
- The service uses the existing common-checkout resolver and opens SQLite using `mode=ro`
  with `query_only` enabled; callers cannot select an alternate database path.
- Dashboard values use the latest row for each eligibility profile and deduplicate valid
  field-evidence facts by their canonical field/evidence relationship. Facts must have an
  allowed verification state, a same-paper evidence row, and a same-paper target entity.
- Per-paper counters are physical database-row counts. The service keeps the usable-fact
  count distinct from those physical counts.
- Workspaces render active accepted corrections, explicit empty strings for blank fields,
  selected-paper evidence only, and newest-first immutable review history.

## TDD evidence

1. Added fixture-backed tests before the service existed.
2. Red run: `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_service.py`
   failed with `ModuleNotFoundError: No module named 'src.ui.review_service'` (5 failures).
3. Green focused run: 5 passed in 0.54s.
4. Final scoped verification: 24 passed in 0.36s with
   `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_service.py tests/test_database_status.py`.

## Scope and safety

- No network, API, LLM, or provider calls were made.
- The authoritative SQLite database was not opened for writing or otherwise mutated.
- The assigned worktree has no local `.venv`; verification used the main checkout's existing
  `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python` interpreter.

## Follow-up consideration

The service intentionally defines the Task 1 read DTO boundary only. Task 2 should extend
this module with its separately specified transactional write APIs and readiness checks.

## Review-fix round 1

- Eligibility dashboards and per-arm eligibility now accept only rows bearing the current
  `src.database.status.RULES_VERSION`; a regression test proves obsolete-rule rows count as
  ineligible.
- Queue order now follows the approved review categories, rather than eligibility: complete
  arms awaiting verification, arms with one or two COMET blockers, target-cell or
  experiment-link confirmations, conflicts, then broader incomplete/blocked work.
- Workspace evidence now includes same-paper evidence linked through `import_field_evidence`
  to the selected arm's formulation, components, arm, and outcomes.
- Verification after the fix: 25 passed in 0.36s with
  `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_service.py tests/test_database_status.py`.

## Review-fix round 2

- The near-COMET queue category now counts the current-rules `comet`
  `eligibility_result.reasons_json` blockers. It no longer infers profile readiness from
  the generic arm-assessment missing-field list.
- A regression fixture covers an arm with only the COMET-specific
  `normalization_basis` blocker and asserts that it is second in the approved queue order.
- Verification: 25 passed in 0.41s with
  `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_service.py tests/test_database_status.py`.

## Review-fix round 3

- Queue safety classifications now take precedence over the near-COMET bucket: conflicts
  rank fourth, and blocked or quarantined work ranks fifth, even if the current COMET
  eligibility result contains only one or two blockers.
- The queue regression fixture gives both a conflict arm and a blocked arm a single
  current-rule COMET reason and proves the approved order remains intact.
- Verification: 25 passed in 0.35s with
  `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_service.py tests/test_database_status.py`.
- Commit: `be85df6515dc87ae7478b7c9db54c1acf73ac1e7`.

## Review-fix round 4

- Import reviews whose `review_status` is `quarantined` now remain in the final broader-work
  bucket even when the arm has no assessment row and has only one or two current COMET
  blockers.
- The queue regression fixture covers that overlap explicitly. Before the production change,
  the focused test failed because the quarantined arm was incorrectly ranked in the
  near-COMET bucket; after the change it passes in the final bucket.
- Verification: 25 passed in 0.34s with
  `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_service.py tests/test_database_status.py`.
