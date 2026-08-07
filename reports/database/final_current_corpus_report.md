# Current evidence database report

- Database: `/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db`
- Database SHA-256: `d183c0065126fc2e14e7dcc9a07d9be75b822b0a679bc4aa8e40d44a01064725`
- Manifest SHA-256: `2559a0498a238bdc8cce8b0324ae0e350b284579e46679b3d6ea0290a07be459`
- Schema migrations: `[1, 2, 3, 4, 5, 6, 7, 8]`
- Eligibility rules: `working-evidence-v3`

## Counts

| Metric | Count |
|---|---:|
| papers | 14 |
| named_formulations | 28 |
| unique_chemical_formulations | 17 |
| complete_formulations | 21 |
| incomplete_formulations | 7 |
| components | 115 |
| source_fact_occurrences | 45938 |
| canonical_facts | 1823 |
| experimental_arms | 48 |
| outcomes | 114 |
| source_evidence_occurrences | 812 |
| evidence_records | 518 |
| general_use_ready_arms | 38 |
| nearest_neighbor_ready_arms | 32 |
| comet_ready_arms | 4 |
| almost_comet_ready_arms | 4 |
| unresolved_review_items | 24 |
| unresolved_automatic_items | 24 |
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
- `general_use_ready_arms`: Complete canonical arms with accepted direct evidence or accepted evidence linked through arm or outcome fields.
- `nearest_neighbor_ready_arms`: Arms passing the fixed nearest-neighbor eligibility rules.
- `comet_ready_arms`: Arms passing the stricter COMET eligibility rules.
- `almost_comet_ready_arms`: Evidence-backed, non-conflict arms failing COMET v3 on only one to three fields.
- `unresolved_review_items`: Visible relationship, normalization, or conflict items; ordinary missing fields are reported separately as readiness blockers.
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
- source_fact_dispositions: {'projected': 103, 'quarantined': 15183, 'unresolved': 30652}

## Per-paper counts

| Paper | Formulations | Arms | Outcomes | Evidence | NN-ready | COMET-ready | Review items |
|---|---:|---:|---:|---:|---:|---:|---:|
| GP-001 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-002 | 1 | 6 | 7 | 67 | 1 | 0 | 1 |
| GP-003 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-004 | 1 | 4 | 9 | 55 | 1 | 1 | 1 |
| GP-005 | 9 | 8 | 16 | 42 | 8 | 1 | 3 |
| GP-006 | 1 | 2 | 10 | 23 | 2 | 2 | 0 |
| GP-007 | 1 | 1 | 8 | 30 | 0 | 0 | 4 |
| GP-008 | 4 | 5 | 7 | 54 | 3 | 0 | 1 |
| GP-009 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NP-001 | 1 | 1 | 1 | 11 | 0 | 0 | 4 |
| NP-002 | 2 | 6 | 13 | 76 | 6 | 0 | 0 |
| PILOT-001 | 2 | 5 | 11 | 58 | 5 | 0 | 3 |
| PILOT-002 | 5 | 5 | 18 | 48 | 2 | 0 | 3 |
| PILOT-003 | 1 | 5 | 14 | 54 | 4 | 0 | 4 |

## Verification status

- automatically_validated: 40
- manually_verified: 8

## Rerun history

```json
{
  "note": "No paid rerun was required for this deterministic projection repair.",
  "paper_ids": [],
  "provider_calls": 0
}
```

## Promotion

```json
{
  "backup_path": "/private/tmp/ai-lnp-database-backups/lnp_evidence-pre-day2-20260807T095144Z.db",
  "backup_sha256": "38cb21db9d355ebcd1c91f5d14b44dcd6fc0f925b42fd47d47107a5865557c97",
  "new_authoritative_sha256": "8258842d955d327e7aa8e4e6099046debcf54bf31db425ef9a95d98121c55d34",
  "old_authoritative_sha256": "ea26a4173e58df8fc0602a8ad37bce4cff7ca3133c1cd6bb1706608a736cfe38"
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
    "automatic_resolution_required": 3,
    "experiment_link_unclear": 7,
    "missing_required_fields": 27,
    "outcome_link_unclear": 1,
    "unsupported_value": 13
  }
}
```
