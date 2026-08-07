# Day 2 Current Evidence Import

**Authoritative database audit.** Database: `/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db`

Overall audit: **PASS**. No paid calls were authorized or made.

| Paper | Disposition | Formulations | Arms | Outcomes | Evidence | Missing | Conflicts | Quarantined | Eligible arms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GP-001 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-002 | needs_review | 1 | 1 | 1 | 18 | 0 | 0 | 0 | 1 |
| GP-003 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-004 | needs_review | 1 | 1 | 2 | 16 | 0 | 0 | 0 | 1 |
| GP-005 | needs_review | 5 | 1 | 2 | 22 | 0 | 0 | 0 | 1 |
| GP-006 | needs_review | 1 | 2 | 5 | 14 | 0 | 0 | 0 | 2 |
| GP-007 | needs_review | 1 | 1 | 1 | 16 | 0 | 0 | 0 | 1 |
| GP-008 | needs_review | 4 | 2 | 4 | 36 | 0 | 0 | 0 | 2 |
| GP-009 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NP-001 | needs_review | 1 | 1 | 1 | 11 | 0 | 0 | 1 | 0 |
| NP-002 | needs_review | 2 | 13 | 13 | 110 | 0 | 0 | 13 | 0 |
| PILOT-001 | ready_with_missing_fields | 2 | 5 | 0 | 58 | 10 | 0 | 0 | 0 |
| PILOT-002 | ready_with_missing_fields | 5 | 5 | 0 | 48 | 10 | 0 | 0 | 0 |
| PILOT-003 | ready_with_missing_fields | 1 | 5 | 0 | 54 | 10 | 0 | 0 | 0 |

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
    "expected_available_manifest_artifacts": 197,
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
    "registered_source_artifacts": 200,
    "screening_only_papers_with_science": [],
    "source_fact_count": 45515,
    "source_fact_disposition_accounting_matches": true,
    "source_fact_dispositions": {
      "quarantined": 15189,
      "unresolved": 30326
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
      "actual": 1260,
      "expected_canonical": 1260,
      "missing": [],
      "raw_references": 673,
      "unexpected": []
    },
    "generation_errors": [],
    "record_identities": {
      "actual": 806,
      "expected": 806,
      "missing": [],
      "unexpected": []
    }
  },
  "orphan_counts": {},
  "review_tag_gaps": [],
  "sqlite_integrity": "ok"
}
```
