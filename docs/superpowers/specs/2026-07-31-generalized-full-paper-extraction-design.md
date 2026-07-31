# Generalized Full-Paper Extraction Design

## Purpose

Build a gold-blind workflow that can extract a complete LNP paper at two
levels:

1. shared paper-level facts, such as formulation components, ratios, payloads,
   routes, species, and models;
2. experiment-level facts, such as formulation/payload/dose/cell/timepoint
   arms and their linked outcomes.

NP-002 is the first evaluation paper, not a source of hardcoded production
rules. Its hidden answer key is used only after all extraction artifacts have
been written.

## Alternatives Considered

### One whole-paper call

This is the smallest call count, but repeats the failure mode in which the
model selects a few convenient records and silently misses other contexts.

### One call per experimental arm

This maximizes isolation but duplicates shared methods evidence, raises cost,
and does not scale.

### Shared paper map plus packed context calls — selected

One paper-map call extracts shared formulation/method facts and enumerates
biological contexts. Local code then builds evidence-backed arm candidates and
packs scientifically compatible candidates into context calls. This preserves
the successful forced-accounting design while avoiding one call per arm.

## Workflow

### Stage 1: Complete local ingestion

Ingest the full document into section-aware evidence records from body text,
methods, captions, and tables. Evidence records carry stable IDs, section
labels, page/locator information, and retrieval tags.

The ingestion completeness gate reports whether the inventory contains
evidence candidates for:

- formulation or preparation methods;
- payload;
- model/species/route;
- recipient cell or organ;
- outcomes;
- tables or figure captions when present.

The gate detects missing categories; it does not invent scientific facts.

### Stage 2: Shared paper-map call

The first paid call receives compact evidence selected across the entire paper,
including methods. It returns:

- formulations, components, ratios, and ratio bases;
- payload identities and roles;
- common route, species, and models;
- detected organs and recipient-cell contexts;
- provisional experiment-context specifications;
- exact evidence IDs for every reported field.

The response schema requires accounting for every locally detected anchor
candidate. Local validation rejects invented IDs and unsupported facts.

### Stage 3: Generic arm construction

Local code builds candidate arms from the paper map and exact evidence. The
identity tuple is data-driven:

`formulation × payload × dose × dose unit × route × species × experimental
model × recipient cell × timepoint`.

No formulation name, payload, dose, assay, cell type, candidate count, or paper
ID is hardcoded. Cross-products are created only when direct evidence supports
joint membership or explicit paired/cross-product language.

### Stage 4: Packed context extraction calls

Candidates are grouped by recipient-cell/organ context and compatible evidence.
Each task includes:

- the applicable shared formulation record;
- exact arm candidate specifications;
- exact arm and outcome evidence;
- a dynamic schema requiring one accounting entry per candidate ID.

Packing is token-budget driven. A new task starts when the next compatible
candidate would exceed the input budget. It is not fixed at six candidates or
one call per cell type.

### Stage 5: Local validation and merge

For every returned arm, local validation checks:

- exact candidate-ID accounting;
- formulation, payload, role, dose, route, model, recipient, and timepoint;
- assay/endpoint compatibility derived from the candidate specification;
- formulation–experiment–outcome links;
- candidate-specific evidence support;
- no incompatible outcome reuse.

Shared records are merged once by normalized identity and evidence. Experiment
records retain separate arm identities.

### Stage 6: Selective repair

Only unresolved candidates are eligible for repair. Text and visual candidates
are separated. The orchestrator produces a zero-call repair preview with exact
candidate counts, tasks, token estimates, and proposed paid calls, then pauses
for approval.

## Hidden NP-002 Answer Key

The answer key contains atomic expected facts in two namespaces:

- `shared_facts`: formulations, lipid identities, ratios and bases, common
  methods, payloads, routes, species, and models;
- `experiment_facts`: arm identities, recipient cells, assays, endpoints,
  comparators, qualitative results, and numeric results when reported.

Each item has a stable gold ID, expected normalized value, acceptable aliases,
source evidence, and criticality. It is stored separately from request
preparation code.

The workflow must write and hash all request/response artifacts before the
evaluator can load the answer key. Tests fail if production modules import the
gold path.

## Scoring

Primary overall recovery is unweighted micro-recall:

`correct expected atomic facts / total expected atomic facts`.

The report also includes:

- shared-paper recall;
- experiment-level recall;
- complete-arm recall;
- precision over extracted facts;
- unsupported-invention count;
- wrong-arm-link count;
- missing gold IDs;
- per-cell-context recall.

The new score is reported beside, not silently substituted for, the previous
72% measurement. Any denominator differences are explicit.

## NP-002 Evaluation Scope

The first end-to-end benchmark covers all liver contexts reported in NP-002:

- Kupffer cells;
- endothelial cells;
- hepatocytes;
- shared formulation and preparation evidence.

The expected initial preflight is one shared paper-map call plus as many packed
context calls as the token budget requires. Calls are prepared locally and
shown with exact hashes and estimates before execution.

## Safety and Generalization Constraints

- No paid call without explicit approval.
- No NP-002, KUP, MC3, cKK-E12, QUANT, Cre, Ai14, or fixed-six logic in generic
  production modules.
- NP-002-specific expected facts exist only in the benchmark fixture.
- The answer key is never included in prompts or candidate construction.
- Existing text, table/Docling, selective-vision, evidence merge, and compact
  contract components are reused rather than reimplemented.

## Acceptance Criteria

- Generic synthetic tests work with unrelated formulation names, payloads,
  models, cell types, doses, and candidate counts.
- NP-002 preparation discovers shared formulation evidence including the
  50:38.5:1.5:10 molar ratio and 10:1 lipid-to-nucleic-acid mass ratio.
- Prepared tasks cover Kupffer, endothelial, and hepatocyte contexts.
- The evaluator detects intentional gold leakage.
- A local preflight reports exact proposed calls and tokens and stops for human
  approval.
