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

## Final verification (2026-08-06)

- The canonical manifest contains **14** paper dispositions: **11** import candidates, **3** screening-only records, **7** selected supported artifacts, and **4** included records with explicit unresolved reasons. It records **0** paid/API/LLM calls.
- Recomputed SHA-256 digests for all **7/7** selected artifact paths matched the canonical manifest; no selected path was missing.
- A temporary legacy six-table SQLite database preserved its seeded `paper` and `experiment` rows through migration. The first and second post-migration schema-and-data dumps were identical (`fb3678bcd8d62baae7f2cd8e05fc44c5208eb8a97ae65e7df2ef5634274fc219`); migration versions 1 and 2 were the only recorded versions, foreign keys were enabled, and `PRAGMA foreign_key_check` returned no rows.
- With `OPENAI_API_KEY` and `SENSENOVA_API_KEY` blank and the RAG site-packages on `PYTHONPATH`, the complete offline suite reported **889 passed, 7 skipped** (5 warnings).
- The worktree has no curated database file (only the tracked placeholder). The repository working database at `data/curated/lnp_evidence.db` remained byte-identical before and after the suite: `87a77275f8c524e70747bff92f247cf78d9907b5a6059d0fcadb38dfb1eca675`.
- The Git index was empty, so no raw provider response, licensed source, credential, or other sensitive file was staged.

### Outstanding handoff

Day 2 imports only the seven selected artifacts and preserves the four explicit unresolved routes (NP-002 plus PILOT-001 through PILOT-003). Day 3 performs field/arm validation, the scoped selective repairs, and the blocked-source follow-up.

Whole-branch review is tracked separately from this local verification record.
