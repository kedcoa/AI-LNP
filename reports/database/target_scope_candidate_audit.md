# Day 2 Current Evidence Import

**Temporary fixture audit.** Database: `/Users/renemilywei/Desktop/AI-LNP/.worktrees/day1-current-corpus/data/staging/database/current_corpus_rebuild/lnp_evidence.target-scope-v4.db`

Overall audit: **PASS**. No paid calls were authorized or made.

| Paper | Disposition | Formulations | Arms | Outcomes | Evidence | Missing | Conflicts | Quarantined | Eligible arms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GP-001 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-002 | needs_review | 1 | 6 | 7 | 51 | 15 | 0 | 0 | 1 |
| GP-003 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-004 | needs_review | 1 | 4 | 9 | 44 | 11 | 0 | 0 | 0 |
| GP-005 | needs_review | 5 | 4 | 6 | 38 | 22 | 0 | 0 | 1 |
| GP-006 | needs_review | 1 | 2 | 10 | 22 | 1 | 0 | 0 | 1 |
| GP-007 | needs_review | 1 | 1 | 8 | 30 | 1 | 0 | 0 | 0 |
| GP-008 | needs_review | 4 | 5 | 6 | 45 | 23 | 0 | 0 | 0 |
| GP-009 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NP-001 | needs_review | 1 | 1 | 1 | 11 | 3 | 0 | 1 | 0 |
| NP-002 | needs_review | 2 | 6 | 13 | 72 | 8 | 0 | 0 | 2 |
| PILOT-001 | ready_with_missing_fields | 2 | 5 | 0 | 58 | 15 | 0 | 0 | 0 |
| PILOT-002 | ready_with_missing_fields | 5 | 5 | 0 | 48 | 18 | 0 | 0 | 0 |
| PILOT-003 | ready_with_missing_fields | 1 | 5 | 0 | 54 | 15 | 0 | 0 | 0 |

## Integrity checks

