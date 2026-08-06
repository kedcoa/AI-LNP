# Cohesive Extraction Pipeline Design

**Date:** 2026-07-30

## Purpose

Make the existing AI-LNP extraction stages operate as one cohesive pipeline
without introducing another extraction, vision, coverage, or merge
implementation. The first acceptance run uses GP-004, GP-006, and GP-008 to
attempt verified 15/15 development recall; verified recall from 13/15 through
15/15 is acceptable when all precision and safety gates pass. Work is divided
into a streamlined morning attempt and a conditional fuller afternoon
implementation. After the development gate passes, the unchanged path must run
on a newly retrieved, non-gold paper.

## Current Failure

The repository already enforces that every repair candidate is returned exactly
once as recovered or unresolved, and it already performs deterministic
post-repair verification before merging. The failed July 29 run occurred
because the repair task did not carry enough semantic information for the model
to classify candidate-to-experiment relationships:

- experiment association was reduced to a Boolean existence check;
- an associated provisional experiment caused
  `permitted_new_experiments` to become `0`;
- the task received opaque existing experiment IDs without compact
  descriptions of what those experiments represented;
- the response listed recovered candidate IDs and outcomes separately, without
  an explicit candidate-to-outcome-to-experiment resolution;
- the model could not safely distinguish an existing experiment, a new
  experiment, a multi-arm comparison, or a finding supported in several
  experiments.

One GP-008 response also exceeded the 4,000-token output limit after a visual
candidate was bundled with four text candidates. Because the raw response was
persisted only after schema parsing, the truncated response was not retained.

## Goals

1. Give the model enough bounded semantic context to classify every candidate
   against relevant existing experiments without resending the paper.
2. Require an explicit candidate-to-outcome-to-experiment resolution for every
   candidate ID.
3. Run existing local text, Docling, deterministic table, and local-VLM stages
   before paid extraction.
4. Route post-extraction misses through the existing narrow-text or
   selective-vision repair path.
5. Require human approval and `--confirm-paid-call` for every paid primary,
   text-repair, or selective-vision batch.
6. Attempt the smallest cohesive repair-path change first, then build the full
   resumable command only if the bounded attempt fails its acceptance gate.
7. Prove verified recall of at least 13/15 on GP-004, GP-006, and GP-008, then
   run the unchanged path on a newly retrieved non-gold paper.

## Non-goals

- Do not create a new extractor, candidate model, vision model, coverage
  algorithm, or merge algorithm.
- Do not run every vision method on every figure or table.
- Do not automatically retry failed, invalid, or truncated paid responses.
- Do not use gold outcome IDs or gold answers in extraction-time inputs.
- Do not delete legacy scripts as part of this improvement.
- Do not claim recall success from candidate detection alone; only verified
  merged outcomes count.

## Design Principles

- **One active route:** Strategy 1 updates the existing repair entry points;
  Strategy 2 conditionally replaces manual coordination with one documented
  command. Legacy scripts may remain available but are not competing routes.
- **Thin coordination:** if Strategy 2 is invoked, its orchestrator calls
  existing stage functions and checks their artifacts; it does not reproduce
  their scientific logic.
- **Fail closed:** ambiguous identity, invalid schema, missing candidate
  disposition, unsupported evidence, or wrong experiment linkage cannot merge.
  Scientific ambiguity quarantines only the affected candidate group; corrupted
  artifacts or invalid paid responses stop the paper.
- **No hidden spending:** local preparation is the default. Every paid stage
  requires a separate explicit invocation and confirmation flag.
- **No throwaway development path:** GP-004, GP-006, and GP-008 use the same
  general code that later processes new papers.

## Architecture

The following stages describe the complete scientific data flow. Strategy 1
implements the bounded repair subset through existing entry points. Strategy 2
adds the thin orchestrator over the entire sequence.

### 1. Local pre-call preparation

The active preparation entry point invokes or verifies the existing stages for:

