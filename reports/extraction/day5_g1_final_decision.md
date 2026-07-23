# Day 5 G1 final decision

**Decision: FAIL**

- Reviewed semantic precision: 69.0%
- Best-case overall precision: 82.4%
- Required precision: 90%
- Traceable abstract-evidence coverage: 100.0%
- Valid schema bundle rate: 6/9 (66.7%)
- Critical-field recall: not established

The best-case calculation assumes every automatically literal-supported field is correctly typed and linked. Even under that favorable assumption, precision remains below the gate. Abstract omissions are deferred to targeted full-text retrieval and are not counted as incorrect extractions.

## Required remediation

- Remove payload records from formulation components.
- Separate payload type, encoded product, formulation description, and lipid composition.
- Preserve reported recipient-cell text alongside controlled categories.
- Prevent disease or tissue sites from being stored as cell types.
- Create separate outcome records for distinct endpoints.
- Require the cited excerpt to directly support each accepted value.
- Replace or repair the unreliable model response path and rerun all gold papers.
