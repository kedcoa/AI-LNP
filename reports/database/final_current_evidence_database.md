# Current evidence database report

- Database: `/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db`
- Database SHA-256: `a8655d9c7a2a1b1aa235cad0a4b173e836070c055f84e51398869487be5879c3`
- Manifest SHA-256: `788a5235818de211cf4c80d52941dc51d053dedd0a07cc1c290dbc2d85cda3c4`
- Schema migrations: `[1, 2, 3, 4, 5, 6]`
- Eligibility rules: `working-evidence-v2`

## Counts

| Metric | Count |
|---|---:|
| papers | 14 |
| named_formulations | 24 |
| unique_chemical_formulations | 17 |
| complete_formulations | 11 |
| incomplete_formulations | 13 |
| components | 74 |
| source_fact_occurrences | 45515 |
| canonical_facts | 1072 |
| experimental_arms | 37 |
| outcomes | 29 |
| source_evidence_occurrences | 626 |
| evidence_records | 403 |
| nearest_neighbor_ready_arms | 8 |
| comet_ready_arms | 4 |
| unresolved_review_items | 53 |

## Definitions

- `papers`: All manifest paper dispositions, including screening-only papers.
- `named_formulations`: Canonical formulation rows with a non-empty reported name.
- `unique_chemical_formulations`: Distinct component-and-amount fingerprints among formulation rows that have component identities.
- `complete_formulations`: Named formulations with all four core LNP roles and a supported amount for each core component or an explicit LNP molar ratio.
- `incomplete_formulations`: Named formulation rows that do not meet the complete-formulation definition.
- `components`: Deduplicated canonical chemical-component rows, including targeting and other formulation constituents.
- `source_fact_occurrences`: Immutable labeled facts retained from every fact-producing source artifact; repeated source occurrences remain separate.
- `canonical_facts`: Distinct normalized entity fields with at least one evidence link.
- `experimental_arms`: Canonical experiment/arm rows after reconciliation and deduplication.
- `outcomes`: Canonical outcome rows linked to experimental arms.
- `source_evidence_occurrences`: Imported evidence source occurrences before canonical evidence deduplication.
- `evidence_records`: Deduplicated canonical evidence records.
- `nearest_neighbor_ready_arms`: Arms passing the fixed nearest-neighbor eligibility rules.
- `comet_ready_arms`: Arms passing the stricter COMET eligibility rules.
- `unresolved_review_items`: Visible import-review rows whose status remains incomplete, conflict, quarantined, or blocked.

## Checks

- integrity_check: ok
- foreign_key_violations: 0
- silent_fact_omissions: 0
- silent_evidence_omissions: 0
- manifest_contributor_occurrences: 199
- manifest_available_hashed_artifacts: 197
- manifest_missing_or_unhashed_artifacts: 2
- approved_completed_map_artifacts: 3
- expected_registered_source_artifacts: 200
- registered_source_artifacts: 200
- source_artifact_accounting_matches: True
- forbidden_general_app_human_tags: 0
- new_paid_rerun_calls: 0
- reused_successful_exact_hash_outputs: 3
- source_fact_dispositions: {'quarantined': 15189, 'unresolved': 30326}

## Per-paper counts

| Paper | Formulations | Arms | Outcomes | Evidence | NN-ready | COMET-ready | Review items |
|---|---:|---:|---:|---:|---:|---:|---:|
| GP-001 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-002 | 1 | 1 | 1 | 18 | 1 | 0 | 1 |
| GP-003 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-004 | 1 | 1 | 2 | 16 | 1 | 1 | 2 |
| GP-005 | 5 | 1 | 2 | 22 | 1 | 1 | 3 |
| GP-006 | 1 | 2 | 5 | 14 | 2 | 2 | 0 |
| GP-007 | 1 | 1 | 1 | 16 | 1 | 0 | 4 |
| GP-008 | 4 | 2 | 4 | 36 | 2 | 0 | 1 |
| GP-009 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NP-001 | 1 | 1 | 1 | 11 | 0 | 0 | 5 |
| NP-002 | 2 | 13 | 13 | 110 | 0 | 0 | 13 |
| PILOT-001 | 2 | 5 | 0 | 58 | 0 | 0 | 8 |
| PILOT-002 | 5 | 5 | 0 | 48 | 0 | 0 | 8 |
| PILOT-003 | 1 | 5 | 0 | 54 | 0 | 0 | 8 |

## Verification status

- automatically_validated: 15
- manually_verified: 8
- rejected: 14

## Rerun history

```json
{
  "approval_hash": "9dbfbcb83e6f8f07c9ce7701eb09adde0db8a352229a77ed1c11358bf75812ea",
  "completed_existing_paper_ids": [
    "PILOT-001",
    "PILOT-002",
    "PILOT-003"
  ],
  "database_path": "/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db",
  "database_sha256": "a8655d9c7a2a1b1aa235cad0a4b173e836070c055f84e51398869487be5879c3",
  "human_approval_required": false,
  "manifest_path": "/Users/renemilywei/Desktop/AI-LNP/.worktrees/day1-current-corpus/data/staging/extraction/application_pilot/map_gate/manifest.json",
  "paper_ids": [],
  "provider_calls": 0,
  "requested_fields": [],
  "requests": [],
  "schema_version": "current-corpus-rerun-preflight/v1",
  "total_estimated_input_tokens": 0,
  "total_max_output_tokens": 0
}
```

## Promotion

```json
{
  "backup_path": "/Users/renemilywei/Documents/AI-LNP-database-backups/lnp_evidence-pre-day2-20260807T035818Z.db",
  "backup_sha256": "931d49674c2c35cc70f7fc99aef4bd97f507884258ade640924ffb3f3d4187c5",
  "new_authoritative_sha256": "a8655d9c7a2a1b1aa235cad0a4b173e836070c055f84e51398869487be5879c3",
  "old_authoritative_sha256": "029dd55f0a33563087cb7cbb48e8ab0eccfa34e9c8c35280192b89d7522c9148",
  "promotion_method": "verified sibling copy plus atomic replace"
}
```

## Unresolved blockers

```json
{
  "missing_or_unhashed_manifest_artifacts": [
    {
      "access_status": "missing",
      "paper_id": "NP-001",
      "path": "data/raw/fulltext/oa_packages/PMC11508592/PMC11508592.nxml"
    },
    {
      "access_status": "missing",
      "paper_id": "NP-001",
      "path": "data/raw/fulltext/oa_packages/PMC11508592/main.pdf"
    }
  ],
  "review_reason_counts": {
    "automatic_resolution_required": 9,
    "experiment_link_unclear": 7,
    "missing_timepoint": 8,
    "outcome_link_unclear": 15,
    "target_cell_automatic_resolution": 1,
    "unsupported_value": 13
  }
}
```
