# LNP Paper Screening Guide

- Rules version: `1.0.0`
- Screening unit: paper–cell–task
- Primary screening task: `liver_cell_lnp_evidence`
- First conditional modeling cell: hepatocyte
- Supported cells: hepatocyte, Kupffer cell, LSEC, and HSC

The machine-readable policy is defined in
`docs/screening/screening_rules_v1.yaml`.

## Purpose

Screening determines whether a publication should advance to detailed
formulation, experiment, outcome, and evidence extraction.

A paper is a discovery container. A paper is not a COMET training example.

A training example is a separately validated formulation-experiment-outcome
record with adequate composition, chemical identity, experimental context,
label evidence, and split-group provenance.

## Screening unit

Each decision applies to one paper, one configured cell type, and one task.

The same publication may receive different decisions for different cells.

Example:

- Paper A + hepatocyte + evidence screening: `include`
- Paper A + Kupffer cell + evidence screening: `exclude`
- Paper A + LSEC + evidence screening: `manual_review`

## Decisions

### `include`

Use `include` only when all mandatory criteria are supported:

1. The publication reports an original experiment.
2. The delivery system is identifiable as an eligible LNP.
3. The payload is supported by the configured task.
4. Eligible target-cell evidence is present.
5. A formulation can plausibly be linked to an experiment and outcome.

### `exclude`

Use `exclude` when a mandatory criterion clearly fails.

Examples include:

- A review with no original experiment.
- A delivery system that is clearly not an LNP.
- A clearly unsupported payload.
- No experimental evidence for the configured cell.
- No usable formulation-outcome linkage.
- A retracted or invalid publication.

### `manual_review`

Use `manual_review` when the paper may be eligible but the available material
is insufficient, ambiguous, or contradictory.

Examples include:

- Full text is required.
- LNP identity is unclear.
- The target cell is mentioned but experimental relevance is unclear.
- Several formulations and outcomes cannot be linked.
- Chemical identities or abbreviations are ambiguous.
- Critical formulation information may be in a table, figure, or supplement.

`manual_review` is a valid decision. It is not a weaker form of `include`.

## Decision precedence

Apply decisions in this order:

1. Retracted or invalid publication: `exclude`
2. A mandatory criterion clearly fails: `exclude`
3. A mandatory criterion is unresolved: `manual_review`
4. All mandatory criteria are supported: `include`

Do not treat missing information as proof of ineligibility.

## Original experiment

An eligible publication must report original experimental results.

Reviews, editorials, commentaries, and similar secondary publications are
excluded unless they contain a separately identifiable original experiment.

Conference abstracts, protocols, corrections, and unclear publication types
require manual review.

## Identifiable LNP

The publication must test a lipid nanoparticle relevant to the project.

A generic mention of “nanoparticle” is insufficient when the carrier type
cannot be resolved.

Incomplete composition does not automatically require paper exclusion. If the
paper may contain an eligible LNP but critical details require full text,
tables, figures, or supplements, use `manual_review`.

## Supported payloads

The broad evidence-screening task currently supports:

- mRNA
- siRNA
- saRNA
- circRNA

These categories apply to evidence screening. They do not establish that an
example is compatible with COMET.

If a payload category cannot be determined, use `manual_review`.

## Target-cell evidence

Discovery keyword matches identify candidates; they do not prove cell-specific
experimental evidence.

### Direct

The outcome is directly measured in the configured cell or a clearly
identified cell-resolved population.

Direct evidence satisfies the target-cell criterion by default.

### Indirect

The result suggests relevance but is not a direct cell-specific measurement.

Indirect evidence requires `manual_review`.

### Mentioned only

The cell appears in metadata, title, abstract, background, or discussion but
not in an eligible experiment.

Use `exclude` for that paper–cell–task combination.

### Absent

No relevant target-cell evidence is present.

Use `exclude`.

### Unclear

Available source material cannot resolve the evidence level.

Use `manual_review`.

General liver biodistribution does not automatically establish hepatocyte,
Kupffer-cell, LSEC, or HSC evidence.

## Formulation-outcome linkage

At least one identifiable formulation must plausibly link to an experimental
context and outcome.

Use `manual_review` when:

- Multiple formulations are reported but the outcome mapping is unclear.
- Outcomes are presented only in a figure or supplement.
- Formulation names change across sections.
- The tested formulation cannot be distinguished from a comparator.

Do not infer ratios, identities, units, comparators, or outcomes.

## Evidence recording

Every screening decision must preserve:

- Supporting evidence text or a structured observation.
- Evidence location type.
- Source identifier.
- Rules version.
- Reviewer.
- Review date.

Evidence locations may include metadata, title, abstract, Methods, Results,
table, figure, caption, or supplement.

## Cell identifiers

Discovery and database vocabulary differ for Kupffer cells:

- Discovery key: `kupffer`
- Canonical database value: `kupffer_cell`

The screening rules preserve this mapping. Do not rewrite Day 3 discovery
records.

Canonical screening cell values are:

- `hepatocyte`
- `kupffer_cell`
- `lsec`
- `hsc`

## Evidence screening versus COMET readiness

Broad evidence screening supports all four cells and the four initial payload
categories.

Hepatocyte COMET adaptation remains conditional. Paper inclusion does not mean:

- The paper is one training example.
- Every formulation is sufficiently specified.
- Outcomes are mutually comparable.
- The record is compatible with a preregistered COMET task.
- The readiness threshold has passed.

COMET training requires a later readiness audit of validated
formulation-experiment-outcome records.

## Gold-set selection

Build a candidate pool of approximately 12–16 papers and provisionally select
8–12 for field-level annotation.

The selected set must represent all four cells and include:

- Likely includes.
- Clear likely excludes.
- Manual-review cases.
- Structured tables.
- PDF tables or figures.
- Incomplete formulations.
- Irrelevant keyword hits.
- Ambiguous chemistry.
- Multi-formulation or multi-cell cases where available.

The gold set evaluates screening and extraction behavior. It is not intended
to estimate literature prevalence.

## Prohibited practices

Reviewers and automated systems must not:

- Infer missing formulation ratios.
- Infer chemical identities from unsupported abbreviations.
- Infer target-cell evidence from a keyword match.
- Treat a paper as one training example.
- Treat a prediction as a measurement.
- Treat similarity as efficacy prediction.
- Weaken inclusion rules to satisfy the COMET sample threshold.
- Automatically include ambiguous records.
- Silently replace selected gold papers.

## Morning-to-afternoon handoff

The morning is complete when:

- Screening decisions and reason codes are frozen.
- Cell and task configuration is explicit.
- A representative 12–16-paper candidate pool exists.
- Eight to twelve papers are provisionally selected.
- Every selected paper is traceable to the Day 3 corpus.

The afternoon will annotate the selected papers at field level and freeze
expected answers and evidence locations.
