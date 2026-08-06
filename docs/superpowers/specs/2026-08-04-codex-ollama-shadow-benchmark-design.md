# Codex CLI and Ollama Shadow Benchmark Design

**Date:** 2026-08-04

**Status:** Approved for implementation planning

## Goal

Determine in one working day whether Codex CLI can serve as a non-destructive
scientific auditing agent and whether Codex CLI with Ollama can safely replace
any saved Gate B text extraction calls. If the local extraction route does not
pass the benchmark, retain the existing OpenAI calls and move on to paper
discovery, database loading, and UI work instead of tuning the local model.

## Current Evidence

The v5.2 three-paper pilot defines 62 application-critical requirements. Its
strict frozen score is 28/62, its automated evidence-grounded score is 40/62,
and a post-hoc hosted Codex scientific audit recovered 57/62 requirements fully
and 60/62 fully or partially. The science-audited artifacts contain five fully
complete arms out of seven.

The repository already provides:

- frozen extraction and evaluation artifacts;
- stable experiment, candidate, outcome, and evidence identifiers;
- strict schema and provenance validators;
- deterministic structural coverage and candidate-accounting checks;
- a saved 12-call Gate B repair workload with a conservative 44,645-token
  input upper bound; and
- an Ollama visual benchmark whose isolation, abstention, and artifact patterns
  can inform this text benchmark.

Codex CLI 0.146.0-alpha.3.1 is installed and exposes an Ollama local-provider
route. The local Ollama client is installed, but model/server availability must
be treated as a benchmark preflight result rather than assumed.

## Scope

### In scope

1. Replay the saved three-paper artifacts through a read-only Codex CLI audit.
2. Replay saved Gate B text tasks through Codex CLI with Ollama.
3. Normalize both routes into a common result envelope.
4. Apply the existing deterministic schema, ID, evidence, relationship, and
   accounting rules before scoring recall.
5. Score all 62 application-critical requirements, including the subset needed
   to form COMET-ready formulation-experiment-outcome rows.
6. Measure attempt dispositions, recall, safety findings, latency, and tokens
   when the backend reports token usage.
7. Produce separate adoption decisions for the auditor and local extractor.

### Out of scope

- Changing accepted records or production routing.
- Replacing Gate A paper mapping.
- Replacing selective vision.
- Running new paper ingestion.
- Making paid OpenAI calls.
- Tuning or repeatedly retrying a failing local model.
- Training COMET or claiming generalization beyond hepatocyte outcomes.

## Architecture

The benchmark is an isolated shadow layer around v5.2:

```text
Frozen saved artifacts
    |-- audit replay --> Codex CLI auditor --> audit score
    `-- Gate B replay --> Codex CLI/Ollama --> extraction score
                                                 |
                         deterministic safety and recall gates
                                                 |
                     pass: later shadow eligibility
                     fail: retain existing OpenAI calls
