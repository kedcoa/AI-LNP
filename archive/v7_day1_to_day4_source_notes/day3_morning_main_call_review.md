# Week 1 Day 3 morning - compact main-call review

Status: **paused for human verification on 2026-07-27**

## Execution summary

Eight additional standard Responses API requests were attempted with
`gpt-5.6-terra`; they were not submitted through the Batch API. The earlier
GP-002 pilot remains a frozen compact-1.0.0 result. The additional requests
used compact-1.1.0 with explicit eligibility. After human approval, the three
validator-rejected papers were submitted as replacement main calls with the
corrected validator and response-preservation path.

| Paper | Local result | Eligibility | Formulations | Experiments | Outcomes | Reported tokens |
|---|---|---|---:|---:|---:|---:|
| GP-001 | valid replacement | ineligible | 0 | 0 | 0 | 20,182 |
| GP-003 | valid | ineligible | 0 | 0 | 0 | 19,547 |
| GP-004 | valid | eligible | 1 | 3 | 4 | 24,315 |
| GP-005 | valid | eligible | 3 | 3 | 3 | 25,227 |
| GP-006 | valid | eligible | 2 | 2 | 3 | 24,512 |
| GP-007 | valid replacement | eligible | 1 | 1 | 3 | 23,240 |
| GP-008 | valid | eligible | 2 | 1 | 2 | 24,637 |
| GP-009 | valid replacement | ineligible | 0 | 0 | 0 | 20,895 |

The eight saved compact-1.1.0 calls used 161,515 input tokens, 21,040 output
tokens, and 182,555 total tokens. The three original rejected attempts also
completed model generation and may be billable, but the prior SDK parsing path
discarded their usage objects, so their exact cost must be read from the
OpenAI usage dashboard.

## Validator finding

The eligibility validator incorrectly required reason codes to contain only
the category matching the final decision. The model reasonably returned both
passed criteria and the failed or incomplete criterion. This rejected GP-001,
GP-007, and GP-009 after generation. The validator now requires the decisive
reason while allowing other documented criteria, and regression tests cover
mixed passed/failed codes.

The runner now saves `response.json` and `candidate.json` before semantic
validation. Future validator failures therefore remain available for narrow
repair without repeating a full extraction call. The three earlier rejected
responses cannot be recovered locally because `store=false` was used.

## Vision boundary

No vision request was made. GP-006 recovered the 16.50% LSEC editing value
from article text, but image-only supplemental values such as the 1.01 +/-
0.38% insertion frequency remain candidates for targeted vision or narrow
repair.

## Human verification required

The approved replacement calls for GP-001, GP-007, and GP-009 completed and
passed the automated structured-output, paper-ID, and evidence-ID checks.
Human review should now confirm the eligibility decisions and inspect GP-007's
extracted formulation, experiment, outcomes, and four unresolved items before
the results are frozen for downstream repair and evaluation.
