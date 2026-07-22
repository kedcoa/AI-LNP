# Claims Matrix

## Direct evidence

A formulation, experiment, or outcome explicitly reported in a cited source.

Allowed wording:

- "Reported in..."
- "The study measured..."
- "The authors observed..."

## Normalized or derived data

A value mechanically transformed from reported information using documented
code.

Allowed wording:

- "Normalized from the reported value..."
- "Calculated from reported composition values..."

## Similarity analogy

An existing formulation retrieved because its encoded composition is similar
to the query.

Allowed wording:

- "Similar reported formulation"
- "Nearest formulation in the available evidence"

Prohibited wording:

- "Predicted to work in this cell"
- "Best formulation"
- "Validated recommendation"

## DOE experiment

An untested candidate selected to improve experimental-space coverage while
satisfying programmed constraints.

Allowed wording:

- "Experimental candidate"
- "Suggested for testing"
- "Requires chemical and experimental review"

## COMET research prediction

Disabled by default and enabled only for a cell/task registered as having
passed the Track B readiness and model-value gates.

Every prediction must be labelled `model_prediction`, stored as y-hat, and
shown separately from reported or prospectively measured y. Required gates
include an appropriate labeled dataset, grouped validation, baseline
comparison, calibration or uncertainty evaluation, OOD handling, and release
review.
