# Day 1 NP lane inventory

Checked locally on 2026-08-06. This lane makes no provider, API, or extraction
calls. It inventories only derived local artifacts; no raw responses or licensed
full text are added to version control.

## NP-001 — import only after review

- Bibliography: *Encapsulation of Dexamethasone into mRNA-Lipid Nanoparticles
  Is a Promising Approach for the Development of Liver-Targeted
  Anti-Inflammatory Therapies*; DOI `10.3390/ijms252011254`; PMCID
  `PMC11508592`; PMID remains unresolved in the local artifacts.
- Local evidence lineage: the compact packet at
  `data/staging/rag/compact_packets_v1/NP-001.json` identifies the OA source
  paths `data/raw/fulltext/oa_packages/PMC11508592/PMC11508592.nxml` and
  `data/raw/fulltext/oa_packages/PMC11508592/main.pdf`. The compact API packet
  is `data/staging/rag/compact_api_packets_v1/NP-001.json`.
- Candidate history: `np001_primary_paid_v1` is the primary compact-1.1.0
  result. Its manifest records a matching paper ID, evidence IDs found in the
  packet, a valid validation report, and one formulation, five components, one
  experiment, one outcome, and three explicit unresolved items. The later
  `np001_primary_accounting_trial_run` and `np001_core_slot_trial_retry_run`
  are rejected as import sources: the latter's scientific validation reports
  `evidence_outside_slot` errors, and neither supersedes the validated primary
  result.
- Selected artifact:
  `data/staging/extraction/np001_primary_paid_v1/NP-001/result.json` (SHA-256
  `6ad0acdc54379dca715b9514d1acf3a54ad3f890d5121ce0d83cb4f85a7c56f4`). It
  is the strongest current structured, evidence-linked result. It is not marked
  ready because its own completion manifest says
  `completed_pending_outcome_coverage_review`; v12 structural coverage routed
  28 facts to human review and eight to bounded repair.
- Routing: `needs_review`, then a selective source-bounded repair only if
  needed for (1) formulation-specific transfection percentage, (2) explicit
  component amounts for LNP(DSPC)/DX25, and (3) the HepG2 quantification assay.
  The inventory does not perform that repair.

## NP-002 — high-priority selective reconciliation

- Bibliography: *Cell Subtypes Within the Liver Microenvironment Differentially
  Interact with Lipid Nanoparticles*; DOI `10.1007/s12195-019-00573-4`; PMID
  `31719922`; PMCID `PMC6816632`. The local source copies are
  `data/staging/new_papers/NP-002/PMC6816632.html` and
  `data/staging/new_papers/NP-002/PMC6816632.pdf`; the compact packet is
  `data/staging/rag/compact_packets_v1/NP-002.json`.
- Pipeline lineage: the original full-paper map is
  `data/staging/extraction/full_paper_np002_paper_map_run/NP-002/paper_map.json`.
  The selective-vision route issued source-derived Figure 2 (six) and Figure 4
  (twelve) slots, then the experiment-ID design bound all 18 slots to six
  immutable, source-supported arms. The local merge report records zero
  wrong-arm links and 153/245 matched benchmark facts after authenticated
  zero-call replay, but only 0% complete-arm recall because assay, endpoint,
  qualitative-outcome, and comparator fields remained unmatched.
- Current supported candidates: each of
  `data/staging/extraction/np002_isolated_liver_cell_run/01-hepatocytes/result.json`,
  `data/staging/extraction/np002_isolated_liver_cell_run/02-kupffer-cells/result.json`,
  and
  `data/staging/extraction/np002_isolated_liver_cell_run/03-hepatic-endothelial-cells/result.json`
  has a valid local validation artifact and scoped, linked outcomes. The
  `np002_kupffer_arm_benchmark_run_v2_retry` result also has zero scientific
  validation errors, but is only a Kupffer-cell slice and remains
  `completed_pending_human_review`.
- No import artifact is selected. The merge report names a stronger,
  unified artifact at
  `data/staging/extraction/np002_experiment_id_merged/NP-002/merged_extraction.json`,
  but that path is absent from the current worktree. The existing validated
  results are overlapping recipient-cell slices, not one non-conflicting
  full-paper import source; automatically choosing one would silently discard
  supported records.
- Routing: `needs_review` with high-priority `selective` rerun. First make a
  deterministic, evidence-preserving reconciliation of the three validated
  slices and check arm identity/conflicts. Then repair only the missing assay,
  endpoint, qualitative outcome, and comparator fields. Do not re-run the
  full-paper map or issue any extraction request solely from this inventory.

## Lane result

Both papers are included import candidates but neither is ready for automatic
Day 2 import. NP-001 has one selected, validated primary artifact awaiting
field review. NP-002 has no safe single import artifact in this worktree and
remains the high-priority selective-reconciliation item. `np_v1.json` was
validated with `load_lane()` and `validate_corpus()` against the repository
root.
