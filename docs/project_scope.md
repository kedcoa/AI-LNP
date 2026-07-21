# Project Scope

## Target cell types

- Hepatocyte
- Kupffer cell
- Liver sinusoidal endothelial cell (LSEC)
- Hepatic stellate cell (HSC)

## Track

This project follows Track A. It does not assume that a paired four-cell
training dataset or new wet-lab data are available.

## Five-week deliverable

A public, read-only Streamlit application that:

- retrieves traceable literature evidence;
- filters evidence by biological and experimental context;
- distinguishes comparable from non-comparable outcomes;
- retrieves similar reported formulations;
- displays out-of-distribution warnings;
- produces constrained DOE experimental suggestions; and
- preserves citations and evidence for every material result.

## Outside the five-week commitment

- Prospective wet-lab validation
- Four-cell predictive-model training
- A validated COMET liver-cell model
- Claims that a formulation is universally best
- Claims of in-vivo liver-cell targeting
- Public experiment submission

## Optional stretch work

A neocloud GPU may be used on Day 25 to test whether the COMET environment
and a known checkpoint can be reproduced. This is not required for Track A
completion.

## Data identity boundary

- X: formulation or candidate input
- y-hat: optional model prediction
- y: reported or experimentally measured outcome

DOE generates X, not y.

A model generates y-hat, not y.

Only reported literature measurements or quality-controlled wet-lab
measurements may be stored as y.