# NP-001 Core Biological Slot Trial Design

## Purpose

Test whether a compact checklist of pre-qualified biological outcome slots can
produce complete, scientifically linked extraction records for NP-001 without
returning to the noisy 36-candidate inventory.

The trial addresses the previous call's failure: the model accounted for all
36 candidates but dismissed them as `not_outcome` or
`insufficient_evidence`, even while independently returning one HepG2 outcome.

## Scope and Isolation

The trial is NP-001-only and separate from:

- the production compact route;
- the 36-candidate accounting trial;
- repair and selective-vision routes;
- canonical merging.

It reuses the current compact formulation, component, experiment, outcome, and
evidence-bound field contracts. It adds one focused core-slot builder,
scientific validator, and exact-request trial runner.

Implementation and local testing make no paid calls. The workflow stops at a
new exact request preview and requires explicit human approval before one paid
call.

## Core Definition

A core biological slot exists only when local preprocessing identifies
evidence for all of:

1. an LNP formulation or formulation group;
2. a payload or active co-component;
3. a biological model;
4. a delivery, expression, biodistribution, immune, or therapeutic outcome.

The slot is an extraction obligation, not a model-authored hypothesis. Local
preprocessing decides which slots qualify before the paid call.

Physical characterization alone does not create a core slot. Excluded
categories include SAXS structure, morphology, storage stability, release
kinetics, size, PDI, zeta potential, and background statements.

## NP-001 Slot Matrix

The builder evaluates these six possible slots:

| Slot | Biological model | Outcome family |
|---|---|---|
| `CORE-HEPG2-TRANSFECTION` | HepG2 | transfection/expression |
| `CORE-DC24-TRANSFECTION` | DC2.4 | transfection/expression |
| `CORE-DC24-IMMUNE` | DC2.4 | cytokine/immune response |
| `CORE-HPBMC-TRANSFECTION` | hPBMC | transfection/expression |
| `CORE-HPBMC-IMMUNE` | hPBMC | cytokine/immune response |
| `CORE-MOUSE-BIODISTRIBUTION` | mouse in vivo | biodistribution/expression |

Only slots satisfying the deterministic evidence threshold are sent. The
preflight reports every evaluated slot, whether it qualified, the exact
evidence IDs, and the reason for any exclusion.

This first trial uses a closed NP-001 slot specification so it can test the
contract quickly. Generalizing slot discovery to arbitrary papers is a
separate production decision.

## Evidence Packets

Each qualifying slot receives a compact evidence packet containing:

- allowed formulation or formulation-group evidence;
- allowed payload or active co-component evidence;
- biological-model evidence;
- outcome evidence;
- route, dose, species, organ, recipient-cell, and disease-context evidence
  when applicable;
- exact allowed evidence IDs.

Evidence may be shared across compatible slots, but the model cannot cite
evidence outside the current slot's allowed set when substantiating that slot.

The compact extraction context may include shared formulation information
once. Each slot packet contains the minimum references needed to connect that
shared information to its own model and outcome family.

## No-Escape Accounting Contract

Every sent slot is a required property of a closed `core_slot_accounting`
object. Additional properties are forbidden.

Every slot entry requires:

- `disposition`;
- `linked_experiment_id`;
- `linked_outcome_ids`;
- `evidence_ids`.

The only permitted dispositions are:

- `extracted`;
- `duplicate`.

There is no `insufficient_evidence`, `ambiguous`, or `not_core` disposition.
Those decisions belong to deterministic preflight qualification, not the paid
model.

`extracted` requires one existing experiment ID and one or more existing
outcome IDs. `duplicate` has the same requirements and is valid only when
another qualifying slot legitimately shares the same scientific record.

## Scientific Validation

Schema validity forces a complete claim for every sent slot. A separate
pure-local validator decides whether each claim is scientifically acceptable.

For every slot it verifies:

- the slot key is exact and complete;
- linked experiment and outcome IDs exist;
- outcome IDs are unique in the compact response;
- the experiment's biological model matches the slot;
- the experiment's formulation and payload are compatible with the slot
  evidence;
- the outcome family matches the slot family;
- linked outcomes belong to the linked experiment;
- every cited evidence ID is allowed for that slot and exists in the request;
- the model, formulation/payload, and outcome claims cite their corresponding
  evidence;
- cross-context links such as HepG2 to DC2.4 are rejected;
- cross-family links such as transfection to cytokine response are rejected;
- duplicate claims share a scientifically valid record with another slot.

Closed values and aliases are defined locally for:

- HepG2;
- DC2.4/dendritic-cell context;
- hPBMC;
- mouse in vivo;
- transfection/expression;
- cytokine/immune response;
- biodistribution/expression.

The validator never treats schema compliance as scientific confirmation.
Invalid links remain review-only and cannot be merged.

## Output Fields

Each accepted core record must make the existing compact structures carry:

- formulation identity;
- components and ratios when available;
- payload or active co-component;
- in-vitro or in-vivo model;
- species;
- delivery-recipient cell;
- target organ when applicable;
- disease context when applicable;
- route and dose when applicable;
- one or more distinct delivery, expression, immune, biodistribution, or
  therapeutic outcomes;
- exact evidence IDs.

Missing optional applicability fields remain represented through the existing
reported/not-applicable/not-reported field statuses. They do not excuse a
missing required slot outcome.

## Request and Approval Boundary

The trial:

1. loads the current NP-001 compact packet;
2. evaluates all six possible slots locally;
3. writes the qualification report and compact evidence packets;
4. builds a dynamic schema requiring every qualified slot;
5. writes the exact provider request and signed manifest;
6. reports qualified/excluded slots, request SHA-256, input estimate, output
   cap, and proposed call count;
7. stops for explicit human approval;
8. if approved, sends the exact saved request once with SDK retries disabled;
9. writes a durable invocation marker before dispatch;
10. validates the result locally without automatic repair or vision calls.

An ambiguous provider failure keeps the invocation marker and blocks a second
call until separate human review.

## Acceptance Criteria

The local preflight passes when:

- every evaluated slot has a qualification decision and evidence report;
- every sent slot meets the four-part core threshold;
- the dynamic schema requires exactly the sent slot IDs;
- provider calls remain zero.

The paid trial succeeds when:

- every sent slot is accounted for as `extracted` or a valid `duplicate`;
- every linked experiment and outcome passes local scientific validation;
- no incompatible context or outcome-family link is accepted;
- the HepG2 54% EGFP-positive result is preserved and linked if its slot
  qualifies;
- all other qualifying NP-001 core slots receive scientifically valid records.

Returning valid JSON alone is not success. A slot counts only after local
scientific validation.

## Testing

All implementation tests use synthetic packets and fake providers:

- six-slot qualification and exclusion reasons;
- physical-characterization evidence does not qualify;
- exact dynamic slot keys;
- no unresolved disposition in the schema;
- missing, extra, or substituted slot keys fail;
- missing experiment/outcome links fail;
- HepG2/DC2.4/hPBMC/mouse cross-links fail;
- transfection/immune/biodistribution cross-links fail;
- evidence outside the slot fails;
- valid extracted and legitimate duplicate records pass;
- production compact and 36-candidate trial routes remain unchanged;
- NP-001-only preflight makes zero calls;
- exact-byte approval and durable one-call guard remain enforced.

## Non-Goals

This trial does not:

- infer arbitrary-paper core slots;
- add automatic repairs;
- add selective vision;
- force one outcome per low-level sentence;
- merge results into production;
- claim that schema enforcement alone guarantees scientific accuracy.
