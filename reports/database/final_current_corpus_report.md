# Current evidence database report

- Database: `/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db`
- Database SHA-256: `d3174d243fbbc5ac694b452bb29bb722d6a25da273c87c07245b4635bff60632`
- Manifest SHA-256: `2559a0498a238bdc8cce8b0324ae0e350b284579e46679b3d6ea0290a07be459`
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
| source_fact_occurrences | 45835 |
| canonical_facts | 1273 |
| experimental_arms | 55 |
| outcomes | 60 |
| source_evidence_occurrences | 771 |
| evidence_records | 515 |
| nearest_neighbor_ready_arms | 8 |
| comet_ready_arms | 2 |
| almost_comet_ready_arms | 6 |
| unresolved_review_items | 71 |
| unresolved_automatic_items | 71 |
| human_adjudication_items | 0 |

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
- `almost_comet_ready_arms`: Evidence-backed, non-conflict arms failing COMET v3 on only one to three fields.
- `unresolved_review_items`: Visible import-review rows whose status remains incomplete, conflict, quarantined, or blocked.
- `unresolved_automatic_items`: Open relationship or normalization items for automatic repair; these are not a general-use human gate.
- `human_adjudication_items`: Open scientific conflicts that require a human scientific decision.

## Checks

- integrity_check: ok
- foreign_key_violations: 0
- silent_fact_omissions: 0
- silent_evidence_omissions: 0
- manifest_contributor_occurrences: 200
- manifest_available_hashed_artifacts: 198
- manifest_missing_or_unhashed_artifacts: 2
- approved_completed_map_artifacts: 3
- expected_registered_source_artifacts: 201
- registered_source_artifacts: 201
- source_artifact_accounting_matches: True
- forbidden_general_app_human_tags: 0
- new_paid_rerun_calls: 0
- reused_successful_exact_hash_outputs: 3
- source_fact_dispositions: {'quarantined': 15189, 'unresolved': 30646}

## Per-paper counts

| Paper | Formulations | Arms | Outcomes | Evidence | NN-ready | COMET-ready | Review items |
|---|---:|---:|---:|---:|---:|---:|---:|
| GP-001 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-002 | 1 | 7 | 7 | 55 | 1 | 0 | 7 |
| GP-003 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-004 | 1 | 4 | 9 | 44 | 1 | 0 | 5 |
| GP-005 | 5 | 5 | 6 | 38 | 1 | 1 | 7 |
| GP-006 | 1 | 3 | 10 | 22 | 2 | 1 | 1 |
| GP-007 | 1 | 2 | 8 | 30 | 1 | 0 | 5 |
| GP-008 | 4 | 5 | 6 | 45 | 2 | 0 | 4 |
| GP-009 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NP-001 | 1 | 1 | 1 | 11 | 0 | 0 | 5 |
| NP-002 | 2 | 13 | 13 | 110 | 0 | 0 | 13 |
| PILOT-001 | 2 | 5 | 0 | 58 | 0 | 0 | 8 |
| PILOT-002 | 5 | 5 | 0 | 48 | 0 | 0 | 8 |
| PILOT-003 | 1 | 5 | 0 | 54 | 0 | 0 | 8 |

## Verification status

- automatically_validated: 15
- manually_verified: 8
- rejected: 30
- unreviewed: 2

## Rerun history

```json
{
  "completed_existing_paper_ids": [
    "PILOT-001",
    "PILOT-002",
    "PILOT-003"
  ],
  "paper_ids": [],
  "provider_calls": 0,
  "reason": "No extraction_missed or recoverable source_asset_missing gaps remain."
}
```

## Promotion

```json
{
  "backup_path": "/Users/renemilywei/Documents/AI-LNP-database-backups/lnp_evidence-pre-day2-20260807T055159Z.db",
  "backup_sha256": "bfd0d664e592d9e384d91ad0b07026c144ebc2fada4d083699f077949ee4b97b",
  "new_authoritative_sha256": "d3174d243fbbc5ac694b452bb29bb722d6a25da273c87c07245b4635bff60632",
  "old_authoritative_sha256": "a8655d9c7a2a1b1aa235cad0a4b173e836070c055f84e51398869487be5879c3"
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
    "missing_dose": 1,
    "missing_evidence_excerpt": 1,
    "missing_timepoint": 8,
    "outcome_link_unclear": 15,
    "target_cell_automatic_resolution": 17,
    "unsupported_value": 13
  }
}
```
