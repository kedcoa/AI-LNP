# Read-only mentor snapshot design

**Date:** 2026-08-07  
**Status:** Approved design awaiting implementation

## Goal

Create a portable, frozen, read-only Streamlit view of the current authoritative
LNP SQLite database for mentor review. The working Streamlit browser must also
become read-only and must no longer display or accept almost-COMET corrections.

## Headline metrics

The main page will show four clearly separated counts:

1. unique chemical formulations;
2. general-use-ready experimental arms;
3. nearest-neighbor-ready experimental arms;
4. COMET-ready experimental arms.

Readiness applies to experimental arms, not formulations. All three readiness
counts must be calculated through the same canonical arm-row logic used by the
combined table. The unique-formulation count must use the existing normalized
component-and-amount fingerprint definition.

For the database at design time, the expected values are 17 unique chemical
formulations, 38 general-use-ready arms, 32 nearest-neighbor-ready arms, and 4
COMET-ready arms. These values are verification expectations, not hard-coded UI
constants.

## Working Streamlit browser

The existing evidence browser will remain the primary interface at port 8506.
It will:

- display the four headline metrics above the combined experimental-arm table;
- retain its paper selector, filters, combined arm table, paper links, detailed
  formulation views, evidence, and automatic-resolution information;
- remove the entire **Almost COMET-ready corrections** section;
- remove its correction form, save button, and correction-success messages;
- remove correction-only imports and callable paths from the application;
- describe itself consistently as read-only, including the footer.

Removing the visible panel alone is insufficient. The application module must
not expose a user-triggered database write path.

## Frozen mentor package

A dated export directory will contain:

- a byte-for-byte SQLite snapshot copied from the authoritative database after
  integrity and foreign-key checks;
- a read-only Streamlit entry point configured to open only that snapshot;
- a CSV export of the same combined arm rows shown in the interface;
- a JSON summary containing the four headline metrics, database SHA-256, export
  timestamp, and row counts;
- a short README containing prerequisites and one launch command.

The snapshot must not contain `.env`, API keys, provider responses, licensed
PDFs, or dependencies on local absolute source-file links. Publisher, DOI,
PubMed, and PMC links may remain. Local-source links will be omitted or disabled
in the mentor view.

## Read-only enforcement

The mentor application will open SQLite with URI read-only mode. The export
process will never mutate the authoritative database. The snapshot database may
also be made filesystem read-only as defense in depth, but application-level
read-only SQLite access is mandatory and must be tested.

The existing working browser will have no mutation controls after this change.
Internal write services may remain available for other workflows, but the
Streamlit application must not import or call them.

## Report consistency

Generated database reports currently lag behind the corrected browser
readiness calculation. Report generation will be updated to use the canonical
readiness calculation or an equivalent shared helper. Regenerated reports and
the Streamlit metrics must agree for all three readiness profiles.

## Error handling

The mentor application will fail visibly and without fallback if its snapshot
database is missing, corrupt, writable through the application connection, or
incompatible with the expected schema. Export creation will stop before writing
a completion manifest if integrity checks, foreign-key checks, row export, or
metric reconciliation fail.

## Verification

Automated tests will verify:

- the correction section and save controls are absent;
- the working app contains no imported correction submission path;
- headline metrics match canonical combined-arm readiness;
- reports and UI summaries agree;
- the mentor database connection rejects writes;
- the CSV row count equals the combined-table arm count;
- the snapshot database hash and integrity results are recorded;
- local source-file links and secrets are absent from the share package.

The final manual check will launch the working browser and the mentor snapshot,
confirm the four displayed metrics, inspect representative rows, and verify that
no correction controls are visible.

## Out of scope

- Changing scientific evidence or readiness definitions;
- adding new papers;
- running paid extraction calls;
- adding authentication or public hosting;
- removing COMET blocker information from the read-only table.

