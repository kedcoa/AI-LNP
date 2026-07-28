# Week 1 Day 4 afternoon - selective vision

## Workflow position

```text
first-call candidate
  -> compact_validation.py
  -> identify_selective_vision_referrals.py
  -> explicit unresolved table/figure referral
  -> build_selective_vision_tasks.py
  -> one page/crop PNG
  -> run_selective_vision.py
  -> exact, derived, missing, ambiguous, or human-review result
```

## File responsibilities

- `selective_vision_contracts.py` defines the referral, one-crop task, and
  response. A resolved value must include a panel or table-cell location.
  Visually estimated values are forced to human review.
- `identify_selective_vision_referrals.py` triggers only when a field-level
  finding explicitly says the value remains unresolved, explicitly references
  a figure/table, and resolves to one visual source, one caption, and a Results
  passage. Ambiguous cases are skipped with a reason.
- `build_selective_vision_tasks.py` requires an explicit
  `unresolved_table` or `unresolved_figure` referral. It gathers only the
  caption, one to three referring results passages, up to three methods
  passages, and the schema of the failed field. It renders one PDF page or
  crop to PNG.
- `run_selective_vision.py` sends the PNG and narrow text context through one
  structured OpenAI request. It never sends the entire PDF, validates that
  only the requested field changed, and caches the call independently.

## Storage

Tasks and crops:

```text
data/staging/extraction/selective_vision_tasks_v1/
  <paper_id>/<finding_id>/
  crop.png
  task.json
```

Every crop receives a deterministic `crop_evidence_id` derived from its SHA-256
checksum. Vision results cite that ID when the image itself supports the value;
caption and passage evidence keep their existing text evidence IDs.

Vision calls:

```text
data/staging/extraction/selective_vision_v1/
  <paper_id>/<finding_id>/<vision_fingerprint>/
    request.json
    response.json
    result.json
    manifest.json
```

## Trigger boundary

Vision is not triggered merely because a paper contains a figure or table.
Text processing must explicitly identify one unresolved field and one relevant
figure/table source. The referral must specify the page, object label, caption,
referring results passage, and any necessary methods context.

## Scientific safety

- Printed values are `exact_reported`.
- `derived` values require an explicit derivation.
- Axis or bar position alone is never an exact value.
- `visually_estimated` values always require human review.
- Every resolved or estimated value needs a panel or table-cell location.
- The full PDF is never sent during routine selective vision.
- Original candidates and morning repair results remain unchanged.
- Final merging is intentionally deferred until text and vision routes can be
  handled together.
