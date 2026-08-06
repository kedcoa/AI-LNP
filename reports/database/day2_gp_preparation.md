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
| GP-002 | 1 | 4 | 6 | 6 | 62 | 7 | Missing dose; needs human verification |
| GP-004 | 1 | 4 | 3 | 7 | 49 | 5 | Experiment link unclear; missing dose; missing evidence excerpt; needs human verification |
| GP-005 | 5 | 4 | 4 | 4 | 40 | 7 | Experiment link unclear; missing dose; missing evidence excerpt; needs human verification |
| GP-006 | 1 | 1 | 1 | 5 | 17 | 1 | Missing dose |
| GP-007 | 1 | 3 | 1 | 7 | 30 | 5 | Experiment link unclear; needs human verification |
| GP-008 | 4 | 0 | 3 | 2 | 30 | 4 | Experiment link unclear; missing dose |

## Provenance and conservative decisions

- Each bundle stores the exact accepted-graph path and SHA-256, plus the graph
  contract version and every imported clause ID and quotation.
- Formulation/component/arm/outcome fields are populated only when an explicit
  graph entity and claim support the relationship. Numeric values are parsed
  only from explicitly numeric dose, timepoint, percent, or fold text.
- One experiment may produce multiple arms when its accepted graph explicitly
  relates multiple formulations. GP-005 therefore preserves LNP1, LNP16,
  LNP17, and LNP3–LNP7 as distinct arms. GP-008 preserves F1, F4, and F5;
  unused F2 is not invented as an arm.
- `shared_claim_ids` are evaluated per experiment. This preserves the shared
  GP-002 payload and assigns GP-007 shared outcomes to E04 because E04 lists
  those claim IDs. Evidence without an explicit formulation relationship stays
  unassigned and visible as `Experiment link unclear` rather than being attached
  to the first formulation.
- Unsupported or not-yet-normalized relation types and their exact excerpts
  remain visible through review records. Missing values are not imputed.
- Numeric dose values are stored only with a parsed unit; `microgram(s)` is
  recognized in addition to symbol and abbreviated forms.
- Context ownership follows explicit, directional graph chains. For example,
  GP-005 links LNP1 administration to the C57BL/6J model and then to *Mus
  musculus*, so species/model/liver context belongs to LNP1. It is not copied
  to the separately linked LNP16 or LNP17 arms.
- Titles remain the paper IDs because the controlled local gold-source manifest
  contains PMID/PMCID/DOI but no title. Bibliographic identifiers are preserved
  from that manifest.

## Files

- Adapter: `src/database/adapters/accepted_graph.py`
- Bundles: `data/staging/database/day2_bundles/gp/GP-00{2,4,5,6,7,8}.json`
- Tests: `tests/test_accepted_graph_adapter.py`
