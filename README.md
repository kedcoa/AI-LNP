# SenseTime LNP

An AI-assisted, literature-grounded tool for finding and comparing lipid
nanoparticle (LNP) starting formulations for four liver cell types:

- Hepatocytes
- Kupffer cells
- Liver sinusoidal endothelial cells (LSECs)
- Hepatic stellate cells (HSCs)

The initial payload categories are mRNA, siRNA, saRNA, and circRNA.

## Project track

This project follows the new **eight-week Track B plan**. It combines an
evidence-first four-cell literature application with a conditional,
hepatocyte-first COMET adaptation and prospective validation workflow.

COMET training is gated rather than assumed. The literature evidence and
similarity modes remain complete products if the curated hepatocyte dataset is
too small, too heterogeneous, or fails grouped evaluation. Kupffer-cell, LSEC,
and HSC predictions remain disabled until each cell passes the same readiness
and model-value gates.

Full plan: `LNP_Liver_Tool_8_Week_Timeline_v4_COMET_Hepatocyte_First.md`

## Intended eight-week deliverable

A public, read-only Streamlit application that:

- retrieves traceable literature evidence;
- filters evidence by biological and experimental context;
- distinguishes comparable from non-comparable outcomes;
- retrieves similar reported formulations;
- displays out-of-distribution warnings;
- optionally produces constrained DOE experimental suggestions;
- exposes a separately gated COMET research mode when validation passes; and
- preserves citations and evidence for every material result.

The interface is designed explicitly during **Day 21**, implemented and wired
to provenance-safe application services during **Day 24**, and usability- and
mode-tested during **Day 25**.

## Claims not made by the application

The application will not claim:

- prospective biological validation;
- reliable prediction for an unseen cell type;
- a universally best LNP formulation;
- a validated four-cell predictive model;
- completed wet-lab validation; or
- proof of in-vivo liver-cell targeting.

## Output hierarchy

The application separates five output categories:

1. **Direct literature evidence**  
   Formulations, experiments, or outcomes explicitly reported in a cited
   source.

2. **Normalized or derived data**  
   Values mechanically transformed from reported information using documented
   and reversible code.

3. **Similarity analogy**  
   Existing formulations retrieved because their encoded composition is
   similar to the query. Similarity is not presented as an efficacy prediction.

4. **DOE experimental suggestion**  
   Untested candidates selected to improve experimental-space coverage while
   satisfying programmed constraints. These require expert review.

5. **COMET model prediction**
   A separately labelled `y_hat` available only in research mode after the
   selected cell/task passes readiness, baseline, grouped-holdout, stability,
   and out-of-domain gates. It never replaces reported evidence.

## Eight-week roadmap

- **Week 1:** discovery, screening rules, and a field-level gold answer set.
- **Week 2:** full-text/table/figure extraction and scientific normalization.
- **Week 3:** per-cell readiness audits and conditional literature expansion.
- **Week 4:** COMET reproduction, baselines, grouped splits, and adaptation.
- **Week 5:** UI/UX design, candidate scoring, integration, and product tests.
- **Week 6:** prospective experiment design, feasibility review, and preregistration.
- **Week 7:** formulation, physical QC, and the frozen hepatocyte experiment.
- **Week 8:** prospective analysis, honest application updates, and next-version planning.

## Data identity boundary

The application maintains a strict distinction between:

- `X`: a formulation or candidate input;
- `y_hat`: an optional model prediction; and
- `y`: a reported or experimentally measured outcome.

DOE generates `X`, not `y`.

A model generates `y_hat`, not `y`.

Only reported literature measurements or quality-controlled wet-lab
measurements may be treated as `y`.

## Literature discovery

The project uses a versioned search manifest covering hepatocytes, Kupffer
cells, liver sinusoidal endothelial cells, and hepatic stellate cells.

PubMed and Europe PMC are the discovery sources. Every cell type receives the
same retrieval cap. Exact query text, request parameters, timestamps,
pagination state, raw responses, and checksums are preserved for each run.

PMC and other open-full-text services are used later for targeted full-text
retrieval. They are not counted as additional discovery sources.

Current search manifest: `docs/search/query_manifest_v1.yaml`

## LLM provider

The project currently uses SenseNova through its OpenAI-compatible API
endpoint.

The LLM may assist with screening and structured extraction, but extracted
values must pass schema validation and evidence review before entering the
curated database.

## Data workflow

Literature information moves through the following stages:

```text
search
  -> screen
  -> retrieve
  -> extract
  -> validate
  -> review
  -> curate
```

## Full-text RAG pipeline

