# Read-Only Evidence Browser Design

**Status:** Approved design awaiting implementation-plan approval

## Goal

Create a simple Streamlit interface for browsing the authoritative LNP evidence
database by paper. The interface shows every formulation as one row, exposes the
supporting evidence beneath that row, and displays missing information as `NA`.
It is a database viewer, not a human-verification workflow.

## Application Boundary

The browser is a new application, separate from `src/ui/review_app.py` and the
fictional review demo. It opens the canonical SQLite database in read-only mode
and provides no edit, approval, rejection, correction, or persistence controls.
COMET's stricter manual-verification metadata may be displayed as internal
eligibility information, but the general interface must never require or label
an item as needing human verification.

Database access lives in a dedicated service module. The Streamlit module calls
only that service boundary and contains no SQL.

## Page Structure

### Paper navigation

The sidebar contains a paper selector and text search. All current-corpus papers
are visible, including screening-only papers. A screening-only paper displays a
clear empty-state message instead of fabricated scientific rows.

### Paper header and access links

The selected paper displays its corpus ID, title, citation identifiers, full-text
status, and available links. Link controls may include DOI/publisher, PubMed,
PMC, source record, and a local source artifact when the artifact exists. Missing
links are omitted rather than replaced with fictional destinations.

### Paper summary

Compact metrics show the selected paper's counts for formulations, components,
experimental arms, outcomes, evidence records, and unresolved automatic-resolution
items.

### Formulation table

The main table has one row per canonical formulation and preserves this exact
column order:

1. `lnp_name`
2. `chemical_formulation_total`
3. `lnp_molar_ratio`
4. `ionizable_lipid`
5. `helper_lipid`
6. `cholesterol`
7. `peg_lipid`
8. `others`

Blank values display as `NA`. The table does not duplicate a formulation merely
because it has multiple experimental arms.

## Expandable Formulation Details

Each formulation has one expandable section beneath the main table.

### Field evidence

A field-evidence table shows:

- field name;
- displayed value or `NA`;
- supporting evidence excerpt or `NA`;
- section, page, table, figure, or source location;
- evidence modality and automatic validation status.

Multiple evidence excerpts remain separate. Evidence is matched through the
database's canonical field-evidence links; the browser does not infer new links.

### Experimental arms

Every arm linked to the formulation is shown as its own row. Arm columns include
target cell, tissue or organ, species, biological model, setting, route, payload,
dose, assay, timepoint, completeness status, nearest-neighbor readiness, and
COMET readiness. Missing values display as `NA`.

Selecting or expanding an arm reveals its field-level evidence, linked outcomes,
outcome evidence, and automatic-resolution blockers. Multiple doses, models,
timepoints, or outcomes are never concatenated into a single formulation value.

### Automatic-resolution issues

Unresolved records display their specific reason, such as `missing_timepoint`,
`outcome_link_unclear`, or `experiment_link_unclear`. The interface calls these
automatic-resolution issues, not human-review requirements.

## Data Rules

- Query only the canonical authoritative database.
- Open SQLite with `mode=ro` and enable query-only behavior.
- Preserve paper, formulation, arm, outcome, evidence, and provenance links.
- Use `NA` only for a missing displayed value; never convert `NA` into a scientific
  database value.
- Do not fabricate evidence when a field lacks a canonical evidence link.
- Do not present source-fact occurrences as canonical usable facts.
- Keep nearest-neighbor and COMET readiness separate.

## Error Handling

If the authoritative database is unavailable, invalid, or missing required
tables, the page displays a concise error and stops. Missing local source files
disable only the relevant link. A formulation or arm without evidence remains
visible with explicit `NA` evidence rather than disappearing.

## Visual Direction

Reuse the existing evidence-import/review styling: neutral background, compact
metrics, white bordered cards, a restrained green-gray palette, and laptop-safe
widths. Evidence excerpts use readable wrapped text. The browser prioritizes
clarity over decorative graphics.

## Verification

Automated tests verify that:

- the service opens the authoritative database read-only;
- papers and access links load correctly;
- the formulation table has exactly the approved eight columns and one row per
  formulation;
- missing cells render as `NA`;
- formulation, arm, outcome, and field evidence remain correctly linked;
- multiple arms do not duplicate formulation rows;
- screening-only papers render an empty state;
- no write, review-decision, or human-verification control appears;
- Streamlit renders successfully against a representative database fixture.

A local Streamlit smoke test will confirm the page loads and the authoritative
database remains byte-for-byte unchanged.

## Out of Scope

- Editing or approving database values;
- manual-review queues;
- COMET adjudication;
- source-document downloading;
- new extraction or screening;
- provider or network calls;
- changing eligibility rules; and
- altering the authoritative database.