1. paper ingestion and compact packet construction;
2. provisional experiment construction;
3. atomic text candidate construction;
4. Docling table and layout extraction;
5. deterministic table candidate construction;
6. local-VLM figure interpretation where the existing gate permits it;
7. promotion of accepted visual claims into the same candidate inventory;
8. exact request and schema preflight.

These stages make no paid API calls. Preparation reports candidate counts,
evidence counts, visual routes, estimated tokens, and all experiment-routing
decisions before stopping at the primary-call approval gate.

### 2. Paid primary extraction

The primary call remains the existing compact extraction implementation. The
active paid entry point may execute it only when:

- local preparation and preflight pass;
- the user has reviewed the exact request summary;
- the invocation contains `--confirm-paid-call`.

The runner persists the raw API response before attempting structured parsing.
Invalid or truncated output stops without an automatic retry.

### 3. Local coverage and repair routing

The existing deterministic coverage checker compares every selected candidate
against the primary result. Each candidate receives one route:

- `confirmed`: no repair;
- `bounded_repair_task` with text evidence: narrow text repair;
- `bounded_repair_task` with visual evidence: selective vision repair;
- `human_review`: no API call;
- `contradicted`: integration blocked and no API call.

Candidate discovery and merged recall remain separate metrics.

### 4. Bounded semantic relationship classification

Candidate IDs are completeness trackers tied to atomic facts and exact
evidence. They do not predetermine the final experiment relationship. The model
classifies that relationship from a bounded repair task.

Each task contains:

- every candidate ID in the task;
- one atomic fact definition per candidate;
- exact evidence for those facts;
- all plausibly relevant existing experiments as compact summaries;
- relevant existing outcome summaries for deduplication;
- provisional experiment context as a retrieval hint, not a binding target;
- explicit limits on new experiments and outcomes.

A compact experiment summary contains only fields needed for classification:
experiment ID, formulation, payload, intervention, recipient and target cells,
model, dose, route, timepoint, comparator context, and existing outcome
endpoints. It omits verbose `ReportedField` wrappers and unrelated narrative.

The builder must include every experiment that remains plausible. “One to
three” is the expected common case, not a top-k rule. If every plausible summary
does not fit the input budget, the builder splits the candidate group or routes
it to review; it never silently drops a plausible experiment.

The response contains one `candidate_resolution` for every candidate ID. A
resolution states:

- `already_represented`: linked to existing outcome IDs;
- `recovered_existing_experiment`: linked to one or more new outcomes on
  existing experiment IDs;
- `recovered_new_experiment`: linked to one permitted new experiment and its
  outcomes;
- `unresolved`: no records and a specific reason.

One candidate resolution may reference several outcomes and experiment IDs when
the evidence explicitly supports the same finding in genuinely separate
experiments. A multi-arm comparison within one experimental design produces one
outcome linked to the encompassing experiment, with the other arm preserved in
the existing comparator field. The model performs this semantic
classification; deterministic code verifies IDs, evidence, completeness, and
structural compatibility.

Association diagnostics remain useful for selecting plausible summaries and
for post-response checking, but they do not replace the model’s relationship
classification.

### 5. Paid targeted repair

Text misses use the existing missing-record/narrow-repair runner. Visual misses
use the existing selective-vision runner with only the relevant crop, caption,
local visual context, candidate facts, and relevant compact experiment
summaries.

The active preparation entry point prepares repair batches locally and stops.
Each text or vision batch requires human review plus `--confirm-paid-call`. A
primary-call approval does not authorize repair calls.

Repair tasks are dynamically packed, not assigned a fixed candidate count. The
builder groups candidates by route, experimental context, and overlapping
evidence, then adds candidates only while both the complete input and
worst-case output remain within budget. The initial input ceiling is 6,000
tokens per repair call; preflight must measure the serialized request, including
the prompt and schema. The output ceiling remains separately enforced.

Text and visual candidates never share a repair call. Visual repair tasks
contain one visual object and every directly supported candidate that safely
fits. They must not rebundle unrelated text candidates into a large visual
response. Candidates that do not fit move to another task; none are dropped.

