# Day 5 morning: extraction contracts

Detailed extraction is a separate stage from relevance screening. A screening
decision never creates a formulation, component, experiment, outcome, or
evidence record by itself.

All scientific fields use `EvidenceBoundValue` and must be supplied explicitly:

- `reported`: the value is non-null and cites one or more evidence IDs;
- `missing`: the value is null, cites no supporting evidence, and explains why
  it is missing.

The contracts intentionally reject `inferred`, `derived`, and `normalized`
statuses. Ratios, units, chemical identities, comparators, and outcomes may not
be guessed. Later normalization or derivation must happen in a separate,
auditable transformation layer and must never overwrite reported values.

Run `python -m src.extraction.export_contract_schemas` to regenerate the
versioned JSON Schemas in `docs/extraction/schemas/v1`.
