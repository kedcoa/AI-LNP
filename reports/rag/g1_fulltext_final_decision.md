# Final full-text RAG G1 result

- Final human-adjudicated precision: **100.0%** (115/115)
- Required precision: **90.0%**
- Traceable evidence coverage: **100.0%**
- Negative-control false-positive papers: **0/3**
- Exact frozen-gold outcome recall: **40.0%** (6/15)

## Decision

**The G1 precision gate passes, with recall remediation required.**

The precision is for the final human-adjudicated graphs after corrections, not the raw first-pass model output. Low exact outcome recall means Day 7 must recover omitted gold outcomes before the records are curated for training.

## Negative controls

- **GP-001:** Cantharidin is a small-molecule payload outside the configured RNA-LNP scope.
- **GP-003:** The paper is a review and contains no eligible original LNP experiments.
- **GP-009:** Its extracted LNP experiments target lung endothelial cells, CD4 T cells, or hematopoietic stem cells; HSC does not mean hepatic stellate cell in this paper.

## Missing frozen-gold outcomes

GO-001, GO-002, GO-003, GO-004, GO-006, GO-011, GO-013, GO-017, GO-018
