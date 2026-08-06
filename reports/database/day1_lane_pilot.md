# Day 1 PILOT metadata lane

**Checked:** 2026-08-06

**Scope:** PILOT-001 through PILOT-003 only. No extraction, provider, or paid calls were made.

## Inventory and routing

| Paper | Reconciled bibliography | Local-source finding | Strongest supported import artifact | Day 2 routing |
| --- | --- | --- | --- | --- |
| PILOT-001 | Han et al. (2023), *Ligand-tethered lipid nanoparticles for targeted RNA delivery to treat liver fibrosis*; DOI `10.1038/s41467-022-35637-z`; PMID `36650129`; PMCID `PMC9845313` | `data/benchmarks/application_pilot/pilot_manifest.json` names `data/staging/new_papers/PILOT-001/PMC9845313.html` and `data/staging/extraction/application_pilot/PILOT-001/inventory.json`; neither exists in this committed worktree. | None. `reports/extraction/application_pilot_final.json` is a provider-free replay with `formal_acceptance.passed: false`, so it is rejected. | Blocked pending restoration of the source HTML and inventory; then re-inventory before any import. |
| PILOT-002 | Kim et al. (2021), *Engineered ionizable lipid nanoparticles for targeted delivery of RNA therapeutics into different types of cells in the liver*; DOI `10.1126/sciadv.abf4398`; PMID `33637537`; PMCID `PMC7909888` | The selection manifest names `data/staging/new_papers/PILOT-002/PMC7909888.html` and `data/staging/extraction/application_pilot/PILOT-002/inventory.json`; neither exists in this committed worktree. | None. The same consolidated replay is rejected for failed formal acceptance. | Blocked pending restoration of the source HTML and inventory; then re-inventory before any import. |
| PILOT-003 | Woitok et al. (2020), *Lipid-encapsulated siRNA for hepatocyte-directed treatment of advanced liver disease*; DOI `10.1038/s41419-020-2571-4`; PMID `32393755`; PMCID `PMC7214425` | The selection manifest names `data/staging/new_papers/PILOT-003/PMC7214425.html` and `data/staging/extraction/application_pilot/PILOT-003/inventory.json`; neither exists in this committed worktree. | None. The same consolidated replay is rejected for failed formal acceptance. | Blocked pending restoration of the source HTML and inventory; then re-inventory before any import. |

## Bibliographic reconciliation

The local pilot-selection manifest already supplied the titles, DOIs, PMCIDs, and years. PMIDs were absent locally and were resolved through free PubMed bibliographic records:

- PILOT-001: [PubMed 36650129](https://pubmed.ncbi.nlm.nih.gov/36650129/)
- PILOT-002: [PubMed 33637537](https://pubmed.ncbi.nlm.nih.gov/33637537/)
- PILOT-003: [PubMed 32393755](https://pubmed.ncbi.nlm.nih.gov/32393755/)

`pmcid` and publication metadata are documented here because the committed `CorpusEntry` contract stores only `title`, `doi`, and `pmid` bibliographic fields. The lane manifest passes those contract-supported identifiers through without inventing additional fields.

## Reference and artifact policy

The 62-item `data/benchmarks/application_pilot/` reference is explicitly benchmark-only under its blinding policy. It is a Codex-authored/internal debugging reference, not human gold, is not a recall denominator, and is not an import candidate. It is cited only as local bibliographic and expected-source provenance.

`reports/extraction/application_pilot_final.json` is also not selected: it identifies itself as `completed_provider_free_replay`, exposes reference/audit containers, and records `formal_acceptance.passed: false`. Selecting it would violate the deterministic strongest-artifact rule to reject unsuccessful or unsupported outputs.

## Manifest validation

`load_lane()` validates the three unique paper IDs and permitted routing values. `validate_corpus()` validates the lane against the repository root; each entry deliberately has no selected import artifact, so no unavailable or reference artifact is admitted. All three papers are included candidates whose current import state is `blocked`, not screening-only.

## Remaining issue

The published source and application-pilot inventory files were present in an earlier local workflow (their paths and hashes remain in the map-gate manifest) but are not committed in this worktree. Restore or otherwise make those source-derived, non-raw artifacts available before the lane can select an import artifact. This task did not retrieve source text, rerun extraction, or commit raw/provider/licensed material.