After one targeted repair attempt, an unresolved candidate goes to human review.
There is no automatic third model call or expanding repair loop.

### 6. Verification and merge

Existing validation and structural coverage remain authoritative. Before a
repair fragment can merge:

1. recovered and unresolved candidate IDs must exactly equal the requested
   candidate IDs;
2. returned evidence IDs must be within the task evidence;
3. every candidate resolution must reference only returned or existing outcome
   and experiment IDs;
4. every returned outcome must appear in at least one candidate resolution;
5. every new experiment must be permitted and referenced by a resolved
   candidate;
6. multi-experiment resolution requires distinct experiment-linked outcomes;
7. a multi-arm comparison must preserve its comparator rather than duplicating
   the same outcome across arms;
8. structural coverage must independently confirm every recovered candidate;
9. every new outcome must confirm at least one requested candidate;
10. unresolved candidates remain quarantined while unrelated verified
    candidates may merge.

Only after these checks does the existing additive merge write the proposed
result.

## Strategy 1: Streamlined Morning Attempt

The morning block is a two-to-three-hour attempt to validate the core repair
design before building the full coordinator. It changes only the existing
repair contract, task builder, text and visual repair runners, preflight, and
merge verification needed to support:

- compact semantic summaries for all plausibly relevant experiments;
- explicit candidate-to-outcome-to-experiment resolutions;
- dynamic input- and output-aware batching;
- separate text and visual repair tasks;
- raw-response persistence before parsing;
- deterministic validation of completeness, evidence, IDs, and experiment
  linkage.

Focused contract, builder, runner, routing, and merge tests must pass. Each
implementation task receives an independent code review, followed by a final
whole-change review. The workflow then prepares the frozen GP-004, GP-006, and
GP-008 repair requests and prints an approval report such as:

```text
12 missing candidates
3 local matches — no call
6 text candidates — 2 repair calls
3 visual candidates across 2 figures — 2 vision calls

Total paid repair calls: 4
Estimated input/output tokens: ...
Estimated cost: ...
```

The preflight entry point stops at this point. It may execute the batch only
after the user reviews the exact requests and explicitly approves the paid
calls.

After merge and evaluation, Strategy 1 passes when verified recall is 13/15,
14/15, or 15/15 and every precision and safety requirement in the acceptance
section passes.

If Strategy 1 fails, systematic debugging must classify the failure before any
fix:

- **Small isolated defect:** a reproducible, localized contract,
  serialization, batching, routing, validation, persistence, or ID-handling
  bug that can be corrected with one focused regression test and without
  changing stage boundaries.
- **Architectural failure:** a new processing layer, replacement or removal of
  an existing stage, broad restructuring, repeated prompt adjustment without a
  demonstrated root cause, or another change that exceeds the streamlined
  design.

One small isolated defect may receive one bounded fix, review, local rerun, and
new paid-call preflight. The paid rerun still requires separate user approval.
If that rerun remains below 13/15, violates a safety gate, or exposes an
architectural failure, Strategy 1 ends and Strategy 2 begins. An architectural
failure skips the bounded rerun and moves directly to Strategy 2.

## Strategy 2: Fuller Afternoon Workflow

The afternoon block begins only when the Strategy 1 escalation rule is met. It
implements the complete coordinator and end-to-end workflow described below.
“Afternoon” denotes the second execution phase, not a promise to bypass tests,
reviews, or approval gates to finish within a fixed clock window.

### Thin orchestrator

Add one orchestration module, tentatively
`src/extraction/run_cohesive_pipeline.py`. It owns stage ordering, readiness
checks, approval stops, summaries, and resumability. It does not own extraction
or scientific matching logic.

The command supports three modes:

- default preparation/resume mode: runs all available local stages, reports the
  next paid gate, and exits;
- paid stage mode: executes one explicitly selected prepared stage with
  `--confirm-paid-call`;
- local finalize mode: validates cached responses, builds only necessary repair
  tasks, performs approved merges, and evaluates the result.

