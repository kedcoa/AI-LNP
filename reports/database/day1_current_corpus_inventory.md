# Day 1 current-corpus inventory

Canonical local-only routing inventory for Day 2 supported-evidence import.
No evidence was imported and no scientific extraction was performed.

## Verified counts

- Total papers: **14**
- Import candidates: **11**
- Screening-only records: **3**
- Selected supported artifacts: **7**
- Included records with an explicit unresolved reason: **4**
- Paid/API/LLM calls recorded: **0**

## Day 2 routing

| Paper | Import status | Rerun status | Selected artifact or explicit reason |
| --- | --- | --- | --- |
| GP-001 | screening_only | none | Screening-ledger-only record; no import artifact permitted. |
| GP-002 | needs_review | selective | data/staging/extraction/g1_fulltext_rag/GP-002/accepted_graph.json |
| GP-003 | screening_only | none | Screening-ledger-only record; no import artifact permitted. |
| GP-004 | needs_review | selective | data/staging/extraction/g1_fulltext_rag/GP-004/accepted_graph.json |
| GP-005 | needs_review | selective | data/staging/extraction/g1_fulltext_rag/GP-005/accepted_graph.json |
| GP-006 | needs_review | selective | data/staging/extraction/g1_fulltext_rag/GP-006/accepted_graph.json |
| GP-007 | needs_review | none | data/staging/extraction/g1_fulltext_rag/GP-007/accepted_graph.json |
| GP-008 | needs_review | selective | data/staging/extraction/g1_fulltext_rag/GP-008/accepted_graph.json |
| GP-009 | screening_only | none | Screening-ledger-only record; no import artifact permitted. |
| NP-001 | needs_review | selective | data/staging/extraction/np001_primary_paid_v1/NP-001/result.json |
| NP-002 | needs_review | selective | High priority: deterministically reconcile the three validated, recipient-cell-scoped results into one source-evidence-preserving artifact, then repair only the missing assay, endpoint, qualitative-outcome, and comparator fields. No new extraction request is authorized by this inventory. |
| PILOT-001 | blocked | blocked_pending_access | The committed worktree lacks the local source HTML and inventory.json named by the pilot selection manifest; the only committed consolidated replay failed formal acceptance and is not importable. |
| PILOT-002 | blocked | blocked_pending_access | The committed worktree lacks the local source HTML and inventory.json named by the pilot selection manifest; the only committed consolidated replay failed formal acceptance and is not importable. |
| PILOT-003 | blocked | blocked_pending_access | The committed worktree lacks the local source HTML and inventory.json named by the pilot selection manifest; the only committed consolidated replay failed formal acceptance and is not importable. |

## Boundary

This inventory selects or defers local artifacts only. Field- and arm-level validation, evidence import, and any authorized selective repair remain Day 2-3 work.
