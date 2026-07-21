# SenseTime LNP

An AI-assisted, literature-grounded tool for finding and comparing lipid
nanoparticle (LNP) starting formulations for four liver cell types:

- Hepatocytes
- Kupffer cells
- Liver sinusoidal endothelial cells (LSECs)
- Hepatic stellate cells (HSCs)

The initial payload categories are mRNA, siRNA, saRNA, and circRNA.

## Project track

This project follows **Track A**.

The five-week deliverable is a literature-grounded evidence and
experimental-design application. It does not assume that a paired four-cell
training dataset, new wet-lab data, or local GPU access is available.

Optional neocloud/COMET work may be attempted at the end of the project, but
it is not required for completing the Track A application.

## Intended Week 5 deliverable

A public, read-only Streamlit application that:

- retrieves traceable literature evidence;
- filters evidence by biological and experimental context;
- distinguishes comparable from non-comparable outcomes;
- retrieves similar reported formulations;
- displays out-of-distribution warnings;
- produces constrained DOE experimental suggestions; and
- preserves citations and evidence for every material result.

## Claims not made by the MVP

The Week 5 application will not claim:

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

5. **Future model prediction**  
   Disabled for the Track A MVP. It may be enabled only after suitable labeled
   data and validation become available.

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