# Six-Arm Payload-Role Benchmark Design

## Goal

Retest NP-002 as six scientifically valid Kupffer-cell delivery arms without
forcing DNA-tracer experiments into an RNA-therapeutic interpretation and
without mixing evidence between the 1.0 and 0.3 mg/kg Cre-mRNA experiments.

## Selected approach

Keep all six arms in extraction. Separate extraction eligibility from
therapeutic-recommendation eligibility:

- KUP-01 and KUP-02 are extractable DNA biodistribution records.
- KUP-03 through KUP-06 are extractable mRNA functional-delivery records.
- Only records satisfying the application's recommendation policy proceed to
  therapeutic recommendation. A DNA tracer is not therapeutic RNA evidence.

This is preferred over removing KUP-01/02 because removal would avoid testing
payload-role classification. It is preferred over treating every payload as
therapeutically equivalent because that would erase an important scientific
distinction.

## Data contract

The payload remains the material physically carried by the LNP. Add a closed
payload-role field with the values:

- `therapeutic`
- `reporter`
- `biodistribution_tracer`
- `screening_barcode`

For NP-002:

| Arms | Payload | Payload role | Evidence type |
|---|---|---|---|
| KUP-01/02 | QUANT DNA | `biodistribution_tracer` | ddPCR biodistribution |
| KUP-03/04 | Cre mRNA | `reporter` | tdTomato functional delivery at 1.0 mg/kg |
| KUP-05/06 | Cre mRNA | `reporter` | tdTomato functional delivery at 0.3 mg/kg |

DNA must not be represented as an LNP component or only as an assay. The assay
measures the DNA payload after delivery.

## Evidence-envelope corrections

Each arm receives only dose-compatible evidence.

KUP-03/04 must include:

- 1.0 mg/kg Cre-mRNA administration with MC3 and cKK-E12.
- Three-day endpoint and flow-cytometry analysis.
- High tdTomato-positive delivery at that dose.
- The reported 1.0 mg/kg MC3/cKK-E12 comparison.
- Kupffer-cell endpoint and intravenous-route/model evidence.

The 0.3 mg/kg-specific outcome must not be used as a direct KUP-03/04 outcome.

KUP-05/06 must include:

- 0.3 mg/kg repeat-experiment evidence.
- The decrease relative to 1.0 mg/kg.
- The reported 0.3 mg/kg MC3/cKK-E12 comparison and Kupffer-cell outcome.
- Formulation identity, model, route, assay, and endpoint evidence used by
  linked records.

KUP-01/02 retain the 0.3 mg/kg QUANT-DNA treatment, ddPCR/biodistribution, cell
isolation, formulation, route, and Kupffer-cell outcome evidence.

## Eligibility behavior

The paper remains extractable when it contains original LNP delivery evidence
with a supported evidence payload role. Recommendation eligibility is evaluated
separately:

- DNA tracer records can contribute formulation-to-cell delivery evidence.
- DNA tracer records cannot silently qualify as therapeutic RNA evidence.
- Reporter mRNA records can contribute functional-delivery evidence but are
  still labeled as reporter experiments.

No ingestion behavior changes. Ingestion continues to preserve raw evidence;
payload-role classification occurs in extraction.

## Validation and failure behavior

- All six candidate IDs must be accounted for.
- Extracted candidates must link at least one experiment and one outcome.
- Candidate evidence must remain inside its approved arm envelope.
- Dose, payload identity, payload role, formulation, assay, model, target cell,
  and outcome linkage are validated independently.
- Structural validity and scientific confirmation remain separate.
- The pipeline stops after a new zero-call preflight and requires explicit
  approval for any paid retry.

## Testing

Test-driven regressions will prove:

1. QUANT DNA is accepted as a `biodistribution_tracer` payload.
2. DNA tracer extraction does not imply RNA therapeutic eligibility.
3. KUP-03/04 cannot cite 0.3 mg/kg-only outcomes.
4. KUP-05/06 envelopes contain every evidence record used by their linked
   scientific fields.
5. The regenerated strict schema remains provider-compatible.
6. The exact six-arm preflight is SHA-bound and makes zero provider calls.

## Scope exclusions

- No ingestion rewrite.
- No new orchestration layer.
- No repair, vision, retry, or additional model call.
- No general ontology expansion beyond the four payload roles required here.
