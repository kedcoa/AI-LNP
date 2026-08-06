# Day 2 NP bundle preparation

Prepared offline on 2026-08-06. No network, API, Codex, or paid LLM calls were
made, and the authoritative SQLite database was not opened or modified.

## NP-001

- Bundle: `data/staging/database/day2_bundles/np/NP-001.json`
- Source result: `data/staging/extraction/np001_primary_paid_v1/NP-001/result.json`
- Imported candidates: 1 formulation, 5 components, 1 experimental arm, 1
  outcome, and 19 entity-scoped evidence records.
- Review state: the arm is visible but quarantined and is ineligible for nearest
  neighbor and COMET. The bundle contains one quarantined arm review and three
  incomplete paper-level reviews. User-facing tags are `Needs human
  verification` and `Unsupported value`.
- Unresolved: the formulation-specific interpretation of the approximately 95%
  result, exact amounts for four lipid components, and the unnamed HepG2 assay
  remain unresolved. No values were imputed.

## NP-002

- Bundle: `data/staging/database/day2_bundles/np/NP-002.json`
- Source results: the hepatocyte, Kupffer-cell, and hepatic-endothelial-cell
  result slices under
  `data/staging/extraction/np002_isolated_liver_cell_run/`.
- Imported candidates: 6 retained formulation variants, 24 source-slice
  components, 13 experimental arms, 13 outcomes, and 169 entity-scoped
  evidence records.
- Reconciliation: experiment, outcome, component, and evidence identities are
  namespaced by source slice. Identical formulation records are unioned, while
  incompatible formulation descriptions remain separate conflict variants.
  This avoids overwriting supported differences or inventing cross-slice links.
- Review state: all 13 arms are visible but quarantined and ineligible for
  nearest neighbor and COMET. The bundle contains 13 quarantined arm reviews
  and 8 explicit formulation-conflict reviews. User-facing tags are `Needs
  human verification` and `Conflicting formulation`.
- Unresolved: the differing formulation descriptions need human reconciliation;
  several arms also lack a timepoint or comparator. The source-supported assay,
  endpoint, and qualitative-outcome fields already present in each slice are
  retained.

## Provenance and validation

Every populated normalized field has one or more field-evidence links. Packet
evidence is copied as an excerpt with its section/page locator when available;
visual table evidence used by NP-001 is recovered from the committed supported
Docling claims. Each evidence record is scoped to its entity and source slice,
and every source result has a recorded SHA-256. Both JSON files load through the
validated `ImportBundle` contract.
