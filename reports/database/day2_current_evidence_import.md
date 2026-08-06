# Day 2 Current Evidence Import

**Authoritative database audit.** Database: `/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db`

Overall audit: **PASS**. No paid calls were authorized or made.

| Paper | Disposition | Formulations | Arms | Outcomes | Evidence | Missing | Conflicts | Quarantined | Eligible arms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GP-001 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-002 | needs_review | 1 | 6 | 6 | 62 | 2 | 0 | 6 | 0 |
| GP-003 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GP-004 | needs_review | 1 | 3 | 7 | 49 | 0 | 0 | 2 | 0 |
| GP-005 | needs_review | 5 | 4 | 4 | 40 | 3 | 0 | 4 | 0 |
| GP-006 | needs_review | 1 | 1 | 5 | 17 | 0 | 0 | 1 | 0 |
| GP-007 | needs_review | 1 | 1 | 7 | 30 | 0 | 0 | 1 | 0 |
| GP-008 | needs_review | 4 | 3 | 2 | 30 | 1 | 0 | 2 | 0 |
| GP-009 | screening_only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NP-001 | needs_review | 1 | 1 | 1 | 42 | 0 | 0 | 1 | 0 |
| NP-002 | needs_review | 2 | 13 | 13 | 347 | 0 | 0 | 13 | 0 |
| PILOT-001 | needs_review | 0 | 0 | 0 | 58 | 0 | 0 | 0 | 0 |
| PILOT-002 | needs_review | 0 | 0 | 0 | 48 | 0 | 0 | 0 | 0 |
| PILOT-003 | needs_review | 0 | 0 | 0 | 54 | 0 | 0 | 0 | 0 |

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
      "actual": 672,
      "expected_canonical": 672,
      "missing": [],
      "raw_references": 673,
      "unexpected": []
    },
    "generation_errors": [],
    "record_identities": {
      "actual": 929,
      "expected": 929,
      "missing": [],
      "unexpected": []
    }
  },
  "orphan_counts": {},
  "review_tag_gaps": [],
  "sqlite_integrity": "ok"
}
```