```json
{
  "bundle_hash_mismatches": [],
  "eligibility_inconsistencies": [],
  "evidence_coverage": {
    "arms_without_evidence": [],
    "outcomes_without_evidence": []
  },
  "exact_duplicate_natural_keys": [],
  "foreign_key_violations": [],
  "lossless_source_ledger": {
    "completed_exact_map_artifacts": 3,
    "expected_available_manifest_artifacts": 198,
    "fact_producing_artifacts_without_facts": [],
    "forbidden_general_app_human_tags": 0,
    "gp008_supplement_hash_registered": true,
    "manifest_missing_or_unhashed_artifacts": [
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
    "missing_registered_artifacts": [],
    "nonprojected_facts_without_reason": 0,
    "pilot_promoted_counts": {
      "PILOT-001": {
        "arms": 5,
        "formulations": 2
      },
      "PILOT-002": {
        "arms": 5,
        "formulations": 5
      },
      "PILOT-003": {
        "arms": 5,
        "formulations": 1
      }
    },
    "registered_source_artifacts": 201,
    "screening_only_papers_with_science": [],
    "source_fact_count": 45835,
    "source_fact_disposition_accounting_matches": true,
    "source_fact_dispositions": {
      "quarantined": 15183,
      "unresolved": 30652
    },
    "unexpected_registered_artifacts": []
  },
  "manifest_disposition_mismatches": [],
  "manifest_dispositions": {
    "expected": 14,
    "missing": [],
    "present": 14,
    "unexpected": []
  },
  "manifest_hash_matches": true,
  "normalized_identity_sets": {
    "content_hash_mismatches": [],
    "content_shape_mismatches": [],
    "field_evidence_links": {
      "actual": 1501,
      "expected_canonical": 1501,
      "missing": [],
      "raw_references": 673,
      "unexpected": []
    },
    "generation_errors": [],
    "record_identities": {
      "actual": 1000,
      "expected": 1000,
      "missing": [],
      "unexpected": []
    }
  },
  "orphan_counts": {},
  "post_projection_gaps": {
    "counts_by_kind": {
      "projection_missed": 49,
      "source_not_reported": 91
    },
    "paid_rerun_requests": [],
    "records": [
      {
        "experiment_id": 2,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E02:F1",
        "recoverable": false
      },
      {
        "experiment_id": 2,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E02:F1",
        "recoverable": false
      },
      {
        "experiment_id": 2,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E02:F1",
        "recoverable": false
      },
      {
        "experiment_id": 3,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E03:F1",
        "recoverable": false
      },
      {
        "experiment_id": 3,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E03:F1",
        "recoverable": false
      },
      {
        "experiment_id": 3,
        "field_name": "outcome",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E03:F1",
        "recoverable": false
      },
      {
        "experiment_id": 3,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E03:F1",
        "recoverable": false
      },
      {
        "experiment_id": 3,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E03:F1",
        "recoverable": false
      },
      {
        "experiment_id": 4,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E04:F1",
        "recoverable": false
      },
      {
        "experiment_id": 4,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E04:F1",
        "recoverable": false
      },
      {
        "experiment_id": 4,
        "field_name": "species",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E04:F1",
        "recoverable": false
      },
      {
        "experiment_id": 4,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E04:F1",
        "recoverable": false
      },
      {
        "experiment_id": 5,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E05:F1",
        "recoverable": false
      },
      {
        "experiment_id": 6,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E06:F1",
        "recoverable": false
      },
      {
        "experiment_id": 6,
        "field_name": "outcome",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-002:ARM:GP-002-E06:F1",
        "recoverable": false
      },
      {
        "experiment_id": 7,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E01:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 7,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E01:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 8,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E02:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 8,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E02:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 8,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E02:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 9,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E03:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 9,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E03:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 9,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E03:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 9,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E03:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 9,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:ARM:GP-004-E03:ENT-FORM-01",
        "recoverable": false
      },
      {
        "experiment_id": 10,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-004",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-004:GOLD:GX-001",
        "recoverable": false
      },
      {
        "experiment_id": 12,
        "field_name": "chemical_formulation_total",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP17",
        "recoverable": false
      },
      {
        "experiment_id": 12,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP17",
        "recoverable": false
      },
      {
        "experiment_id": 12,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP17",
        "recoverable": false
      },
      {
        "experiment_id": 12,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP17",
        "recoverable": false
      },
      {
        "experiment_id": 12,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP17",
        "recoverable": false
      },
      {
        "experiment_id": 12,
        "field_name": "species",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP17",
        "recoverable": false
      },
      {
        "experiment_id": 12,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP17",
        "recoverable": false
      },
      {
        "experiment_id": 13,
        "field_name": "chemical_formulation_total",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP16",
        "recoverable": false
      },
      {
        "experiment_id": 13,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP16",
        "recoverable": false
      },
      {
        "experiment_id": 13,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP16",
        "recoverable": false
      },
      {
        "experiment_id": 13,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP16",
        "recoverable": false
      },
      {
        "experiment_id": 13,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP16",
        "recoverable": false
      },
      {
        "experiment_id": 13,
        "field_name": "species",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP16",
        "recoverable": false
      },
      {
        "experiment_id": 13,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E01:ENT-LNP16",
        "recoverable": false
      },
      {
        "experiment_id": 14,
        "field_name": "chemical_formulation_total",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E02:ENT-LNP3-7",
        "recoverable": false
      },
      {
        "experiment_id": 14,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E02:ENT-LNP3-7",
        "recoverable": false
      },
      {
        "experiment_id": 14,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E02:ENT-LNP3-7",
        "recoverable": false
      },
      {
        "experiment_id": 14,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E02:ENT-LNP3-7",
        "recoverable": false
      },
      {
        "experiment_id": 14,
        "field_name": "outcome",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E02:ENT-LNP3-7",
        "recoverable": false
      },
      {
        "experiment_id": 14,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E02:ENT-LNP3-7",
        "recoverable": false
      },
      {
        "experiment_id": 14,
        "field_name": "species",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E02:ENT-LNP3-7",
        "recoverable": false
      },
      {
        "experiment_id": 14,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-005",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-005:ARM:GP-005-E02:ENT-LNP3-7",
        "recoverable": false
      },
      {
        "experiment_id": 15,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-006",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-006:ARM:GP-006-E01:E_FORM_01",
        "recoverable": false
      },
      {
        "experiment_id": 17,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-007",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-007:ARM:GP-007-E04:ENT-F01",
        "recoverable": false
      },
      {
        "experiment_id": 18,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F1",
        "recoverable": false
      },
      {
        "experiment_id": 18,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F1",
        "recoverable": false
      },
      {
        "experiment_id": 18,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F1",
        "recoverable": false
      },
      {
        "experiment_id": 18,
        "field_name": "species",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F1",
        "recoverable": false
      },
      {
        "experiment_id": 18,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F1",
        "recoverable": false
      },
      {
        "experiment_id": 19,
        "field_name": "chemical_formulation_total",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F4",
        "recoverable": false
      },
      {
        "experiment_id": 19,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F4",
        "recoverable": false
      },
      {
        "experiment_id": 19,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F4",
        "recoverable": false
      },
      {
        "experiment_id": 19,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F4",
        "recoverable": false
      },
      {
        "experiment_id": 19,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "GP-008",
        "reason": "source graph contains the field, but canonical arm projection did not attach it",
        "record_id": "GP-008:ARM:GP-008-E01:F4",
        "recoverable": false
      },
      {
        "experiment_id": 19,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F4",
        "recoverable": false
      },
      {
        "experiment_id": 19,
        "field_name": "species",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F4",
        "recoverable": false
      },
      {
        "experiment_id": 19,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F4",
        "recoverable": false
      },
      {
        "experiment_id": 20,
        "field_name": "chemical_formulation_total",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F5",
        "recoverable": false
      },
      {
        "experiment_id": 20,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F5",
        "recoverable": false
      },
      {
        "experiment_id": 20,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F5",
        "recoverable": false
      },
      {
        "experiment_id": 20,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F5",
        "recoverable": false
      },
      {
        "experiment_id": 20,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F5",
        "recoverable": false
      },
      {
        "experiment_id": 20,
        "field_name": "species",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F5",
        "recoverable": false
      },
      {
        "experiment_id": 20,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:ARM:GP-008-E01:F5",
        "recoverable": false
      },
      {
        "experiment_id": 21,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:GOLD:GX-008",
        "recoverable": false
      },
      {
        "experiment_id": 21,
        "field_name": "dose",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:GOLD:GX-008",
        "recoverable": false
      },
      {
        "experiment_id": 22,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "GP-008",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "GP-008:GOLD:GX-009",
        "recoverable": false
      },
      {
        "experiment_id": 23,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-001",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-001::arm::EX1",
        "recoverable": false
      },
      {
        "experiment_id": 23,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-001",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-001::arm::EX1",
        "recoverable": false
      },
      {
        "experiment_id": 23,
        "field_name": "route",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-001",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-001::arm::EX1",
        "recoverable": false
      },
      {
        "experiment_id": 26,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::03-hepatic-endothelial-cells::EXP-CRE-1.0-MC3",
        "recoverable": false
      },
      {
        "experiment_id": 26,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::03-hepatic-endothelial-cells::EXP-CRE-1.0-MC3",
        "recoverable": false
      },
      {
        "experiment_id": 26,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::01-hepatocytes::X3",
        "recoverable": false
      },
      {
        "experiment_id": 26,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::01-hepatocytes::X3",
        "recoverable": false
      },
      {
        "experiment_id": 26,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::02-kupffer-cells::EXP-Cre-MC3-1.0",
        "recoverable": false
      },
      {
        "experiment_id": 26,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::02-kupffer-cells::EXP-Cre-MC3-1.0",
        "recoverable": false
      },
      {
        "experiment_id": 27,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::03-hepatic-endothelial-cells::EXP-CRE-1.0-cKK-E12",
        "recoverable": false
      },
      {
        "experiment_id": 27,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::03-hepatic-endothelial-cells::EXP-CRE-1.0-cKK-E12",
        "recoverable": false
      },
      {
        "experiment_id": 27,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::01-hepatocytes::X4",
        "recoverable": false
      },
      {
        "experiment_id": 27,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::01-hepatocytes::X4",
        "recoverable": false
      },
      {
        "experiment_id": 27,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::02-kupffer-cells::EXP-Cre-cKK-E12-1.0",
        "recoverable": false
      },
      {
        "experiment_id": 27,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::02-kupffer-cells::EXP-Cre-cKK-E12-1.0",
        "recoverable": false
      },
      {
        "experiment_id": 28,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::01-hepatocytes::X5",
        "recoverable": false
      },
      {
        "experiment_id": 28,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::01-hepatocytes::X5",
        "recoverable": false
      },
      {
        "experiment_id": 29,
        "field_name": "delivery_destination",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::01-hepatocytes::X6",
        "recoverable": false
      },
      {
        "experiment_id": 29,
        "field_name": "timepoint",
        "gap_kind": "source_not_reported",
        "paper_id": "NP-002",
        "reason": "available arm-scoped source claims do not report this field",
        "record_id": "NP-002::arm::01-hepatocytes::X6",
        "recoverable": false
      },
      {
        "experiment_id": 37,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-1",
        "recoverable": false
      },
      {
        "experiment_id": 37,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-1",
        "recoverable": false
      },
      {
        "experiment_id": 37,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-1",
        "recoverable": false
      },
      {
        "experiment_id": 38,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-2",
        "recoverable": false
      },
      {
        "experiment_id": 38,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-2",
        "recoverable": false
      },
      {
        "experiment_id": 38,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-2",
        "recoverable": false
      },
      {
        "experiment_id": 39,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-3",
        "recoverable": false
      },
      {
        "experiment_id": 39,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-3",
        "recoverable": false
      },
      {
        "experiment_id": 39,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-3",
        "recoverable": false
      },
      {
        "experiment_id": 40,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-4",
        "recoverable": false
      },
      {
        "experiment_id": 40,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-4",
        "recoverable": false
      },
      {
        "experiment_id": 40,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-4",
        "recoverable": false
      },
      {
        "experiment_id": 41,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-5",
        "recoverable": false
      },
      {
        "experiment_id": 41,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-5",
        "recoverable": false
      },
      {
        "experiment_id": 41,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-001",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-001::map-arm::PEC-5",
        "recoverable": false
      },
      {
        "experiment_id": 42,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::HELA_MFLUC",
        "recoverable": false
      },
      {
        "experiment_id": 42,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::HELA_MFLUC",
        "recoverable": false
      },
      {
        "experiment_id": 42,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::HELA_MFLUC",
        "recoverable": false
      },
      {
        "experiment_id": 43,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::C57BL6_MFLUC",
        "recoverable": false
      },
      {
        "experiment_id": 43,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::C57BL6_MFLUC",
        "recoverable": false
      },
      {
        "experiment_id": 43,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::C57BL6_MFLUC",
        "recoverable": false
      },
      {
        "experiment_id": 44,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::LSL_MCRE",
        "recoverable": false
      },
      {
        "experiment_id": 44,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::LSL_MCRE",
        "recoverable": false
      },
      {
        "experiment_id": 44,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::LSL_MCRE",
        "recoverable": false
      },
      {
        "experiment_id": 44,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::LSL_MCRE",
        "recoverable": false
      },
      {
        "experiment_id": 45,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::MANNOSE_MCRE_LSEC",
        "recoverable": false
      },
      {
        "experiment_id": 45,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::MANNOSE_MCRE_LSEC",
        "recoverable": false
      },
      {
        "experiment_id": 45,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::MANNOSE_MCRE_LSEC",
        "recoverable": false
      },
      {
        "experiment_id": 45,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::MANNOSE_MCRE_LSEC",
        "recoverable": false
      },
      {
        "experiment_id": 46,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::C57BL6_SIFVIII_MANNOSE",
        "recoverable": false
      },
      {
        "experiment_id": 46,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::C57BL6_SIFVIII_MANNOSE",
        "recoverable": false
      },
      {
        "experiment_id": 46,
        "field_name": "lnp_molar_ratio",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::C57BL6_SIFVIII_MANNOSE",
        "recoverable": false
      },
      {
        "experiment_id": 46,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-002",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-002::map-arm::CTX::C57BL6_SIFVIII_MANNOSE",
        "recoverable": false
      },
      {
        "experiment_id": 47,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-1",
        "recoverable": false
      },
      {
        "experiment_id": 47,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-1",
        "recoverable": false
      },
      {
        "experiment_id": 47,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-1",
        "recoverable": false
      },
      {
        "experiment_id": 48,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-2",
        "recoverable": false
      },
      {
        "experiment_id": 48,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-2",
        "recoverable": false
      },
      {
        "experiment_id": 48,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-2",
        "recoverable": false
      },
      {
        "experiment_id": 49,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-3",
        "recoverable": false
      },
      {
        "experiment_id": 49,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-3",
        "recoverable": false
      },
      {
        "experiment_id": 49,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-3",
        "recoverable": false
      },
      {
        "experiment_id": 50,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-4",
        "recoverable": false
      },
      {
        "experiment_id": 50,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-4",
        "recoverable": false
      },
      {
        "experiment_id": 50,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-4",
        "recoverable": false
      },
      {
        "experiment_id": 51,
        "field_name": "delivery_destination",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-5",
        "recoverable": false
      },
      {
        "experiment_id": 51,
        "field_name": "evidence",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-5",
        "recoverable": false
      },
      {
        "experiment_id": 51,
        "field_name": "outcome",
        "gap_kind": "projection_missed",
        "paper_id": "PILOT-003",
        "reason": "extracted records exist but their arm relationship is unresolved",
        "record_id": "PILOT-003::map-arm::CTX-5",
        "recoverable": false
      }
    ]
  },
  "review_tag_gaps": [],
  "sqlite_integrity": "ok"
}
```
