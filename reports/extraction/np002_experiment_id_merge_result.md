# NP-002 Experiment-ID Merge Result

## Decision

The experiment-ID merge change is structurally successful but did not meet the
agreed extraction-recall gate. NP-002 repair work stops here for today. The
next product work should move to multi-paper extraction, database population,
and a minimal UI rather than adding another NP-002-specific layer.

No new paid API calls were made. The two previously validated Figure 2 and
Figure 4 responses were authenticated and replayed locally.

## What changed

- Built six source-supported experiment identities: two QUANT DNA arms and
  four Cre mRNA arms split by formulation and dose.
- Bound all 18 visual candidates to one immutable experiment ID before the
  response contract.
- Required future visual responses to echo that experiment ID unchanged.
- Added exact candidate/experiment-pair validation.
- Removed `VIS::<slot>` experiment identities.
- Removed Figure 2/Figure 4 conditional scientific context from the merger.
- Joined paper-level arm metadata and visual outcomes deterministically by ID.
- Added an authenticated zero-cost replay path for the two existing responses.

## Score

| Metric | Before | After |
|---|---:|---:|
| Overall micro recall | 42.9% | **62.4%** |
| Experiment-fact recall | 45.7% | **68.6%** |
| Complete-arm recall | 0% | **0%** |
| Precision | 42.7% | **61.7%** |
| Wrong-arm links | 42 | **0** |
| Matched gold facts | 105/245 | **153/245** |

The join recovered 48 additional benchmark facts and eliminated wrong-arm
links. This confirms that immutable experiment IDs solve the record-linkage
failure.

## Why complete-arm recall remains zero

The strict evaluator marks an arm complete only when every required fact for
that arm matches. All 18 arms now have their basic identity and context joined,
but the following expected outcome fields remain unmatched:

| Missing field | Arms affected |
|---|---:|
| Assay | 18 |
| Endpoint | 18 |
| Qualitative outcome | 18 |
| Comparator | 12 |

The vision responses often contain scientifically useful but differently
scoped descriptions. For example, a response can report a significant
MC3-versus-cKK-E12 comparison while the benchmark expects the more basic
statement that DNA accumulation was detected. The Figure 2 task also labels
the assay as cellular DNA accumulation while the benchmark expects ddPCR.

These are outcome-contract and evaluator-normalization differences, not
remaining experiment-ID merge failures. Fixing them would require another
extraction-contract or semantic-normalization cycle, which is outside the one
bounded merge fix approved for today.

## Acceptance-gate result

- Six experiment arms present: **pass**
- Eighteen candidates linked: **pass**
- Unknown or swapped experiment IDs: **zero, pass**
- Wrong-arm links: **zero, pass**
- Existing responses replayed without a paid call: **pass**
- NP-002 figure-specific merge context removed: **pass**
- Complete-arm recall at least 80%: **fail (0%)**

The overall feature therefore does not pass the full acceptance gate, even
though the joining mechanism itself is validated.

## Product decision and next work

Do not add another NP-002 repair layer today. Continue with a pipeline that
stores evidence-backed partial records and makes their completeness visible.

The next implementation sequence should be:

1. Select a bounded set of liver-focused papers from the existing source pool.
2. Run ingestion and the current extraction routes without gold-set tuning.
3. Convert accepted complete and partial records into one stable database
   schema with provenance, completeness status, and quarantine status.
4. Load the extracted records into the database.
5. Build a minimal UI that can filter formulations, components, payloads,
   models, target cells, and qualitative outcomes.
6. Use the accumulated real-paper failures to decide whether one reusable
   outcome normalizer is justified; do not design it from NP-002 alone.

This allows database, UI, nearest-neighbor, and later COMET work to proceed
without treating perfect recall on one paper as a prerequisite.

## Artifacts

- New preflight: `data/staging/extraction/np002_experiment_id_preflight/NP-002/`
- Zero-call replay: `data/staging/extraction/np002_experiment_id_replay/NP-002/`
- Merged extraction: `data/staging/extraction/np002_experiment_id_merged/NP-002/merged_extraction.json`
- Score: `reports/extraction/np002_selective_vision_score.json`
