# Compact extraction contract v1 - human verification draft

Status: **human verified on 2026-07-27**

Contract version: `compact-1.1.0`

## Purpose

The contract keeps the existing relational entities - paper, formulation,
chemical component, experiment, outcome, and evidence - while reducing the
model response to structured values and local evidence IDs. Evidence text and
source coordinates stay in the local evidence packet and are not repeated in
the OpenAI response.

No database migration is part of this change.

## Paper eligibility

Every response now contains one `eligibility` record with a decision,
controlled screening reason codes, supporting evidence IDs, and a short
explanation. Eligible decisions require all five inclusion criteria:
original experiment, identifiable LNP, supported RNA payload, relevant liver
cell evidence, and formulation-experiment-outcome linkage. A clearly failed
criterion is `ineligible`; insufficient or ambiguous evidence is `uncertain`.
Both `ineligible` and `uncertain` require empty extraction-record lists.

## Required literature-product fields

| Product need | Compact response field |
|---|---|
| Formulation name and composition | `formulations[].formulation_name`, `composition`, `composition_basis`, `np_ratio` |
| Component identity, role, and amount | `components[].identity`, `role`, `amount`, `amount_unit` |
| Payload type, name, encoded product, or molecular target | `experiments[].payload_type`, `payload_name`, `encoded_product`, `molecular_target` |
| Delivery-recipient cell | `experiments[].delivery_recipient_cell` |
| Therapeutic-target cell | `experiments[].therapeutic_target_cell` |
| Tissue or organ | `experiments[].tissue_or_organ` |
| Species and disease model | `experiments[].species`, `disease_model` |
| In-vitro, ex-vivo, or in-vivo context | `experiments[].experimental_context` |
| Dose, route, and timepoint | `experiments[].dose`, `dose_unit`, `route`, `timepoint`, `timepoint_unit` |
| Assay, endpoint, comparator, and outcome | `outcomes[].assay`, `endpoint`, `comparator`, `outcome_value`, `outcome_unit`, `qualitative_outcome` |

## Evidence boundary

Every scientific field uses the same shape:

```json
{
  "value": "reported value or null",
  "status": "reported or missing",
  "evidence_ids": ["local-packet-evidence-id"],
  "missing_reason": "required only when status is missing"
}
```

- `reported` requires a non-null value and at least one evidence ID.
- `missing` requires a null value, no supporting evidence IDs, and a reason.
- Evidence IDs are checked against the IDs in the local packet.
- The model response has no evidence quotation or evidence-coordinate fields.
- IDs linking records are structural and do not themselves represent
  scientific claims.

## Relational preservation

- `paper_id` scopes the response to one paper.
- Components and experiments reference a formulation.
- Payload fields remain on the experiment record; outcomes reference an
  experiment.
- Evidence remains local and is joined after response validation.
- The SQL experiment columns are mapped as follows:
  - `tissue_or_organ` -> `experiment.tissue_or_organ`
  - `disease_model` -> `experiment.disease_model`
  - `encoded_product` -> `experiment.payload_encoded_product`
  - `molecular_target` -> `experiment.payload_molecular_target`

## Human verification decisions

1. The field list is sufficient for the literature-search product.
2. Tissue/organ, disease model, encoded product, and molecular target use the
   additive SQL mapping documented above.
3. Recipient and target cells remain faithful free text during extraction and
   receive controlled normalization later.
4. `missing` carries no supporting evidence IDs. Packet checksums, retrieval
   coverage, unresolved-item logs, and targeted review provide auditability.
5. The initial response version was `compact-1.0.0`.
6. After the first Day 3 pilot, explicit eligibility was human requested and
   added as `compact-1.1.0`; the original GP-002 pilot remains a frozen v1.0.0
   historical result.