Existing manifests, checksums, cached responses, and output directories remain
the authoritative state. The orchestrator may write one summary referencing
those artifacts, but it must not introduce a parallel canonical state model.

## Approval and Failure Behavior

Before any paid stage, the command prints:

- paper IDs;
- stage name;
- model;
- task and candidate counts;
- local matches requiring no call and candidate counts by repair route;
- total paid-call count;
- relevant experiment summaries and proposed candidate scope;
- input and output token limits plus estimated token usage and cost;
- exact prepared request paths;
- cache status.

Without `--confirm-paid-call`, it exits successfully after preparation. It never
prompts interactively inside an unattended command and never treats a previous
approval as permission for a later repair stage.

On a paid-call failure, the raw response and request metadata are preserved.
The affected paper stops and reports the exact failed task. No retry or fallback
call is automatic. Scientific ambiguity or an unresolved repair quarantines
only the affected candidate group; other verified groups may continue.

## Acceptance Strategy

### Development proof

Use GP-004, GP-006, and GP-008 through Strategy 1 first and Strategy 2 only if
the escalation gate is met.

Before paid calls:

- all affected focused local tests pass;
- all task schemas and checksums pass;
- every task contains the exact fact and evidence for every requested
  candidate;
- every plausibly relevant experiment is represented by a compact semantic
  summary;
- the serialized request remains at or below the 6,000-token input ceiling and
  its worst-case response fits the configured output ceiling;
- text and visual candidates are separated, and every candidate that does not
  fit one task appears in another task or in human review;
- the response contract requires one complete candidate resolution per
  requested candidate ID;
- accepted visual candidates appear in exactly one route;
- the exact minimal retry set is presented for approval.

After approved calls and local merge:

- final verified recall is at least 13/15, with 15/15 retained as the target;
- all previously recovered 10 outcomes remain recovered;
- unsupported accepted outcomes equal `0`;
- wrong experiment links equal `0`;
- every requested candidate has exactly one final disposition;
- no invalid or truncated response is merged;
- precision meets the existing minimum of `0.9`.

Verified recall from 13/15 through 15/15 passes. A result of 12/15 or lower, or
any failure of the precision and safety requirements, invokes the Strategy 1
debugging and escalation rule. No paid rerun is automatic.

### New-paper generalization proof

After the development proof passes, retrieve one entirely new paper through
PubMed or Europe PMC. It must be absent from the gold set and current corpus,
report original LNP experiments, expose enough accessible full text for the
pipeline, and contain identifiable formulation, payload, experiment, and
outcome evidence. Record its PMID, PMCID or Europe PMC identifier, source URL,
retrieval date, full-text availability, and corpus-overlap check before
processing it.

Run the unchanged successful path on that paper. Success requires:

- raw source through local candidate and visual preparation completes;
- the primary paid gate presents a valid request;
- post-call misses route deterministically to confirmed, text repair, selective
  vision, or human review;
- every paid call has separate approval;
- all merged records pass evidence and experiment-link validation;
- a human can inspect one concise end-to-end report without reconstructing the
  route from multiple directories.

This proof does not use a recall denominator because the paper is outside the
development gold set. It evaluates route completion, auditability, evidence
support, and experiment linkage instead.

## Limitation Matrix

The design explicitly covers the known ways the route can fail:

