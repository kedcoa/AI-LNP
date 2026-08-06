# Streamlit Human-Review Demo Design

**Status:** Approved visual design awaiting implementation plan

## Goal

Build an interactive, mock-data-only Streamlit prototype that lets the user evaluate the intended evidence-review workflow before the application is connected to the authoritative SQLite database.

The demo must never read from or write to `data/curated/lnp_evidence.db`. A persistent banner will identify all displayed papers, arms, evidence, and review decisions as fictional demonstration data.

## Default Experience

The landing page is a review queue, not a paper browser. It prioritizes experimental arms that need human attention and lets the reviewer filter by paper, review reason, target cell, payload, species, and eligibility proximity.

Selecting a queue item opens a single-page review workspace:

1. a compact paper header;
2. mock DOI, PubMed, publisher, PDF, HTML, and institutional-access controls;
3. an editable experimental-arm table;
4. field-level status and evidence;
5. review-decision controls; and
6. simulated nearest-neighbor and COMET eligibility.

## Interface Structure

### Header and progress summary

The top of the page shows fictional review metrics:

- arms awaiting review;
- arms missing one or two fields;
- arms with conflicts;
- arms simulated as nearest-neighbor eligible; and
- arms simulated as COMET eligible.

### Review queue

The left panel lists mock arms grouped by paper. Each item includes a concise reason such as `Target cell needs confirmation`, `Dose missing`, or `Outcome link unclear`.

Queue filters update the visible list without changing any real application state.

### Paper access panel

The selected mock paper shows title, DOI, PMID/PMCID, and buttons representing:

- DOI/publisher page;
- PubMed or PMC;
- PDF;
- HTML full text; and
- institutional library access.

For this demo, links use harmless example destinations or are visibly marked as mock. No licensed paper is embedded.

### Experimental-arm editor

One row represents the selected mock arm. Editable fields include:

- formulation name and composition ratio;
- target cell and delivery cell;
- species and biological model;
- delivery setting and route;
- payload;
- dose and unit;
- assay and timepoint; and
- outcome value, unit, and normalization.

Field states use accessible text and color together:

- verified;
- needs confirmation;
- missing;
- conflict; and
- not reported.

Missing values appear as `Not extracted` rather than silently becoming scientific `NA` values.

### Evidence inspector

Selecting a field displays one or more fictional evidence excerpts with:

- excerpt text;
- section, page, table, or figure location;
- source modality;
- extraction confidence; and
- a clear statement that evidence is mock data.

The interface demonstrates that an excerpt may support multiple fields and that a field may have multiple excerpts.

### Review controls

The reviewer can interactively:

- accept the extracted value;
- edit and accept a corrected value;
- mark the value as genuinely not reported;
- mark the evidence as belonging to another arm;
- leave the field unresolved; or
- reset the demo state.

Decisions live only in Streamlit session state. Refreshing or resetting discards them.

### Eligibility simulation

The demo recalculates illustrative eligibility after each mock decision. It lists remaining reasons separately for nearest-neighbor and COMET.

The simulation is a user-interface demonstration, not the production eligibility engine, and will be labeled accordingly.

## Visual Direction

Use a restrained scientific-review aesthetic: neutral background, compact cards, readable tables, and clear status chips. Avoid decorative visuals that compete with evidence review. The workspace should remain usable on a laptop without horizontal page scrolling.

## Isolation and Safety

- No SQLite connection.
- No API, Codex, LLM, or network call.
- No real paper text or licensed PDF.
- No real review decision is persisted.
- Mock data is defined in a dedicated demo module and labeled in the interface.

## Verification

Automated tests will verify that:

- the demo imports without opening SQLite;
- mock records contain all intended field states;
- review decisions update only session-state-compatible data;
- eligibility simulation responds to accepted, corrected, missing, and unresolved states; and
- no real database path or extraction artifact is referenced.

A local Streamlit smoke test and browser inspection will verify the layout, controls, and visible demo-only warning.

## Out of Scope

- Real database reads or writes;
- real DOI/library authentication;
- embedded licensed PDFs;
- production review-history persistence;
- production eligibility recalculation; and
- bulk review or export.
