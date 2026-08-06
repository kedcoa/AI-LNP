# Final manual-review fix report

Date: 2026-08-06

## Delivered

- Added migrations 4 and 5 for entity-scoped immutable review history, explicit
  six-action provenance, evidence IDs, entity-ownership triggers, shared-formulation
  missing-field resolution, legacy `experiment` entity compatibility, and a safe
  trigger repair for databases that had already reached migration 4.
  Migration 5 also qualifies uniquely attributable v4 outcome state and explicitly
  marks ambiguous legacy outcome ownership instead of guessing.
- Made formulation revisions active by formulation ID for every sibling arm. Workspace
  fields, queue summaries, status, formulation eligibility blockers, missing-state
  resolution, and recalculation now use the same active revision.
- Made every submitted action append a `review_revision`, including `not_reported`,
  `unresolved`, original-evidence rejection, and `wrong_arm`. Each record preserves the
  original/reviewed value, reviewer, exact note, timestamp, action, entity, and evidence
  context without modifying source extraction or evidence rows.
- Kept `not_reported` and `wrong_arm` facts unusable until a later accepted revision;
  a later unresolved action cannot accidentally reactivate them.
- Added selectable outcome fields with outcome-owned evidence, entity-filtered history,
  qualified missing/verification keys, immutable outcome writes, active-value overlays,
  and deterministic eligibility recalculation. Wrong-arm review permits same-paper
  evidence owned by a different arm while accept/correct/reject require the selected
  outcome's evidence. Human verification of initially unreviewed outcome evidence is
  consumed through the active canonical link during eligibility evaluation. Same-paper
  foreign-arm candidates remain available for `wrong_arm` and carry explicit arm/outcome
  ownership labels in the UI.

## TDD evidence

- Initial red run: 14 expected failures across service and migration regressions.
- Additional red regressions reproduced persistent negative-fact invalidation, sibling
  formulation status/eligibility, and outcome-qualified state before their respective
  production changes.
- All new tests exercise temporary SQLite databases; no mocks replace the service,
  migration, status, or transaction behavior.

## Verification

```text
OPENAI_API_KEY= SENSENOVA_API_KEY= ANTHROPIC_API_KEY= GOOGLE_API_KEY= \
  /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q \
  tests/test_schema.py tests/test_database_lifecycle.py \
  tests/test_review_service.py tests/test_review_app.py \
  tests/test_database_status.py tests/test_database_migrations.py

157 passed in 2.05s
```

`py_compile` passed for the four changed production modules, and `git diff --check`
reported no whitespace errors.

## Safety and concerns

- The authoritative SQLite database was not opened for writing or migrated. All write
  tests used pytest temporary databases and external temporary backups.
- No network, API, LLM, provider, DOI, or publisher call was made.
- The authoritative database remains at its existing migration version until a separately
  authorized lifecycle migration is run. This change does not grant or exercise that
  authorization.
