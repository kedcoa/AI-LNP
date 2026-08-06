# Day 2 PILOT Artifact Recovery

Date: 2026-08-06  
Scope: PILOT-001 through PILOT-003  
Paid/API/LLM calls: **0**

## Result

The expected OA HTML source and source-derived inventory were found for all
three papers in the registered `v5.2-failed-codex-audit` worktree at commit
`003646328852f127ff8f04da7ff3b9b5c0839e34`. Each HTML file exactly matches the
SHA-256 approved in the Day 1 manifest. The inventory files had no expected
hashes in that manifest: their listed SHA-256 values are observations made
during recovery, not immutable verification.

No formally accepted merged extraction artifact exists for these papers. The
recovered inventories identify evidence blocks but do not themselves validate
complete formulation/arm/outcome relationships. Therefore each paper has a
metadata-and-provenance bundle with a visible blocked review record and the
plain-language user tag **Needs human verification**. The 160 inventory-derived
excerpts are retained with `unverified_recovery` confidence and explicit
quarantine notes, but none is promoted into an unsupported formulation, arm, or
outcome. All papers remain ineligible for nearest-neighbor and COMET use.

| Paper | Manifest-verified source SHA-256 | Observed, unverified inventory SHA-256 | Quarantined excerpts | Bundle status | Formulation/arm/outcome rows |
|---|---|---|---:|---|---:|
| PILOT-001 | `74f5c9753888de6396a73609bfa1339e2033e14d6b6453cbabe776d0a0df0b94` | `766a73a0b3a3826e90440d489b577cdac3f29020965bc50548a8d16ec1da1690` | 58 | Blocked review | 0 |
| PILOT-002 | `ca3f29c32d7e84085693e36c0bf409ab09125a2ddbcb5aba2aada052e0866619` | `37f67b111abfb978b9291fc67fad430f613f94995cfaad3f95de77794c270e5d` | 48 | Blocked review | 0 |
| PILOT-003 | `b27ca7553386ece0179125f7234d68434b9ae5bc7311dd016fc4a35b3980cabf` | `a32678f5b3c5cb7cef2bcb35541de70013962e74c8e6c857863cc16bb06f2e77` | 54 | Blocked review | 0 |

## Safety boundaries

- The Codex-authored 62-item benchmark was not read as truth and is not cited as
  provenance.
- Raw provider responses and invocation files were not selected, copied, or
  committed.
- The OA HTML was checked against an approved expected hash. Inventory identity,
  source filename, and JSON structure were checked, but its observed hash has no
  approved expected value and is explicitly marked unverified.
- The OA HTML and source inventories were inspected in place; their source files
  were not copied into this branch.
- The generated recovery manifest records the registered worktree root, its
  checked-out commit, logical artifact paths, observed hashes, and trust state.
- Recovery rejects non-registered roots and normalizes path components before
  rejecting benchmark, answer-key, raw-provider, response, and invocation path
  variants.
- The authoritative SQLite database was not opened or modified.

## Next required action

These papers can enter the database now with their source excerpts and visible
blocked-review paper records. Their scientific experimental arms require a
separately approved validated extraction or human-supported import before
eligibility can be recalculated.
