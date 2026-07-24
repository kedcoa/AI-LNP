# Day 7 morning: G1 error analysis

- Exact outcome recall: **6/15 (40.0%)**
- Missing outcomes with evidence already retrieved: **9/9**
- Extraction recall conditional on retrieved outcome evidence: **40.0%**
- Independent retrieval recall@6: **31/31 (100.0%)**
- Post-review critical-field precision: **100%**

## Error classes

- experiment_boundary_error: **4**
- human_gold_disagreement: **1**
- incomplete_evidence: **1**
- normalization_error: **1**
- wrong_relation: **2**

## Outcome-level audit

| Outcome | Paper | Retrieval | Primary class | Explanation |
|---|---|---:|---|---|
| GO-001 | GP-004 | hit | experiment_boundary_error | Evidence was retrieved, but the GP-004 Kupffer/CD11b reporter experiment was omitted. |
| GO-002 | GP-004 | hit | experiment_boundary_error | Evidence was retrieved, but the GP-004 F4/80-positive qualitative result was omitted with its experiment. |
| GO-003 | GP-006 | hit | experiment_boundary_error | Evidence was retrieved, but GP-006 retained only the Cas9/sgRNA experiment and omitted reporter delivery. |
| GO-004 | GP-006 | hit | experiment_boundary_error | Evidence was retrieved, but the hepatocyte-to-LSEC reporter comparison was omitted with the reporter experiment. |
| GO-006 | GP-006 | hit | incomplete_evidence | The supplement page was retrieved and deletion frequency was retained, but the insertion-frequency table value was omitted. |
| GO-011 | GP-005 | hit | normalization_error | The graph retained low Kupffer translation but did not preserve the frozen exact negative result of no obvious EGFP-positive Kupffer cells. |
| GO-013 | GP-007 | hit | wrong_relation | GP-007 retained improvement values without a complete intervention-to-endpoint relation for the frozen LSEC protection outcome. |
| GO-017 | GP-008 | hit | wrong_relation | GP-008 retained the therapeutic-target-cell link but not the macrophage-mediated activated-HSC elimination outcome. |
| GO-018 | GP-008 | hit | human_gold_disagreement | The frozen page was 18, but the extracted PDF places Appendix Figure 5 panels G-L and marker labels on page 19. |

> Retrieval recall, conditional extraction recall, and post-review precision are separate metrics and must not be substituted for one another.
