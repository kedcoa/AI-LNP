# Strategy A Kupffer Arm Benchmark Design

**Date:** 2026-07-31  
**Status:** Proposed for user review  
**Scope:** One precision-first, human-gated benchmark on NP-002 Kupffer-cell evidence

## Objective

Test the smallest useful version of experimental-arm accounting before investing
in further automation. The benchmark succeeds when one paid extraction call
returns five or six of the six expected Kupffer-cell arms with scientifically
correct formulation, payload, dose, model, route, timepoint, assay, and outcome
linkage.

If fewer than five arms are scientifically correct, stop. Do not implement the
later automation phases on the assumption that stricter accounting will work.

## Non-goals

- No fully automatic arm approval.
- No second discovery LLM.
- No independent LLM coverage auditor.
- No production-wide orchestration layer.
- No repair, vision, or retry call in this benchmark.
- No changes to the existing NP-002 source or prior responses.
- No paid call before a separate exact-request approval.

## Inputs

Use the existing NP-002 ingestion artifacts and evidence packet for:

- MC3 and cKK-E12 LNPs;
- QUANT DNA biodistribution at 0.3 mg/kg;
- Cre mRNA functional delivery at 1.0 and 0.3 mg/kg;
- Kupffer cells in mice;
- intravenous lateral-tail-vein administration;
- six-hour QUANT and three-day Cre outcome assessment;
- FACS cell isolation, ddPCR QUANT measurement, and tdTomato flow-cytometry
  measurement.

The builder may use only evidence already present in the preserved NP-002
packet. It must not use facts manually typed into production extraction output.

## Arm identity

An arm is uniquely identified by:

1. formulation;
2. payload;
3. dose;
4. route;
5. model/species;
6. treatment schedule;
7. target-cell outcome context.

Assay and timepoint are mandatory extraction fields, but they do not create a
new arm unless the treatment condition also changes.

For this paper, the expected Kupffer benchmark inventory is:

| Candidate | Formulation | Payload | Dose |
|---|---|---|---|
| KUP-01 | MC3 | QUANT DNA | 0.3 mg/kg |
| KUP-02 | cKK-E12 | QUANT DNA | 0.3 mg/kg |
| KUP-03 | MC3 | Cre mRNA | 1.0 mg/kg |
| KUP-04 | cKK-E12 | Cre mRNA | 1.0 mg/kg |
| KUP-05 | MC3 | Cre mRNA | 0.3 mg/kg |
| KUP-06 | cKK-E12 | Cre mRNA | 0.3 mg/kg |

These six rows are the human-reviewed benchmark expectation. The implementation
must demonstrate which rows the local builder proposed independently and which,
if any, required human correction.

## Precision-first local builder

The local builder proposes arms from explicit relationships inside one
experiment context. It must not create a Cartesian product from paragraph
co-occurrence alone.

Each proposed arm contains:

- a stable candidate ID;
- normalized arm fields;
- `pairing_type`: `single_statement`, `cross_product`, or
  `paired_correspondence`;
- evidence IDs proving arm existence;
- evidence IDs available for outcome extraction;
- local confidence and any quarantine reason.

`cross_product` is allowed only when language explicitly applies alternatives
to the same experimental condition, such as “either MC3 or cKK-E12” with “0.3
or 1.0 mg/kg Cre mRNA.” “Respectively,” ordered lists, and numbered one-to-one
mappings must use `paired_correspondence`.

## Human review gate

Before request construction, present the proposed arms and their proof evidence
in human-readable form. The reviewer can accept, correct, remove, or add an arm.
Record all changes in a review artifact.

The paid request is built only from the approved six-arm inventory. Human
review corrects the benchmark input; it does not count as automated builder
success.

## Paid extraction contract

Run exactly one Kupffer-cell call after separate user approval of:

- final request path and SHA-256;
- exact input-token estimate;
- maximum output tokens;
- model;
- provider call count of one.

The request contains all six candidate IDs and compact evidence. The response
must account for the exact same ID set.

Allowed dispositions:

- `extracted`;
- `ambiguous`.

`ambiguous` requires cited evidence and a reason code, and earns no extraction
credit. There is no `invalid`, `not_core`, or unrestricted
`insufficient_evidence` disposition.

Duplicate arms should be removed locally before the paid call. The LLM does not
receive a general-purpose duplicate escape tag in this six-arm benchmark.

## Validation

Local structural validation requires:

- input candidate IDs equal output candidate IDs;
- no missing, invented, or repeated IDs;
- every extracted candidate links to one returned experiment and at least one
  returned outcome;
- formulation, payload, dose, route, model, and target cell agree with the
  approved arm;
- every citation belongs to the supplied evidence envelope;
- no evidence is borrowed across incompatible experiment contexts.