| Limitation | Required safeguard |
| --- | --- |
| The model reports fewer candidates than were requested | Exact set equality between requested candidate IDs and candidate resolutions |
| Candidate IDs lack enough scientific meaning | Atomic fact, exact evidence, and every plausible compact experiment summary travel together |
| Semantic context makes requests too large | Hard 6,000-token input preflight and dynamic task splitting without dropping candidates or experiments |
| Responses truncate | Worst-case output estimation, smaller dynamic batches, and raw-response persistence before parsing |
| Text and visual evidence compete for context | Separate narrow-text and selective-vision tasks |
| A comparison spans several arms | One encompassing experiment and an explicit comparator, not duplicate outcomes |
| The same finding truly occurs in distinct experiments | One candidate resolution may contain distinct experiment-linked outcomes |
| Classification remains scientifically ambiguous | Quarantine only that candidate group for human review |
| A model invents or mislinks an experiment | Known-ID, evidence, permission, and structural-compatibility validation before merge |
| A repair duplicates an existing result | Compact existing outcome summaries plus deterministic deduplication checks |
| Repair calls recursively expand | One targeted repair attempt, then human review |
| Development answers leak into extraction | Gold IDs and answers are excluded from extraction-time requests |
| A local preparation unexpectedly spends money | Every paid batch requires a separate reviewed summary and `--confirm-paid-call` |
| Cached artifacts are stale or mismatched | Source identity, checksum, schema, and cache validation before reuse |
| The streamlined change hides an architectural problem | One root-cause classification, at most one bounded correction, then automatic escalation to Strategy 2 |
| The route works only on the development set | The unchanged successful path is run on a newly retrieved non-gold paper |

## Test Strategy

### Contract and builder tests

- One candidate with one plausible experiment carries its compact summary.
- One candidate with several plausible experiments carries every summary and
  lets the response classify the relationship.
- A missing experiment can be created only when the task explicitly permits
  one.
- A candidate can resolve to distinct experiment-linked outcomes when the
  evidence supports repetition across experiments.
- A multi-arm comparison resolves to one encompassing experiment with its
  comparator preserved.
- Every candidate fact appears exactly once.
- Dynamic packing spills complete candidates into additional tasks when either
  token ceiling would be exceeded.
- No packing operation silently drops a candidate, its evidence, or a plausible
  experiment summary.
- Existing v1.0/v1.1 cached tasks remain readable where required.

### Runner tests

- Paid stages refuse to run without `--confirm-paid-call`.
- Every candidate has exactly one allowed resolution status.
- Returned outcomes and experiments must be explicitly linked through a
  candidate resolution.
- Unknown or unpermitted experiment IDs fail validation.
- Raw responses are persisted before schema parsing.
- Truncated output produces a stopped, resumable diagnostic state and no retry.

### Routing tests

- Text misses create narrow text tasks only.
- Visual misses create selective-vision tasks only.
- Confirmed candidates create no repair task.
- Contradicted candidates and structurally invalid artifacts make no API call.
- Scientific ambiguity after a valid response quarantines only the affected
  candidate group.
- One visual object is not bundled with unrelated text candidates.

### Merge tests

- Structurally valid candidate-linked outcomes merge.
- Wrong experiment links fail.
- Broad outcomes that do not confirm atomic candidates fail.
- Extra unrelated outcomes fail.
- Unresolved candidates remain quarantined without blocking unrelated verified
  candidates.
- Every candidate-to-outcome-to-experiment disposition remains auditable,
  including one-to-many resolutions.

### End-to-end tests

- Offline saved-response run exercises local preparation through final
  evaluation with zero API calls.
- GP-004 regression covers the unique eGFP target and ambiguous HGF/EGF
  targets.
- GP-006 covers distinct reporter-expression and gene-editing experiments.
- GP-008 covers local visual promotion and targeted selective-vision fallback.
- The development acceptance run evaluates verified merged recall, not merely
  candidate detection.
- A 13/15, 14/15, or 15/15 safe result passes the development gate; 12/15 or a
  safety failure invokes the documented debugging and escalation rule.
- The new-paper run records its external identifier and proves it is absent
  from both the gold set and existing corpus before ingestion.

## Implementation Method

Implementation must use `superpowers:subagent-driven-development`. Each
implementation task receives an independent review through
`superpowers:requesting-code-review` before the next task, followed by a final
whole-change review. Tests are written before production changes.
`superpowers:systematic-debugging` is mandatory for every test failure,
unexpected result, or below-threshold paid evaluation before a fix is proposed.
No paid test call or rerun occurs until all applicable local tasks, reviews, and
exact-request preflights pass and the user gives explicit approval.
