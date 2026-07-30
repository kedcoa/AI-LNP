# Cohesive Extraction Pipeline Design

**Date:** 2026-07-30

## Purpose

Make the existing AI-LNP extraction stages operate as one cohesive pipeline
without introducing another extraction, vision, coverage, or merge
implementation. The first acceptance run uses GP-004, GP-006, and GP-008 to
prove verified 15/15 development recall. The same code path must then run on a
new non-gold paper.

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
6. Provide one resumable command that coordinates existing stages and treats
   their current artifacts as the source of truth.
7. Prove the path first on GP-004, GP-006, and GP-008, then run the unchanged
   path on a new non-gold paper.

## Non-goals

- Do not create a new extractor, candidate model, vision model, coverage
  algorithm, or merge algorithm.
- Do not run every vision method on every figure or table.
- Do not automatically retry failed, invalid, or truncated paid responses.
- Do not use gold outcome IDs or gold answers in extraction-time inputs.
- Do not delete legacy scripts as part of this improvement.
- Do not claim 15/15 from candidate detection alone; only verified merged
  outcomes count.

## Design Principles

- **One active route:** documentation and the new command identify one
  authoritative path even if legacy scripts remain available.
- **Thin coordination:** the orchestrator calls existing stage functions and
  checks their artifacts; it does not reproduce their scientific logic.
- **Fail closed:** ambiguous identity, invalid schema, missing candidate
  disposition, unsupported evidence, or wrong experiment linkage cannot merge.
  Scientific ambiguity quarantines only the affected candidate group; corrupted
  artifacts or invalid paid responses stop the paper.
- **No hidden spending:** local preparation is the default. Every paid stage
  requires a separate explicit invocation and confirmation flag.
- **No throwaway development path:** GP-004, GP-006, and GP-008 use the same
  general code that later processes new papers.

## Architecture

### 1. Local pre-call preparation

The orchestrator invokes or verifies the existing stages for:

1. paper ingestion and compact packet construction;
2. provisional experiment construction;
3. atomic text candidate construction;
4. Docling table and layout extraction;
5. deterministic table candidate construction;
6. local-VLM figure interpretation where the existing gate permits it;
7. promotion of accepted visual claims into the same candidate inventory;
8. exact request and schema preflight.

These stages make no paid API calls. The orchestrator reports candidate counts,
evidence counts, visual routes, estimated tokens, and all experiment-routing
decisions before stopping at the primary-call approval gate.

### 2. Paid primary extraction

The primary call remains the existing compact extraction implementation. The
orchestrator may execute it only when:

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

The orchestrator prepares repair batches locally and stops. Each text or vision
batch requires human review plus `--confirm-paid-call`. A primary-call approval
does not authorize repair calls.

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

## Thin Orchestrator

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
- relevant experiment summaries and proposed candidate scope;
- input and output token limits;
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

### Stage 1: frozen development proof

Use GP-004, GP-006, and GP-008 through the general command.

Before paid calls:

- all local tests pass;
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

- final verified recall is 15/15;
- all previously recovered 10 outcomes remain recovered;
- unsupported accepted outcomes equal `0`;
- wrong experiment links equal `0`;
- every requested candidate has exactly one final disposition;
- no invalid or truncated response is merged;
- precision meets the existing minimum of `0.9`.

If 15/15 is not reached, the run is considered diagnostic evidence. The system
must stop without broadening scopes or automatically repeating calls.

### Stage 2: generalization proof

Run the unchanged command on one new non-gold paper. Success requires:

- raw source through local candidate and visual preparation completes;
- the primary paid gate presents a valid request;
- post-call misses route deterministically to confirmed, text repair, selective
  vision, or human review;
- every paid call has separate approval;
- all merged records pass evidence and experiment-link validation;
- a human can inspect one concise end-to-end report without reconstructing the
  route from multiple directories.

This stage does not use 15/15 as its metric because the paper is outside the
development gold set.

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
| The route works only on the development set | The unchanged pipeline is run on a new non-gold paper in Stage 2 |

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

## Implementation Method

Implementation must use `superpowers:subagent-driven-development`. Each
implementation task receives an independent review before the next task. Tests
are written before production changes, and no paid test call occurs until all
local tasks, reviews, and exact-request preflights pass and the user gives
explicit approval.