The G1 extraction workflow now uses a modular, provenance-preserving full-text
retrieval-augmented generation pipeline. Retrieval and extraction are evaluated
separately: finding the correct evidence does not by itself mean that an LLM
extracted the correct structured value.

```text
PMC XML / supplement PDF
  -> GROBID adapter or PyMuPDF ingestion
  -> provenance-bearing document blocks
  -> SQLite FTS5/BM25 lexical retrieval
  -> sentence-transformer + FAISS/Chroma semantic retrieval
  -> custom LNP entity candidates (optional SciSpaCy enrichment)
  -> field-specific evidence packets
  -> retrieval and contradiction gates
  -> experiment-scoped LLM evidence graph
  -> independent second-read verification
  -> Pydantic and deterministic graph validation
  -> human scientific review
```

### Pipeline stages

1. **Ingestion** reads structured PMC XML first and supplemental PDFs with
   PyMuPDF. Every block retains its paper, source file, section, page, XML
   element, and parser provenance. GROBID is an optional fallback when usable
   structured XML is unavailable.
2. **Lexical retrieval** stores blocks in SQLite and uses FTS5/BM25 to find
   exact terminology, chemical names, ratios, doses, and cell markers.
3. **Semantic retrieval** uses a local sentence-transformer with FAISS. A
   Chroma adapter is also available. Biomedical synonym expansion and
   conservative adjacent-paragraph retrieval reduce vocabulary and context
   misses.
4. **Entity candidates** detect LNPs, lipid components, RNA payloads, cells,
   species, routes, genes, proteins, and outcomes. The deterministic detector
   always runs; SciSpaCy enrichment is optional because the current SciSpaCy
   release does not build under Python 3.14.
5. **Evidence packets** retrieve composition, payload, experiment-boundary,
   delivery-recipient-cell, therapeutic-target-cell, model-context, and outcome
   evidence separately. Results are hard-filtered by paper to prevent
   cross-paper leakage.
6. **Evidence gates** require sufficient source blocks and relevant entity
   types. Missing evidence causes abstention. Mixed positive and negative
   evidence is retained and flagged instead of being simplified into a false
   answer.
7. **Experiment-scoped extraction** uses the existing evidence-graph schema:
   atomic entities, typed relations, explicit experiment IDs, and exact source
   quotes. Delivery recipients and therapeutic targets remain separate, and
   each cell and endpoint receives its own relation.
8. **Second read and validation** asks an independent model pass to reread the
   source and apply corrections. Pydantic and deterministic audits reject
   invalid links, merged cells, payload-as-component errors, non-verbatim
   evidence, context leakage, and unsupported relations.
9. **Review and curation** expose evidence and saved scientific decisions.
   Human verification remains mandatory before G1 approval.

### Current benchmark

On the 31 human-verified evidence locations across the nine open-access gold
papers, the current hybrid retriever finds the correct source within its top
eight blocks for **28/31 checks (90.3% recall@8)**. This is retrieval recall,
not extraction precision and not a G1 pass. The three remaining retrieval
misses are GP-008 macrophage-delivery, HSC therapeutic-effect, and
recipient-cell-specificity evidence.

Readable benchmark outputs:

- `reports/rag/gold_v1_retrieval_table.md`
- `reports/rag/gold_v1_retrieval_table.csv`
- `reports/rag/gold_v1_retrieval_sentence-transformers.json`

### Local setup and commands

RAG dependencies are isolated from the original environment:

```bash
python3 -m venv .venv-rag
.venv-rag/bin/pip install -r requirements-rag.txt
```

Build the corpus and retrieval packets:

```bash
.venv-rag/bin/python -m src.rag.ingestion
.venv-rag/bin/python -m src.rag.run_pipeline
```

Run the fixed retrieval benchmark and build the plain results table:

```bash
.venv-rag/bin/python -m src.rag.benchmark --backend sentence-transformers -k 8
.venv-rag/bin/python -m src.rag.build_retrieval_table
```

Start the optional evidence review interface:

```bash
.venv/bin/streamlit run src/rag/review_app.py
```

Run one experiment-scoped extraction only after retrieval gates pass and a
provider has sufficient quota:

```bash
.venv/bin/python -m src.rag.run_experiment_extraction --paper-id GP-002
```

The API key and provider URL belong in `.env`, which is ignored by Git.

## G1 architecture history

The initial schema-first abstract extraction trial validated JSON structure but
could not establish scientific correctness or preserve full experiment context;
after repeated omissions and cross-experiment field leakage, the workflow moved
to full-text hybrid RAG so each typed claim is grounded in retrieved,
provenance-bearing evidence before validation and human review.
