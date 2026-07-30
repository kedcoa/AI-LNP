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
because experiment association was reduced to a Boolean existence check during
task construction:

- an associated provisional experiment caused
  `permitted_new_experiments` to become `0`;
- the task received every existing experiment ID;
- the task did not receive one exact target experiment ID;
- a provisional experiment could correspond to zero, one, or several existing
  experiments;
- the model could not safely attach recovered outcomes when the target was
  absent or ambiguous.

One GP-008 response also exceeded the 4,000-token output limit after a visual
candidate was bundled with four text candidates. Because the raw response was
persisted only after schema parsing, the truncated response was not retained.

## Goals

1. Preserve a unique existing experiment target through repair task creation,
   model response validation, deterministic verification, and merge.
2. Refuse paid calls when the experiment target is ambiguous.
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
  disposition, unsupported evidence, or wrong experiment linkage stops the
  pipeline.
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

### 4. Experiment-target decision

Repair tasks are already grouped by one provisional experiment. Task
construction must invert the existing output-experiment association:

- **One compatible existing experiment:** set
  `target_experiment_id` to that exact ID and set
  `permitted_new_experiments` to `0`.
- **No compatible existing experiment:** set `target_experiment_id` to `null`
  and set `permitted_new_experiments` to `1`.
- **Several compatible existing experiments:** create no paid task. Record the
  candidate group as human review until its boundary is refined or a human
  selects the target.

`MissingRecordTask` advances to a new compatible version with one task-level
`target_experiment_id`. A separate candidate-to-target data model is
unnecessary because every task contains candidates from one provisional
experiment.

### 5. Paid targeted repair

Text misses use the existing missing-record/narrow-repair runner. Visual misses
use the existing selective-vision runner with only the relevant crop, caption,
local visual context, candidate facts, and target decision.

The orchestrator prepares repair batches locally and stops. Each text or vision
batch requires human review plus `--confirm-paid-call`. A primary-call approval
does not authorize repair calls.

Visual repair tasks should contain one visual object and the smallest candidate
group supported by that object. They must not rebundle unrelated text
candidates into a large visual response.

### 6. Verification and merge

Existing validation and structural coverage remain authoritative. Before a
repair fragment can merge:

1. recovered and unresolved candidate IDs must exactly equal the requested
   candidate IDs;
2. returned evidence IDs must be within the task evidence;
3. when `target_experiment_id` is present, every returned outcome must reference
   that experiment;
4. when a new experiment is permitted, exactly one new experiment may be
   returned and every new outcome must reference it;
5. structural coverage must independently confirm every recovered candidate;
6. every new outcome must confirm at least one requested candidate;
7. unresolved candidates keep finalization blocked.

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
- target experiment decisions;
- input and output token limits;
- exact prepared request paths;
- cache status.

Without `--confirm-paid-call`, it exits successfully after preparation. It never
prompts interactively inside an unattended command and never treats a previous
approval as permission for a later repair stage.

On a paid-call failure, the raw response and request metadata are preserved.
The pipeline stops and reports the exact failed task. No retry or fallback call
is automatic.

## Acceptance Strategy

### Stage 1: frozen development proof

Use GP-004, GP-006, and GP-008 through the general command.

Before paid calls:

- all local tests pass;
- all task schemas and checksums pass;
- each paid task has a unique existing target or permission for exactly one new
  experiment;
- ambiguous multi-match groups make no call;
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

## Test Strategy

### Contract and builder tests

- Unique inverse association produces the exact target experiment ID.
- Zero inverse associations permits exactly one new experiment.
- Multiple inverse associations produce human review and no paid task.
- Every candidate fact appears exactly once.
- Existing v1.0/v1.1 cached tasks remain readable where required.

### Runner tests

- Paid stages refuse to run without `--confirm-paid-call`.
- Every candidate is recovered or unresolved exactly once.
- Returned outcomes cannot reference a non-target existing experiment.
- Raw responses are persisted before schema parsing.
- Truncated output produces a stopped, resumable diagnostic state and no retry.

### Routing tests

- Text misses create narrow text tasks only.
- Visual misses create selective-vision tasks only.
- Confirmed candidates create no repair task.
- Contradictions and ambiguous target mappings make no API call.
- One visual object is not bundled with unrelated text candidates.

### Merge tests

- Correct target-linked outcomes merge.
- Wrong experiment links fail.
- Broad outcomes that do not confirm atomic candidates fail.
- Extra unrelated outcomes fail.
- Unresolved candidates block finalization.
- Candidate and outcome dispositions remain one-to-one auditable.

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