Human scientific evaluation checks each arm for:

- correct formulation and composition;
- correct payload and dose;
- correct Kupffer-cell scope;
- correct route and model;
- six-hour QUANT or three-day Cre timepoint;
- ddPCR for QUANT or tdTomato flow cytometry for Cre;
- correct biodistribution or functional-delivery outcome and comparator.

## Benchmark decision

Report three separate counts:

1. accounted arms;
2. structurally valid extracted arms;
3. scientifically correct arms.

Decision:

- **Pass:** five or six scientifically correct arms.
- **Fail:** zero through four scientifically correct arms.

A pass permits planning the next automation phase; it does not automatically
trigger further implementation or paid calls. A fail stops the experiment with
the raw response and failure analysis preserved.

## Safety and cost controls

- Preflight is the default action.
- Provider credentials are cleared during all tests.
- Approved execution verifies immutable request bytes and SHA-256.
- Exactly one provider invocation; retries disabled.
- Refuse execution if a completed invocation marker already exists.
- No repair or vision dispatch.
- Preserve raw response, parsed result, validation report, scientific review,
  usage, and request/response hashes.
- Never stage or commit `.env`.

## Why the final four-part hardening cycle is required

The first paid call has not occurred. Final code review of the locally prepared
request found four implementation gaps that could make a real response appear
better or worse than it actually is, or could leave an attempted call without a
complete audit. These changes do not add another extraction layer and do not
change the approved six Kupffer arms. They make the existing benchmark contract
faithfully enforce this design.

### 1. Connect route and model evidence to the correct experiment

The builder now connects treatment evidence to target/outcome evidence using
packet-native source or adjacency metadata. However, it can still append a
route sentence or Ai14-model sentence from a different experiment. That violates
the existing rule that evidence must not be borrowed across incompatible
experiment contexts.

The hardening must require route and model evidence to belong to the same
connected experiment evidence graph as the treatment and outcome, except for a
clearly identified reusable protocol statement whose packet context explicitly
links it to that experiment. If that relationship is absent, the automatic
builder must quarantine the arm. Human review may still approve an arm only
through exact, SHA-bound packet evidence.

### 2. Audit every malformed or contract-invalid API response

The one-call marker is intentionally written before provider execution so a
crash cannot accidentally trigger a second paid call. That means every terminal
path after the marker must also write a terminal failure manifest. Review found
that JSON objects failing Pydantic validation and provider exceptions are now
audited, but valid JSON scalars or arrays can fail before the audit handler.
One validation path also omitted an already-computed response hash.

The hardening must treat every provider exception, invalid JSON response,
non-object JSON response, and object-shaped contract failure as a terminal,
non-retryable result. It must preserve every available request, raw-response,
parsed-response, usage, and validation hash before re-raising the error.

### 3. Separate structural validity from scientific accuracy

The benchmark deliberately reports three different quantities: accounted,
structurally valid, and scientifically correct. Review found that assay or
timepoint failures were being subtracted from the structural count. That would
hide a useful result such as “the model created and linked all six records, but
two used the wrong assay.”

Structural validity must cover accounting, record linkage, candidate identity,
evidence-envelope compliance, and incompatible record reuse. Scientific
accuracy must independently cover assay, timepoint, route, model, target, and
outcome semantics. A candidate may therefore be structurally valid but
scientifically incorrect, and both facts must remain visible.

### 4. Prevent negative validity counts

The scoped evidence validator currently adjusts an aggregate structural count
after the core validator has already removed candidates. The same candidate can
therefore be subtracted twice, producing an impossible negative result.

Both validators must operate on candidate-ID sets rather than decrementing an
integer. The final count is the size of the remaining valid-ID set, which
guarantees a value from zero through six and makes every removed candidate
traceable to a concrete error.

### Acceptance gate after hardening

The four changes are complete only when focused negative regressions pass, the
complete credential-cleared suite passes, and independent review finds no
remaining Critical or Important defect in these paths. The signed six-arm review
and immutable request must then be regenerated because any code or proposal
change invalidates the prior SHA-256. The regenerated request still requires a
separate explicit paid-call approval.

## Testing

Add focused tests for:

- six-arm construction from explicit NP-002 relationships;
- rejection of unsupported cross-products;
- `respectively`/paired-correspondence behavior;
- immutable human review artifact;
- exact six-ID schema and set-equality validation;
- rejection of missing, invented, or repeated IDs;
- no duplicate/invalid/not-core escape dispositions;
- correct assay and timepoint requirements;
- zero-call preflight;
- one-call execution guard with a fake provider;
- no retry, repair, or vision dispatch.

Run the focused tests and the complete test suite before preparing the paid-call
approval packet.
