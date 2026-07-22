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
