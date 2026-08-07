# AI-LNP

AI-LNP is a literature-grounded pipeline for finding, extracting, validating,
and comparing lipid nanoparticle (LNP) evidence involving hepatocytes, Kupffer
cells, liver sinusoidal endothelial cells (LSECs), and hepatic stellate cells
(HSCs).

## Live read-only database

**[Open the AI-LNP mentor evidence browser](https://ai-lnp-mentor-snapshot.streamlit.app/)**

The public app is hosted by Streamlit Community Cloud. It does not depend on a
local computer remaining powered on. The app may take a moment to wake after a
period without visitors, but closing the development laptop does not shut it
down.

The deployed app is a frozen, read-only snapshot. It contains no correction,
review-submission, or database-writing controls.

## v5.2 status

The v5.2 database passed SQLite integrity and foreign-key checks. These counts
describe different scientific objects and must not be combined:

| Measure | v5.2 result |
|---|---:|
| Manifest papers | 14 |
| Named formulation rows | 28 |
| Unique chemical formulations | 17 |
| Complete formulations | 21 |
| Incomplete formulations | 7 |
| Chemical components | 115 |
| Canonical source facts | 1,823 |
| Source-fact occurrences retained in the lossless ledger | 45,938 |
| Experimental arms | 48 |
| Outcomes | 114 |
| Evidence records | 518 |
| General-use-ready arms | 38 |
| Nearest-neighbor-ready arms | 32 |
| COMET-ready arms | 4 |
| Unresolved automatic review items | 24 |
| Human scientific-conflict items | 0 |

“Manifest papers” includes screening-only paper dispositions. A formulation
row is a reported formulation identity; a unique chemical formulation is a
deduplicated component-and-amount fingerprint. Facts, evidence records,
experimental arms, and outcomes are separate database objects.

The frozen public snapshot has SHA-256:

`d183c0065126fc2e14e7dcc9a07d9be75b822b0a679bc4aa8e40d44a01064725`

## What changed in v5.2

The current workflow is designed to prevent information from disappearing
between source JSON and SQLite:

```text
paper discovery and screening
  -> full text, supplement, and source-asset retrieval
  -> schema-specific JSON adapters
  -> immutable source-fact ledger
  -> evidence and provenance links
  -> deterministic arm and outcome projection
  -> shared paper/experiment context propagation
  -> scientific deduplication
  -> wide LNP formulation projection
  -> readiness calculation
  -> SQLite audits and read-only Streamlit browser
```

Important v5.2 behavior:

- Every contributing artifact is registered with its paper, schema family,
  hash, role, and provenance.
- Accepted graph JSON, NP result JSON, and pilot paper-map JSON use explicit
  adapters instead of one lossy generic importer.
- Source facts are retained before projection, including facts that cannot yet
  become an arm or outcome field.
- Evidence reported in a contributing JSON artifact is audited against the
  SQLite source-fact and evidence tables.
- Shared experimental context can be propagated across arms when the paper
  reports setup information once for a group of experiments.
- Experimental arms are deduplicated by scientific identity rather than raw
  JSON node identity.
- Multiple outcomes remain separate in SQLite and are displayed together in
  one arm row in the main browser.
- Missing values remain `NA`; the pipeline does not invent unsupported values.

No validation, audit, or screening command silently initiates a paid provider
call. Paid calls require exact request-hash approval.

## LNP formulation projection

The wide formulation view uses the approved order:

```text
lnp_name
chemical_formulation_total
lnp_molar_ratio
ionizable_lipid
helper_lipid
cholesterol
peg_lipid
others
```

One formulation stays on one wide row. Individual components and their
evidence remain normalized internally so the database can preserve provenance,
deduplicate chemistry, and rebuild the wide view deterministically.

## Readiness definitions

General-use readiness requires the following supported fields:

- chemical formulation (total);
- LNP molar ratio;
- target cell or recipient organ;
- species;
- payload;
- dose;
- route;
- outcome;
- timepoint.

Individual component slots, biological model, encoded product, and molecular
target are useful but are not general-use blockers when the required
formulation and experiment evidence is already present.

Nearest-neighbor and COMET readiness use separate versioned rules. COMET is
intentionally stricter and may require evidence review; that review requirement
does not block the general application.

## Repository layout

| Path | Purpose |
|---|---|
| `src/rag/` | Full-text/XML/PDF ingestion, retrieval, compact evidence packets, and provenance. |
| `src/extraction/` | Structured contracts, validation, repair routing, provider-call gates, and deterministic merging. |
| `src/database/` | Lossless adapters, source-fact import, schema migrations, deduplication, readiness, audits, and reports. |
| `src/screening/` and `src/search/` | Literature discovery, metadata normalization, deduplication, and screening. |
| `src/ui/` | Read-only evidence browser, review services, and snapshot export. |
| `config/database/` | Current-corpus manifests, readiness profiles, and source-backed repair rules. |
| `data/manifests/` | Paper and contributing-artifact manifests. |
| `reports/database/` | Integrity audits and honest final database reports. |
| `exports/mentor_snapshot_2026-08-07/` | Portable read-only Streamlit app, SQLite snapshot, and CSV export. |
| `tests/` | Regression tests for successful, incomplete, and abstention paths. |

## Run the portable Streamlit snapshot

The portable snapshot is the easiest option after cloning the repository. It
already contains its own SQLite database.

```bash
python3 -m venv .venv
.venv/bin/pip install -r exports/mentor_snapshot_2026-08-07/requirements.txt
.venv/bin/streamlit run exports/mentor_snapshot_2026-08-07/app.py
```

Streamlit will print a local URL, normally
[http://localhost:8501](http://localhost:8501).

## Run the development evidence browser

Install the full project dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The development browser reads `data/curated/lnp_evidence.db`. That working
database is intentionally ignored by Git. To initialize it from the committed
v5.2 snapshot:

```bash
mkdir -p data/curated
cp exports/mentor_snapshot_2026-08-07/lnp_evidence.db data/curated/lnp_evidence.db
.venv/bin/streamlit run src/ui/evidence_browser_app.py --server.port 8506
```

Then open [http://localhost:8506](http://localhost:8506).

## Run tests

```bash
.venv/bin/python -m pytest -q
```

The database-specific regression suite checks:

- source-fact and evidence import coverage;
- JSON adapter behavior for each schema family;
- experimental-arm and outcome projection;
- shared-context propagation;
- scientific deduplication;
- readiness calculations;
- SQLite integrity and foreign keys;
- read-only Streamlit behavior.

## New-paper screening handoff

The screening pipeline deduplicates candidates against the existing SQLite
database, records inclusion/exclusion reasons, selects a balanced full-text
queue by liver-cell type, retrieves primary and supplementary assets, and
prepares compact extraction requests.

The first batch metadata and extraction preflight artifacts are under:

`data/staging/new_papers/2026-08-07/`

Screening and extraction remain separate stages. A paper is not imported merely
because it mentions an LNP: it must produce at least one evidence-backed
formulation/experimental-arm candidate, or remain explicitly queued for
automatic repair or review.

## Data and security boundaries

- API keys belong only in `.env`; `.env` is ignored by Git.
- Raw provider responses are not committed.
- Downloaded or licensed PDFs and supplements are not committed.
- Public snapshot links omit local source-file paths.
- Reported evidence, normalized/derived data, similarity results,
  experimental suggestions, and model predictions remain separate categories.
- Similarity does not turn an inferred formulation into reported evidence.

## Reference reports

- `reports/database/final_current_evidence_database.md`
- `reports/database/final_current_evidence_database.json`
- `reports/database/final_current_evidence_audit.md`
- `reports/database/target_scope_candidate_audit.md`
- `docs/database/shared-context-projection-invariants.md`
