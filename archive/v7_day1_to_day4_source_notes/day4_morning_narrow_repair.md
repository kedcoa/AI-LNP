# Week 1 Day 4 morning - narrow field repair

## Workflow position

```text
compact API packet
  -> run_compact_one_call.py (first LLM call)
  -> compact_validation.py (deterministic findings)
  -> build_repair_tasks.py (one small packet per repairable field)
  -> run_narrow_repair.py (second LLM call)
  -> separately stored repair result
```

## File responsibilities

- `compact_validation.py` applies the existing compact contract and converts
  failures into a stable `ValidationReport`. A finding is repairable only when
  it identifies one collection, record index, and field.
- `build_repair_tasks.py` includes the invalid record, validation finding,
  cited evidence, at most three field-matched passages, and the expected field
  schema. Whole paper packets are not included.
- `repair_contracts.py` restricts the response to `corrected`, `missing`, or
  `ambiguous`.
- `run_narrow_repair.py` makes one structured repair call, validates the
  returned field locally, records usage, and caches it independently from the
  first extraction.

## Storage

First-call validation reports:

```text
data/staging/extraction/compact_one_call_v1/<paper_id>/validation_report.json
```

Repair tasks:

```text
data/staging/extraction/narrow_repair_tasks_v1/<paper_id>/<finding_id>.json
```

Repair calls:

```text
data/staging/extraction/narrow_repair_v1/
  <paper_id>/<finding_id>/<repair_fingerprint>/
```

Each repair-call directory contains `request.json`, `response.json`,
`result.json`, and `manifest.json`.

## Safety boundaries

- Non-field and cross-record findings are not automatically repaired.
- A repair can change exactly one field.
- Evidence IDs must come from the repair task.
- The first LLM candidate remains unchanged.
- Merging accepted repairs into a final result is a later, explicit step.
- The CLI requires `--confirm-paid-call`; tests use a fake client and spend
  nothing.
