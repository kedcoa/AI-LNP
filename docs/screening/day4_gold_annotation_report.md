# Day 4 Gold Annotation Report

## Status

The Day 4 field-level gold package contains nine papers across hepatocyte,
Kupffer-cell, LSEC, and hepatic-stellate-cell screening strata. All expected
answers and evidence locations are frozen in `data/annotations/gold_v1/`.

The annotations are human-reviewed evaluation fixtures. They are not LLM
fine-tuning data, and paper inclusion does not imply compatibility with COMET.

## Required coverage

- Structured XML tables: GP-005, including LNP physicochemical tables.
- Image-based PDF table: GP-006, supplemental Tables S1 and S2.
- PDF figure: GP-008, supplemental cell-marker colocalization figure.
- Incomplete formulations: GP-004 and GP-007.
- Ambiguous chemistry: GP-008 has an unidentified base PEG-lipid and an
  unquantified DSPE-PEG-maleimide post-insertion step.
- Irrelevant keyword hits: GP-001 has an unsupported non-RNA payload; GP-003
  is a review; GP-009 uses HSC to mean hematopoietic stem cell.
- Endpoint ambiguity: GP-005 separates Kupffer-cell uptake from functional
  mRNA translation.
- Cell-role ambiguity: GP-008 separates the macrophage delivery recipient
  from the activated-HSC therapeutic target.

## Cell-role rule

`experiments.csv` preserves the original screening `cell_type` and adds:

- `delivery_recipient_cell`: the cell that receives or expresses the payload;
- `therapeutic_target_cell`: the cell affected downstream by the intervention.

An experiment may support HSC therapeutic-effect retrieval without supporting
HSC delivery retrieval. GP-008 is the frozen example of this distinction.

## Reproduction and validation

Run:

```bash
.venv/bin/python -m src.screening.complete_day4_gold_annotations
.venv/bin/python -m src.screening.validate_gold_annotations
.venv/bin/python -m pytest
```

The completion command is idempotent and preserves unrelated annotation rows.
