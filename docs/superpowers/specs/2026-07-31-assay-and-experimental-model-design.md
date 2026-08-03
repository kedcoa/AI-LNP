# Assay Alias and Experimental Model Design

## Goal

Remove two scientific-validation mismatches before the next NP-002 paid call:

1. Treat `ddPCR`, `digital droplet PCR`, and `droplet digital PCR` as the same assay.
2. Store the experimental animal model separately from the disease model.

## Data Contract

`ExperimentRecord` gains an `experimental_model` reported field. The strict API schema requires the field but allows a reported value or a normal missing value through the existing `TextField` contract.

The meanings are:

- `species`: organism, such as `Mus musculus`.
- `experimental_model`: strain or engineered model, such as `Ai14 Cre-reporter mice`.
- `disease_model`: disease context only; it remains missing for NP-002 because the paper does not study a disease model.

For compatibility with already stored local responses, the Python model accepts an omitted `experimental_model`, while OpenAI's strict JSON schema requires it in new responses.

## Prompt and Validation

The compact prompt explicitly distinguishes experimental and disease models. It instructs the model not to place reporter strains into `disease_model`.

The approved arm's `model` value is validated against `experimental_model`, not `disease_model`. Experimental-model evidence becomes part of the candidate evidence projection.

Assay validation canonicalizes unambiguous ddPCR names before comparison. It does not accept generic PCR or qPCR.

## Scope

No database migration, unrelated schema refactor, API call, or automatic retry is included. The benchmark only prepares a new preflight request after local tests pass. Execution pauses for human approval.

## Success Criteria

- Full-name ddPCR variants pass; `qPCR` still fails.
- Ai14 arms require `experimental_model = Ai14 Cre-reporter mice`.
- `disease_model` may correctly remain missing for all six arms.
- A fresh preflight request includes the new field and has an exact token estimate.
- No paid API call occurs before explicit approval.
