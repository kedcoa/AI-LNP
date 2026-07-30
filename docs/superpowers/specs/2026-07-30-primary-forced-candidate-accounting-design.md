# Primary Forced Candidate Accounting Trial Design

## Purpose

Test whether mandatory candidate-by-candidate accounting prevents the compact
primary extraction model from returning one valid outcome while silently
ignoring the remaining supplied candidates. The first trial is limited to
NP-001 and must not change the default compact primary route, merge into a
canonical dataset, or authorize a paid call.

The trial succeeds at accounting when every candidate sent to the model
receives exactly one disposition. It succeeds scientifically only when every
claimed extraction or duplicate also passes deterministic evidence and
structural validation. The number of candidates is not an expected number of
unique outcomes.

## Scope

The trial adds a forced-accounting variant of the existing compact primary
request. It reuses the current evidence packet, recall support, formulation,
component, experiment, and outcome contracts. It adds one focused accounting
contract and validator, an isolated request route/version, local preflight, and
same-paper evaluation.

The trial does not:

- change the default `compact-route-1.2.0` request or response;
- change the repair or selective-vision contracts;
- add a coordinator or automatic retry;
- make, merge, or approve a paid request;
- claim that every raw candidate is a valid outcome;
- add Figure 1e or Figure 3a image pixels to the primary text call.

## Options Considered

### Required object keyed by candidate ID — selected

Generate a `candidate_accounting` object whose property names are the exact
candidate IDs in the request. Every property is required and additional
properties are forbidden. This is the strongest schema-level guarantee that a
valid structured response cannot omit a candidate or repeat one identifier in
place of another.

### Fixed-length resolution list — rejected

A list with `minItems == maxItems == candidate_count` is simpler, but the model
could repeat one candidate ID. A local validator would detect the error only
after the paid call, so the schema would not provide the intended forced
accounting.

### Post-primary repair only — rejected for this trial

The current repair contract has stronger candidate resolution semantics, but
using repairs alone preserves the primary failure mode and can require
multiple paid calls. Repairs remain available after the isolated experiment,
subject to separate human approval.

## Isolation Boundary

The trial uses:

- primary route: `primary-candidate-accounting-trial`;
- route version: `compact-route-1.3.0-trial`;
- accounting wrapper version: `compact-accounting-trial-1.0.0`;
- preflight version: `compact-primary-accounting-preflight-1.0.0`;
- a separate preflight and run output root selected explicitly by the caller.

The default `build_openai_request()` and `run_one()` behavior remains byte-for-
byte compatible unless the caller explicitly selects the trial functions. The
trial runner refuses any paper other than `NP-001`. Trial output is review-only
and never enters the normal merge path.

## Candidate Set

The trial begins with the exact atomic candidates produced by
`build_v12_route_support()` for NP-001. The preflight records:

- raw candidate count and IDs;
- locally quarantined candidate count and IDs;
- sent candidate count and IDs;
- a checksum of the ordered sent candidate facts.

For this first isolated experiment, all 36 existing NP-001 candidates are sent.
This intentionally tests whether forced accounting works across high,
medium-confidence, malformed, and visual candidates. Local eligibility remains
diagnostic rather than silently removing candidates. A later production design
may quarantine malformed candidates before the call, but that is outside this
trial.

## Accounting Contract

The response retains the existing compact extraction fields and adds:

```json
{
  "accounting_contract_version": "compact-accounting-trial-1.0.0",
  "candidate_accounting": {
    "AOC-example": {
      "disposition": "extracted",
      "linked_outcome_ids": ["O1"],
      "evidence_ids": ["E-example"],
      "reason_code": "directly_reported"
    }
  }
}
```

Every sent candidate ID is a required property. `additionalProperties` is
false. Each value requires all four fields. Dispositions are:

- `extracted`;
- `duplicate`;
- `not_outcome`;
- `insufficient_evidence`;
- `requires_visual`;
- `ambiguous`.

Reason codes are compact and closed:

- `directly_reported`;
- `same_fact_as_linked_outcome`;
- `context_or_method_only`;
- `malformed_candidate`;
- `evidence_does_not_support_outcome`;
- `visual_value_not_available_as_text`;
- `conflicting_or_incomplete_evidence`;
- `experiment_assignment_uncertain`.

`extracted` and `duplicate` require at least one linked outcome ID.
`not_outcome`, `insufficient_evidence`, `requires_visual`, and `ambiguous`
require an empty linked-outcome list. Every disposition requires at least one
of that candidate's supplied evidence IDs. All 36 current NP-001 candidates
have supplied evidence, including candidates diagnosed as malformed.

The schema forces complete accounting, not scientific correctness. All
scientific claims remain subject to local validation.

## Dynamic Schema Construction

A focused module receives the static strict JSON schema generated from
`CompactExtractionResponse` plus the ordered candidate list. It returns a
strict wrapper schema that:

1. preserves every existing compact response field and keeps
   `contract_version: "compact-1.1.0"`;
2. adds the required accounting version;
3. adds one required candidate-accounting property per sent ID;
4. reuses one shared accounting-entry definition;
5. forbids unknown top-level and candidate-accounting properties.

The request fingerprint and signed preflight manifest bind the dynamic schema
checksum, candidate facts checksum, route, route version, model, packet
checksum, and exact request bytes.

## Local Validation

The trial parser validates the compact extraction body with the existing
`CompactExtractionResponse` model after removing the two trial-only accounting
fields. A new pure-local validator then checks the accounting block.

### Set and syntax checks

