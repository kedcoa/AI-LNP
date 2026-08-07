# SQLite Human-Review Workspace Design

**Status:** Approved interaction design awaiting implementation plan

## Goal

Connect the approved queue-first Streamlit reviewer to the authoritative SQLite evidence database so human decisions are persistent, traceable, and immediately reflected in nearest-neighbor and COMET eligibility.

By end of day, the interface must provide two primary numbers:

1. the number of experimental arms currently eligible for COMET; and
2. the number of usable, evidence-backed field facts, separated into automatically validated and manually verified facts.

It must also show each paper's physical database-row breakdown.

## Safety Model

The interface never performs untracked cell replacement. Each accepted or corrected decision creates an immutable `review_revision` record containing:

- the original extracted value;
- the active corrected value;
- the evidence excerpt and location;
- the reviewer name or local reviewer label;
- the decision type and reviewer note;
- the review timestamp; and
- the prior revision when the decision supersedes an earlier correction.

The active scientific record is updated transactionally only after the revision is valid. The original extraction and evidence remain unchanged as provenance. The main interface shows the active value; extraction history appears only when the reviewer expands **Review history**.

Before enabling writes, the application verifies SQLite integrity and creates a timestamped backup outside the repository. The interface refuses writes when integrity, foreign keys, schema version, or backup verification fails.

## Dashboard Metrics

### COMET-ready arms

Count distinct `experiment_id` values whose current `eligibility_result` for profile `comet` is eligible under the current rules version. Eligibility is recalculated after every committed review transaction.

### Nearest-neighbor-ready arms

Count distinct experiments whose current nearest-neighbor eligibility result is eligible.

### Usable field facts

A usable field fact is one canonical field-level relationship that:

- targets an existing paper, formulation, component, experiment, outcome, or evidence record;
- links to at least one existing evidence record owned by the same paper;
- has verification state `automatically_validated` or `manually_verified`;
- is not rejected, unresolved, or superseded; and
- is counted once by its canonical field-evidence identity even when the same excerpt is repeated.

The dashboard shows automatically validated and manually verified counts separately, plus their deduplicated combined total.

### Per-paper database rows

For every paper, show separate counts for:

- formulations;
- chemical components;
- experimental arms;
- outcomes;
- evidence excerpts;
- canonical usable field facts;
- open review items; and
- review-history revisions.

A total database-row column may sum the physical scientific and review rows, but the interface must not describe that sum as a scientific evidence count.

## Review Queue

The landing page retains the approved queue-first layout and uses real records. Queue priority is:

1. structurally complete arms awaiting verification;
2. arms missing only one or two COMET requirements;
3. target-cell or experiment-link confirmations;
4. conflicting values; and
5. broader incomplete or blocked records.

Filters include paper, review reason, target cell, species, payload, review status, and proximity to nearest-neighbor or COMET eligibility.

## Paper and Arm Workspace

The selected paper displays title, DOI, PMID/PMCID, publisher/DOI, PubMed/PMC, local full-text, and institutional-library access links when available. Links never imply that the application bypasses authentication or licensing.

The experimental-arm table shows active values and explicit blanks for formulation, composition ratio, target cell, delivery cell, species, biological model, delivery setting, route, payload, dose, assay, timepoint, and outcomes.

Selecting a field shows:

- all linked evidence excerpts;
- section, page, table, figure, or source-block location;
- source modality and extraction confidence;
- the active verification state; and
- collapsed review history.

## Review Actions

The reviewer can:

- accept the extracted value;
- enter and accept a corrected value;
- confirm that the field is not reported;
- flag evidence as belonging to another arm;
- reject unsupported evidence; or
- leave the field unresolved.

Every final action requires a reviewer note. Corrections additionally require selected supporting evidence. `Not reported` is an explicit review decision, not an empty string or scientific `NA` value.

## Transactional Write Flow

For one field decision:

1. open one SQLite transaction with foreign keys enabled;
2. re-read the current entity and reject stale browser state;
3. validate entity ownership, evidence ownership, decision, corrected value, and note;
4. insert an immutable review revision;
5. supersede the prior active review revision when applicable;
6. update the active scientific value or verification state;
7. resolve or create the relevant missing-field record;
8. recalculate arm completeness, nearest-neighbor eligibility, and COMET eligibility;
9. run foreign-key and decision consistency checks; and
10. commit, or roll back the entire decision on any failure.

The application displays the newly calculated eligibility and remaining blockers after commit.

## Isolation and Concurrency

- The authoritative database path is fixed through the existing common-checkout resolver.
- The browser cannot supply an alternate database path.
- Only one local reviewer/writer is supported initially.
- Reads use read-only connections; writes use short explicit transactions.
- Stale form submissions fail rather than overwriting a newer review.
- No API, LLM, Codex, DOI, or publisher call is needed for review or metrics.

## Testing

Tests must prove:

- dashboard metrics match controlled SQLite fixtures;
- usable facts are canonically deduplicated and correctly separated by verification state;
- per-paper row counts are exact;
- accepted, corrected, not-reported, rejected, wrong-arm, and unresolved flows behave as designed;
- original extraction and evidence remain unchanged;
- active values and review history update together;
- stale submission, invalid evidence ownership, and validation failure roll back completely;
- eligibility recalculates after commit;
- backup/integrity gating prevents unsafe writes;
- Streamlit reads the real database only through the reviewed service layer; and
- the existing authoritative database passes a read-only preflight before the interface is launched.

## Out of Scope

- Public end-user search UI;
- multi-user authentication and concurrent editing;
- remote hosting;
- automatic DOI/full-text downloading;
- institutional credential storage;
- bulk spreadsheet review;
- paid extraction or repair calls; and
- changing production COMET eligibility definitions.
