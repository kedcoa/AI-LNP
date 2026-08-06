# Day 2 NP bundle preparation

Prepared offline on 2026-08-06. No network, API, Codex, or paid LLM calls were
made, and the authoritative SQLite database was not opened or modified.

## NP-001

- Bundle: `data/staging/database/day2_bundles/np/NP-001.json`
- Source result: `data/staging/extraction/np001_primary_paid_v1/NP-001/result.json`
- Imported candidates: 1 formulation, 5 components, 1 experimental arm, 1
  outcome, and 42 entity-and-field-scoped evidence records.
- Review state: the arm is visible but quarantined and is ineligible for nearest
  neighbor and COMET. The bundle contains one quarantined arm review and four
  incomplete reviews. User-facing tags are `Needs human
  verification` and `Unsupported value`.
- Unresolved: the formulation-specific interpretation of the approximately 95%
  result, exact amounts for four lipid components, and the unnamed HepG2 assay
  remain unresolved. DX's reported `25% cholesterol replacement` is preserved
  verbatim in component notes and evidence with a visible review; it is not
  mislabeled as 25 mol% of the whole formulation. No values were imputed.

## NP-002

- Bundle: `data/staging/database/day2_bundles/np/NP-002.json`
- Source results: the hepatocyte, Kupffer-cell, and hepatic-endothelial-cell
  result slices under
  `data/staging/extraction/np002_isolated_liver_cell_run/`.
- Imported candidates: 2 scientifically reconciled formulations, 24 source-slice
  components, 13 experimental arms, 13 outcomes, and 347 entity-and-field-scoped
  evidence records.
- Reconciliation: experiment, outcome, component, and evidence identities are
  namespaced by source slice. Slice-local formulation IDs are reconciled using
  normalized formulation name, supported component identities, reported ratio,
  and N:P ratio. Supported facts and evidence are unioned across the matching
  records, preserving the Kupffer slice's reported 10:1 lipid:nucleic-acid mass
  ratio. The wording variants resolve to the same two scientific
  formulations; truly incompatible variants would remain explicit conflicts.
  In particular, contradictory supported quantitative facts such as 10:1
  versus 20:1 mass ratios are never resolved by description length: they create
  separate evidence-linked variants and a visible conflict review.
  Non-ratio semantics are checked as well (for example, measured versus
  theoretical composition). Ratio identity preserves ratio type, ordered
  values, and multiplicity, so `50:50` molar, `50:50` mass, and a lone `50`
  remain distinct. Compatible descriptions retain their complete evidence union
  under an explicit semantic representation; no scientific value is selected
  by string length. Conflict provenance remains grouped into left and right
  evidence sets, and a missing side is visibly blocked rather than accepted.
  Component `molar_percentage` is populated only for explicit `mol%` or for a
  complete set of molar-ratio parts that deterministically sums to 100. Other
  percentage meanings remain raw evidence/notes with review.
  This avoids both duplicate formulations and invented cross-slice links.
- Review state: all 13 arms are visible but quarantined and ineligible for
  nearest neighbor and COMET. The bundle contains 13 quarantined arm reviews
  and no unsupported automatic eligibility. The user-facing tag is `Needs
  human verification`.
- Unresolved: several arms lack a timepoint or comparator. The source-supported assay,
  endpoint, and qualitative-outcome fields already present in each slice are
  retained.

## Provenance and validation

Every populated normalized field has one or more field-evidence links, and each
link points to evidence carrying the same entity field. Packet evidence is
copied as an excerpt with every available source locator; visual table evidence
used by NP-001 is recovered from the committed supported Docling claims. The
compact packet, Docling claims, validated result artifacts, and available local
full-text copies are independently registered with canonical repository-relative
paths and SHA-256 hashes. NP-002's committed PMC HTML and PDF copies are
registered; the packet's absent `.full` source path remains explicitly marked
unverified rather than borrowing either copy's hash. NP-001 source paths that are
not present in the checkout likewise remain unverified. Bundle
bytes contain no checkout-root paths and are reproducible across worktrees. Both
JSON files load through the validated `ImportBundle` contract.
