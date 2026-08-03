# Candidate-Specific Evidence Projection Design

## Problem

The six-arm NP-002 response accounted for and extracted all six approved arms, but local validation rejected every arm for two bookkeeping reasons:

1. The top-level accounting entry did not repeat every citation already present in its linked formulation, experiment, and outcome records.
2. Shared MC3 and cKK-E12 formulation records contained globally valid citations from both dose contexts, so each narrow arm envelope saw one harmless citation from another context as an error.

These checks confuse extra citation metadata with missing scientific support.

## Decision

Validation will construct a candidate-specific evidence projection without modifying the raw LLM response.

For each candidate:

- Collect the evidence groups used by its linked formulation, experiment, and outcome fields.
- Intersect each evidence group with that candidate's approved evidence envelope.
- Require every scientific evidence group to retain at least one permitted citation.
- Treat the accounting entry's citations as supplementary evidence, not as a duplicate index of every linked field citation.
- Ignore extra globally valid citations on shared records when the same field has permitted evidence inside the candidate envelope.
- Continue rejecting a candidate when a required field is supported only by evidence outside its envelope.

## Scope

The change is limited to experimental-arm scientific validation and the NP-002 scoped-envelope wrapper. It does not alter prompts, schemas, extraction records, approved arm definitions, or API execution.

## Error Handling

The existing `candidate_evidence_outside_arm_envelope` error will be emitted only when a required linked scientific evidence group has no citation inside the candidate's approved packet. Mere presence of additional globally valid citations will not invalidate an arm.

The existing `accounting_evidence_does_not_cover_scientific_fields` rule will no longer require the accounting block to duplicate citations already carried by linked scientific fields.

## Tests

Regression tests will prove:

- A correct arm with a shared formulation citation from another approved arm passes when every required field also has in-envelope support.
- A field supported exclusively by another arm's evidence still fails.
- A short accounting citation list does not invalidate otherwise fully supported linked records.
- The saved six-arm API response revalidates locally without making another API call.

## Success Criteria

- Existing wrong-arm evidence protections remain green.
- The saved response accounts for six arms and scientifically confirms the arms whose required fields are supported by their approved evidence packets.
- No API client is invoked.
