# Six Isolated NP-001 Core Calls Design

## Goal

Replace the failed global six-slot response with six independent, sequential
requests. Each request receives one slot's compact evidence and must return
one complete experiment/outcome record for that slot.

## Requests

Create one exact request for each:

1. `CORE-HEPG2-TRANSFECTION`
2. `CORE-DC24-TRANSFECTION`
3. `CORE-DC24-IMMUNE`
4. `CORE-HPBMC-TRANSFECTION`
5. `CORE-HPBMC-IMMUNE`
6. `CORE-MOUSE-BIODISTRIBUTION`

Each request:

- contains only its slot-specific evidence packet plus the minimal shared
  formulation/payload evidence already selected by the compact preflight;
- requires exactly one `extracted` slot disposition;
- forbids `duplicate` and unresolved dispositions;
- requires a linked experiment and at least one linked outcome;
- uses the existing compact response structures;
- is independently hashed, previewed, invoked, and scientifically validated.

## Execution

Calls run sequentially, never as a batch. The next call starts only after the
previous provider response is persisted and locally validated. SDK retries,
repair calls, and vision calls are disabled.

Every call has a distinct request, manifest, invocation marker, response, and
validation report. An HTTP/provider ambiguity or failed local request audit
stops the sequence. A scientifically invalid but successfully persisted
response is recorded and the sequence may continue because no provider state
is ambiguous.

The user's instruction explicitly authorizes up to six paid calls in this
sequence. No seventh call or retry is authorized.

## Acceptance

- Six exact request JSON files pass local schema/evidence audits.
- Each request contains one and only one slot.
- Calls are dispatched in the listed order, one at a time.
- Each output is accepted only if its model, outcome family, formulation,
  payload, experiment, and evidence pass the existing local validator.
- Results remain trial-only and are not merged automatically.