```

Production records remain immutable. Every replay case is derived from saved
artifacts and written to a new benchmark-specific run directory. Gold labels
are loaded only by the scorer after inference and must never enter prompts,
request manifests, or model-readable working files.

The design separates two independent decisions:

- **Auditor decision:** whether Codex CLI can reliably identify omissions,
  unsupported relationships, wrong-arm associations, incomplete required
  fields, and COMET-readiness gaps.
- **Extractor decision:** whether the selected Ollama model can return safe,
  schema-valid Gate B text results with acceptable recall.

An extractor failure does not invalidate an auditor pass. Passing either
benchmark authorizes only a later shadow rollout, not an immediate production
replacement.

## Components and Responsibilities

### Case builder

Builds audit cases and Gate B replay cases from the frozen three-paper inputs.
It records source paths and checksums, preserves issued IDs, and rejects any
case whose dependencies are missing or whose source artifacts have changed.

### Backend adapters

Adapters run a case through a saved/mock backend, hosted Codex CLI audit route,
or Codex CLI with the Ollama local provider. They do not score results. All
adapters return the same normalized result envelope.

### Normalized result envelope

Each attempted case records:

- run ID, case ID, task type, backend, and model identity;
- source and prompt checksums;
- start time, wall-clock duration, process exit code, and terminal disposition;
- input and output token counts when reported, otherwise an explicit null with
  a reason;
- raw-output artifact reference and parsed structured result;
- schema, issued-ID, evidence, numeric-support, relationship, and accounting
  findings; and
- requirement-level matches produced after inference by the scorer.

Terminal disposition is exactly one of:

- `accepted`;
- `rejected_by_validation`;
- `model_abstained`;
- `schema_failure`;
- `timeout_or_runtime_failure`; or
- `requires_human_review`.

### Deterministic validator

Reuses existing contracts and validation rules. It runs before recall scoring
and rejects invented experiment, candidate, outcome, or evidence IDs;
unsupported exact numbers; incompatible treatment-arm or formulation links;
and incomplete candidate accounting. Model-authored confidence or acceptance
labels never override deterministic findings.

### Requirement scorer

Loads the 62 gold requirements only after inference. It performs one-to-one
matching where required and reports full, partial, missing, and unsafe matches.
Audit and extraction results are scored independently. COMET readiness is a
separate projection over complete, compatible formulation-experiment-outcome
rows rather than a synonym for general extraction recall.

### Decision report

Produces one of four recommendations with supporting evidence:

1. adopt the Codex auditor in shadow mode;
2. continue a low-risk Ollama text shadow trial;
3. retain OpenAI extraction calls; or
4. insufficient evidence because preflight or benchmark execution was
   incomplete.

## Benchmark Inputs

The primary benchmark is the saved three-paper pilot and all 62
application-critical requirements. Cases must exercise:

- formulation identity, components, and composition;
- payload and administration;
- biological model and liver cell type;
- experiment, comparator, and treatment-arm linkage;
- outcome endpoint, value, unit, direction, and normalization;
- evidence provenance and exact-number support; and
- fields required to form hepatocyte-specific COMET candidate rows.

The Gate B replay set must be frozen before the first model run. No case may be
removed after seeing model output. A preflight failure is recorded as a result,
not silently excluded from the denominator.

## Acceptance Gates

### Shared safety gates

| Gate | Required result |
|---|---:|
| Schema-valid accepted outputs | 100% |
| Invented issued IDs in accepted outputs | 0 |
| Unsupported exact numeric claims in accepted outputs | 0 |
| Wrong formulation-experiment or treatment-arm links in accepted outputs | 0 |
| Candidate accounting for issued candidates | 100% |
| Attempt disposition coverage | 100% of issued benchmark cases |
| Production writes | 0 |

Attempt disposition coverage means every issued case has a recorded terminal
state. It does not require every model attempt to succeed. Abstention and model
failure rates are measured and reported without a fixed pass threshold.

### Auditor quality gates

- Full recovery of at least 90% of the 62 requirements.
- Every unsafe or unsupported relationship in the frozen review set is flagged.
- At least five of seven application-critical arms are recognized as complete
  when the evidence supports them.

### Ollama Gate B quality gates

- Recall is at least 85% of the cached hosted OpenAI result on the identical
  replay cases. The scorer derives this baseline from the saved accepted
  responses; it makes no new hosted call.
- At least five of seven application-critical arms are complete after validated
  local outputs are projected into the frozen merged view.
- Every shared safety gate passes.

Any shared safety-gate failure requires retaining OpenAI for extraction. A
quality-gate miss also retains OpenAI unless the final report classifies the
run as insufficient evidence because benchmark infrastructure failed before a
valid comparison could be made.

## Error Handling and Stop Rules

- Missing or checksum-mismatched source artifacts fail preflight before model
  invocation.
- Malformed output is preserved verbatim, classified as `schema_failure`, and
  never repaired with gold information.
- Timeouts and nonzero CLI exits are classified as
  `timeout_or_runtime_failure` with stderr preserved.
- Three consecutive systemic failures of the same class trigger an early stop.
  The denominator and every unattempted case remain visible; unattempted cases
  receive no terminal attempt disposition and are reported separately from the
  issued-attempt disposition denominator.
- An unavailable Ollama server or missing model yields `insufficient evidence`
  for the extractor unless it can be corrected within the time box without
  downloading or tuning a new model.
- The benchmark never falls back to paid calls automatically. The operational
  decision after a local failure is to retain the existing OpenAI production
  route.

## Test Strategy

Unit and integration tests must prove:

1. Audit and Gate B cases are built from the intended frozen inputs.
2. Gold requirements cannot enter prompts or model-readable manifests.
3. Source and prompt checksums are stable and verified.
4. Unknown issued IDs and evidence IDs are rejected.
5. Unsupported exact numbers and wrong-arm associations are rejected.
6. Every issued attempt receives exactly one terminal disposition, including
   timeout, malformed output, and abstention paths.
7. The scorer performs requirement-level and one-to-one matching correctly.
8. Auditor and extractor decisions are independent.
9. Failed local extraction produces `retain_openai`, never an implicit
   production promotion.
10. The report exposes token counts, latency, denominators, skipped cases, and
    stop reasons without treating missing measurements as zero.

Tests use fixtures, fake subprocess runners, and saved responses. Paid calls are
not unit tests. The live local replay is a separately invoked benchmark step.

## Artifact Policy

All new outputs are append-only under benchmark-specific directories in
`data/staging/extraction/` and `reports/extraction/`. Run directories contain a
timestamp or unique run ID and refuse overwrite. Raw provider output remains
separate from parsed and accepted results. Existing accepted graphs, frozen
results, production configuration, and gold fixtures are never changed by the
runner.

## Same-Day Schedule and Budget

Assume seven to eight focused hours remain.

| Phase | Duration | Model usage |
|---|---:|---:|
| Freeze inputs and inventory exact cases | 30 min | 0 inference tokens |
| Write harness and failing unit tests | 75 min | about 25k-50k Codex development tokens |
| Implement validators and scorer | 60 min | about 20k-40k Codex development tokens |
| Run Codex CLI audit replay | 45-75 min | target input <=60k and output <=20k |
| Run Ollama Gate B replay | 60-90 min | expected input 45k-70k and output <=25k, local inference |
| Score and inspect failures | 45 min | 0-15k Codex analysis tokens |
| Document the decision and fallback | 30 min | about 5k-10k Codex tokens |
| Start discovery/database/UI handoff | remaining 2-3 h | separately budgeted |

The practical Codex allowance for implementation, testing, and analysis is
approximately 75k-150k total context/output tokens. This is a planning range,
not an API invoice estimate. Local Ollama inference incurs no OpenAI inference
tokens. The existing saved OpenAI repair workload, 12 calls and at most 44,645
input tokens, is the comparison point for the replay set.

## End-of-Day Decision and Handoff

The benchmark receives a firm cutoff. If Ollama fails or cannot be evaluated
within its time box, record the result, retain OpenAI, and stop local-model work.
Paper discovery, database loading, and UI work proceed regardless of the local
model outcome.

The successful end-of-day deliverables are therefore:

1. an evidence-backed Codex auditor decision;
2. an evidence-backed Ollama Gate B decision or an explicit insufficient-
   evidence result;
3. a retained OpenAI fallback whenever local extraction is not proven safe;
4. reusable tests and benchmark artifacts; and
5. no further extraction-architecture work blocking the next product phase.
