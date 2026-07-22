# Project Scope

## Target cell types

- Hepatocyte
- Kupffer cell
- Liver sinusoidal endothelial cell (LSEC)
- Hepatic stellate cell (HSC)

## Track

This project follows the eight-week Track B plan. It combines a complete
four-cell literature-evidence product with conditional hepatocyte-first COMET
adaptation and prospective validation. COMET proceeds only if the selected
task passes data-readiness and model-value gates.

## Eight-week deliverable

A public, read-only Streamlit application that:

- retrieves traceable literature evidence;
- filters evidence by biological and experimental context;
- distinguishes comparable from non-comparable outcomes;
- retrieves similar reported formulations;
- displays out-of-distribution warnings;
- optionally produces constrained DOE experimental suggestions;
- exposes a separately gated COMET research mode when validation passes; and
- preserves citations and evidence for every material result.

The application remains fully usable in literature-only mode if COMET is not
trained or does not pass evaluation.

## Outside the commitment

- Four-cell predictive-model training
- Predictions for Kupffer cells, LSECs, or HSCs before their own gates pass
- Claims that a formulation is universally best
- Claims of in-vivo liver-cell targeting
- Public experiment submission

## Conditional COMET and prospective work

Weeks 3-4 audit data readiness, reproduce COMET, compare baselines, and run
grouped evaluation. Weeks 5-8 design the UI, integrate only an approved model,
and conduct a preregistered prospective hepatocyte test when the preceding
gates pass. A failed gate disables the dependent model or experiment work; it
does not block the literature-evidence application.

## Data identity boundary

- X: formulation or candidate input
- y-hat: optional model prediction
- y: reported or experimentally measured outcome

DOE generates X, not y.

A model generates y-hat, not y.

Only reported literature measurements or quality-controlled wet-lab
measurements may be stored as y.