- Returned candidate keys equal the sent candidate IDs exactly.
- No unknown or missing candidate is accepted.
- Every linked outcome ID exists in the returned outcome list.
- Outcome IDs are unique within the result.
- Every accounting evidence ID belongs to that candidate's allowed evidence.
- Every accounting evidence ID exists in the request evidence envelope.

### Disposition checks

- `extracted` requires a linked outcome that passes the existing deterministic
  structural comparison for that candidate.
- `duplicate` requires a linked outcome that passes the same structural
  comparison and is linked by at least one other candidate.
- `requires_visual` requires visual provenance or a candidate whose source is a
  figure/table object unavailable as accepted textual evidence.
- `not_outcome` with `context_or_method_only` or `malformed_candidate` must
  agree with the existing candidate diagnostics.
- Other unresolved dispositions remain unmerged and carry their explicit
  reason code into the evaluation report.

Model-authored disposition labels never override deterministic structural
contradictions. Unsupported links are reported as rejected and remain
unconfirmed.

### Authoritative counts

The local validator—not the model—computes:

- candidates sent;
- candidates accounted for;
- valid extracted;
- valid duplicates;
- rejected links;
- not outcomes;
- insufficient evidence;
- requires visual;
- ambiguous;
- unique returned outcomes;
- structurally confirmed candidates.

Accounting completeness is `accounted_for / sent`. Scientific recovery is
reported separately and never inferred from accounting completeness.

## Request and Execution Flow

1. Load the current NP-001 compact API packet.
2. Build the existing v1.2 recall support once.
3. Build the dynamic trial schema from its ordered 36 candidates.
4. Build and persist the exact trial request locally.
5. Run existing schema/evidence audits plus trial-specific accounting audits.
6. Write a signed local manifest with `provider_calls: 0`.
7. Present the exact request path, SHA-256, input estimate, output cap, candidate
   count, and one-call proposal to the human.
8. Stop for explicit approval.
9. If approved, send exactly the approved request bytes once.
10. Validate and persist the core extraction, accounting report, structural
    coverage, response, usage, and manifest under a trial-only output root.
11. Do not run repair or vision automatically.

## Same-Paper Evaluation

The trial compares the new NP-001 result with the completed baseline response:

- baseline: one formulation, one experiment, one outcome;
- baseline loose candidate match: 1 of 36;
- baseline strict structural confirmation: 0 of 36.

The trial report must show:

- whether all 36 candidates received a disposition;
- how many claimed links passed structural validation;
- how many distinct formulations, experiments, and outcomes were returned;
- whether HepG2, DC2.4, hPBMC, mouse biodistribution, and table/figure
  candidates received explicit treatment;
- whether any candidate was incorrectly grouped into an incompatible outcome;
- which candidates require separate selective vision.

Passing the schema-accounting acceptance criterion requires 36 of 36 exact
candidate keys. Passing the scientific acceptance criterion requires no
accepted random/incompatible links and more than the baseline zero strict
confirmations. The result does not need to extract 36 unique outcomes.

## Figure-Only Formulations

Figure 1e and Figure 3a contain exact theoretical molar compositions. The
primary accounting trial must identify these as visual when the values are not
available in accepted text evidence. It must not hallucinate those percentages
from candidate names.

After the primary trial, local Docling/OCR may attempt extraction and validate
that each formulation sums to approximately 100 mol%. If local extraction
remains incomplete, a separate selective-vision preflight may be prepared for
those panels. Any selective-vision call requires a new exact request preview
and explicit human approval.

## Error Handling

- Missing, extra, or malformed accounting keys invalidate the trial response.
- A nonexistent linked outcome ID invalidates that accounting entry.
- A structurally incompatible link is rejected and cannot count as extracted
  or duplicate.
- Output truncation or invalid structured JSON fails the trial; there is no
  automatic retry.
- An all-unresolved response may be accounting-complete but is scientifically
  unsuccessful and cannot merge.
- Existing duplicate-call refusal and exact-approved-byte checks remain
  mandatory.

## Token and Time Budget

The dynamic schema should add approximately 1,000–2,500 input tokens. Compact
accounting entries should add approximately 1,500–3,000 output tokens before
any additional scientific records. The trial retains a 12,000 output-token cap
and must measure the exact serialized request locally before approval.

Implementation, TDD, full verification, review, and local preflight should fit
within approximately two to three hours. The design adds no paid work until the
human approves the exact same-paper retest request.

## Testing

Tests use fake provider responses and make no network calls.

Required cases:

- dynamic schema requires every candidate key;
- a missing, extra, or repeated substitute ID is rejected;
- a valid extracted link passes;
- a nonexistent outcome ID is rejected;
- a random endpoint/cell/evidence link is rejected;
- a valid duplicate link passes and is counted once;
- a visual candidate can be marked `requires_visual`;
- a malformed candidate can be marked `not_outcome`;
- all-unresolved accounting is complete but scientifically unsuccessful;
- core compact response validation remains unchanged;
- default v1.2 request bytes and route behavior remain unchanged;
- NP-001 trial preflight makes zero provider calls and binds exact bytes;
- trial runner refuses non-NP-001 papers and duplicate paid execution;
- the provider receives exactly the approved trial request dictionary.

## Adoption Gate

The trial does not become the default route automatically. Production adoption
requires a separate decision after reviewing NP-001 accounting completeness,
scientific validation, token use, and failure modes. Any production design must
decide whether to pre-quarantine malformed candidates and how to generalize the
dynamic schema without changing the repair and selective-vision boundaries.
