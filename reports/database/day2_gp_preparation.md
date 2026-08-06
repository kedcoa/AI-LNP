# Day 2 GP bundle preparation

**Prepared:** 2026-08-06. **Paid/API/LLM/network calls:** 0.

## Result

Six committed `accepted_graph.json` artifacts were converted to normalized,
round-trip-valid `ImportBundle` files. GP-001, GP-003, and GP-009 are
screening-only and the adapter rejects them before reading a graph. No arm is
marked eligible for nearest-neighbor or COMET training: accepted extraction is
not equivalent to human verification, and every arm still has at least one
missing or unresolved required field.

| Paper | Formulations | Components | Arms | Outcomes | Evidence excerpts | Review records | Plain review reasons |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| GP-002 | 1 | 4 | 6 | 6 | 40 | 6 | Missing dose; needs human verification |
| GP-004 | 1 | 4 | 4 | 8 | 44 | 4 | Missing dose; missing evidence excerpt |
| GP-005 | 5 | 4 | 3 | 5 | 32 | 3 | Missing dose; needs human verification |
| GP-006 | 1 | 1 | 1 | 5 | 17 | 1 | Missing dose |
| GP-007 | 1 | 3 | 4 | 5 | 24 | 7 | Missing dose; needs human verification; outcome link unclear |
| GP-008 | 4 | 0 | 1 | 7 | 29 | 1 | Needs human verification |

## Provenance and conservative decisions

- Each bundle stores the exact accepted-graph path and SHA-256, plus the graph
  contract version and every imported clause ID and quotation.
- Formulation/component/arm/outcome fields are populated only when an explicit
  graph entity and claim support the relationship. Numeric values are parsed
  only from explicitly numeric dose, timepoint, percent, or fold text.
- Multiple claims are retained as separate outcomes. Shared GP-007 outcome
  claims that lack an experiment assignment are retained as evidence plus
  `Outcome link unclear` review records; they are not attached to an arbitrary
  arm.
- Unsupported or not-yet-normalized relation types remain visible through the
  `Needs human verification` tag. Missing values are not imputed.
- Titles remain the paper IDs because the controlled local gold-source manifest
  contains PMID/PMCID/DOI but no title. Bibliographic identifiers are preserved
  from that manifest.

## Files

- Adapter: `src/database/adapters/accepted_graph.py`
- Bundles: `data/staging/database/day2_bundles/gp/GP-00{2,4,5,6,7,8}.json`
- Tests: `tests/test_accepted_graph_adapter.py`
