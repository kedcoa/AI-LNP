# Day 1 GP-lane inventory

**Checked:** 2026-08-06 (local artifacts only). **Paid/API/LLM calls:** 0.

## Result

The lane contains nine distinct IDs: six supported-evidence import candidates
(all `needs_review`) and three required screening-only records (GP-001,
GP-003, and GP-009). The selected import artifacts are committed accepted
full-text graphs, not raw provider responses. Their final-audit files contain
zero deterministic findings; that does not resolve the separate compact
coverage gaps listed below.

| Paper | Ledger disposition and identifiers | Selected artifact / rationale | Day 2-3 route |
| --- | --- | --- | --- |
| GP-001 | exclude; PMID 42249613, PMCID PMC13244520, DOI 10.1080/10717544.2026.2682976 | None: screening ledger identifies an unsupported non-RNA payload. | Screening-only; never import or rerun. |
| GP-002 | include; PMID 42440881, PMCID PMC13334401, DOI 10.1016/j.omtn.2026.102989 | `data/staging/extraction/g1_fulltext_rag/GP-002/accepted_graph.json`; full-text, evidence-linked accepted graph (6 experiments, 42 claims; zero audit findings). | Import supported graph; selectively handle 2 `first_call_required` gaps. |
| GP-003 | exclude; PMID 42164756, PMCID PMC13184955, DOI 10.34133/research.1288 | None: screening ledger identifies a review article. | Screening-only; never import or rerun. |
| GP-004 | include; PMID 33504774, PMCID PMC7840919, DOI 10.1038/s41467-021-20903-3 | `data/staging/extraction/g1_fulltext_rag/GP-004/accepted_graph.json`; accepted full-text-with-supplement graph (4 experiments, 42 claims; zero audit findings). | Import supported graph only; selectively address 6 missing-record-text gaps and incomplete formulation context. |
| GP-005 | include; PMID 39792811, PMCID PMC11884593, DOI 10.1002/advs.202409729 | `data/staging/extraction/g1_fulltext_rag/GP-005/accepted_graph.json`; accepted full-text graph (3 experiments, 28 claims; zero audit findings). | Import supported graph only; selectively review the one vision gap and endpoint adjudication. |
| GP-006 | include; PMID 39640016, PMCID PMC11617921, DOI 10.1016/j.omtn.2024.102383 | `data/staging/extraction/g1_fulltext_rag/GP-006/accepted_graph.json`; accepted full-text graph (1 experiment, 11 claims; zero audit findings). | Import supported graph only; selectively address 6 vision and 14 missing-record-text gaps, including supplemental evidence. |
| GP-007 | include; PMID 42088421, PMCID PMC13137855, DOI 10.7150/ijbs.126332 | `data/staging/extraction/g1_fulltext_rag/GP-007/accepted_graph.json`; accepted full-text-with-supplement graph (4 experiments, 26 claims; zero audit findings). | Import supported graph; retain 41 human-review coverage items without a Day 1 rerun. |
| GP-008 | manual_review; PMID 42213756, PMCID PMC13229182, DOI 10.1073/pnas.2534673123 | `data/staging/extraction/g1_fulltext_rag/GP-008/accepted_graph.json`; accepted full-text-with-supplement graph (1 umbrella experiment, 24 claims; zero audit findings). | Import only supported graph after review; selectively handle 7 vision and 3 missing-record-text gaps. |
| GP-009 | exclude; PMID 40087866, PMCID PMC12265960, DOI 10.1016/j.ymthe.2025.03.018 | None: screening ledger documents that “HSC” refers to hematopoietic stem cells, outside scope. | Screening-only; never import or rerun. |

## Local provenance and caveats

- Bibliographic IDs and ledger dispositions come from
  `data/manifests/gold_source_manifest_v1.json`. The lane now records PMCIDs,
  explicit-null publication metadata, checked source access, candidate and
  pipeline lineage, field-level metadata provenance, and the artifact-selection
  rationale. Titles remain explicit `null` because no title-bearing local
  metadata was promoted into the contract.
- Candidate inventories are in
  `data/staging/extraction/v12_atomic_inventory/GP-00{1..9}/manifest.json`.
  All report `paid_api_requests: 0`.
- Accepted-graph audit evidence is in
  `data/staging/extraction/g1_fulltext_rag/GP-00{2,4,5,6,7,8}/final_audit.json`.
  Compact-routing scope and blockers are in
  `reports/extraction/enforced_compact_workflow_v1/GP-00{2,4,5,6,7,8}/routing.json`.
- No raw response, licensed source, extraction rerun, provider invocation, or
  scientific re-adjudication was created in this lane. `needs_review` means
  the selected graph is the controlled supported import candidate, not that
  every graph claim is approved for downstream use.
