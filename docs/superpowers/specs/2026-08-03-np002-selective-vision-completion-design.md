# NP-002 Selective-Vision Completion Design

## Objective

Complete the existing NP-002 v5.2 extraction with two targeted vision calls,
then merge the visual outcomes with the already validated paper-level map and
score the combined artifact. This is a narrow end-to-end benchmark, not a new
general orchestration layer.

## Decisions

- Reuse the committed v5.2 paper map; do not repeat the 35,575-token paid call.
- Make exactly two independently approved calls: Figure 2 and Figure 4.
- Extract qualitative comparisons and exact values only when explicitly
  printed in the supplied figure or text.
- Never convert an unlabeled axis position or bar height into a number.
- Do not use the hidden NP-002 answer key to construct prompts, slots, crops,
  evidence packets, or responses. Load it only after the merged extraction is
  finalized.
- Run calls sequentially with no automatic retries. A failed call stops the
  run and requires a new human approval before any paid retry.

## Inputs

- `data/staging/new_papers/NP-002/PMC6816632.pdf`
- `data/staging/new_papers/NP-002/PMC6816632.html`
- `data/staging/extraction/full_paper_np002_paper_map_run/NP-002/paper_map.json`
- Source captions, referring Results passages, and Methods passages selected
  from the ingested paper.

The committed answer key at `data/benchmarks/full_paper/NP-002.json` is an
evaluator-only input.

## Call 1: Figure 2

Purpose: extract source-supported qualitative QUANT-DNA accumulation outcomes
for MC3 and cKK-E12 across Kupffer cells, liver endothelial cells, and
hepatocytes.

The request contains:

- one verified Figure 2 crop;
- its caption;
- the local Results passage that describes Figure 2;
- the QUANT-DNA assay and administration context;
- six explicit source-derived slots: two formulations by three recipient cell
  classes.

Expected preliminary budget: 4,000–7,000 input tokens and a 4,000-token output
cap. The final preflight must report the exact locally estimated input, output
cap, crop checksum, and request SHA-256 before approval.

## Call 2: Figure 4

Purpose: extract source-supported qualitative Cre-mRNA functional-delivery
outcomes for MC3 and cKK-E12 at 0.3 and 1.0 mg/kg across the same three liver
cell classes.

The request contains:

- one verified Figure 4 crop, retaining panels needed to distinguish doses;
- its caption;
- the local Results passage that describes Figure 4;
- Ai14/tdTomato assay and administration context;
- twelve explicit source-derived slots: two formulations by two doses by three
  recipient cell classes.

Expected preliminary budget: 5,000–9,000 input tokens and a 6,000-token output
cap. The final preflight must report the same exact approval data as Call 1.

## Response Contract

Each source-derived slot must be accounted for exactly once. An extracted row
contains:

- slot ID;
- formulation;
- payload and dose;
- recipient cell;
- assay and endpoint;
- qualitative outcome;
- comparison target, when reported;
- significance wording, when reported;
- exact numeric value and unit only when explicitly printed;
- figure and panel;
- supplied evidence IDs;
- confidence.

Allowed dispositions are `extracted` and `not_explicit`. `not_explicit` must
include a source-grounded explanation and cannot link a returned outcome. The
validator rejects missing slots, invented slots, changed formulation/dose/cell
identity, unknown evidence IDs, numeric values without visible printed support,
and unaccounted returned rows.

## Merge

The merger combines each visual row with the existing shared paper map. Shared
formulation components and ratios remain paper-level facts and are not inferred
onto Cre-mRNA arms where the exact recipe is not restated. The merged artifact
preserves source provenance and records `numeric_value: null` when only a
qualitative comparison is supported.

The hidden evaluator runs only after the merged artifact is written. It reports
overall recall, shared recall, experiment-fact recall, complete-arm recall,
precision, unsupported inventions, wrong-arm links, and per-recipient recall.

## Failure Boundary

- Preflight and crop inspection make zero provider calls.
- Human approval must name both exact request hashes or approve calls one at a
  time.
- A provider exception, malformed response, failed schema validation, or
  scientific identity violation stops execution.
- No repair or retry call is automatic.

## Timing

- Build, render, inspect, and test preflights: 15–25 minutes.
- Paid-call execution after approval: 10–20 minutes.
- Merge and benchmark: 15–25 minutes.
- Expected end-to-end time: 40–70 minutes if neither call requires a retry.

## Acceptance Criteria

1. Two request artifacts are produced locally with zero provider calls.
2. The Figure 2 request accounts for six source-derived slots.
3. The Figure 4 request accounts for twelve source-derived slots, including
   both 0.3 and 1.0 mg/kg.
4. No visually estimated numeric value can pass validation.
5. Both paid calls require explicit approval and run sequentially without
   retry.
6. The final merged artifact is scored against the hidden key only after
   extraction is complete.
