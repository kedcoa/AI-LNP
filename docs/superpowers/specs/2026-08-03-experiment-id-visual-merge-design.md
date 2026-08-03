# Experiment-ID Visual Merge Design

## Decision summary

The NP-002 selective-vision calls accounted for all 18 requested outcome
slots, but the final benchmark scored only 42.9% overall recall and 0/18
complete arms. The immediate cause is not missing visual rows. The current
merge writes the paper map and the visual outcomes into one artifact without
reliably joining them into the same experiment-level records.

This change will give every visual candidate an immutable experiment ID before
the paid call. The model must echo the candidate/experiment pair unchanged.
The merger will then use that pair to combine verified paper-map metadata with
the visual outcome. It will no longer create unrelated `VIS::<slot>` experiment
identities or infer NP-002 context from figure numbers.

## Current problem

`merge_validated()` currently performs three separate actions:

1. It creates one new `VIS::<slot_id>` experiment for each visual outcome.
2. It supplies dose, model, route, organ, and timepoint through hard-coded
   Figure 2 and Figure 4 rules.
3. It embeds the complete paper-map object beside those visual experiments.

Embedding both sources is not a scientific join. Shared formulation facts can
exist in the paper map while the corresponding visual experiment remains
incomplete. The evaluator therefore sees 18 visual outcomes but cannot confirm
18 complete, correctly linked arms.

The current method is also paper-specific. Another paper's Figure 2 and Figure
4 will not necessarily use NP-002's doses, models, routes, or timepoints.

## Upstream inventory issue

The existing NP-002 paper map contains four provisional contexts, but the
paper reports six distinct experimental arms relevant to these visual tasks:

| Experiment ID | Formulation | Payload | Dose | Model | Visual outcomes |
|---|---|---|---:|---|---:|
| `EXP::NP002::QUANT::MC3::0.3` | MC3 | QUANT DNA | 0.3 mg/kg | C57BL/6J mice | 3 |
| `EXP::NP002::QUANT::cKKE12::0.3` | cKK-E12 | QUANT DNA | 0.3 mg/kg | C57BL/6J mice | 3 |
| `EXP::NP002::CRE::MC3::0.3` | MC3 | Cre mRNA | 0.3 mg/kg | Ai14 mice | 3 |
| `EXP::NP002::CRE::cKKE12::0.3` | cKK-E12 | Cre mRNA | 0.3 mg/kg | Ai14 mice | 3 |
| `EXP::NP002::CRE::MC3::1.0` | MC3 | Cre mRNA | 1.0 mg/kg | Ai14 mice | 3 |
| `EXP::NP002::CRE::cKKE12::1.0` | cKK-E12 | Cre mRNA | 1.0 mg/kg | Ai14 mice | 3 |

The current Figure 4 contexts compress `0.3 or 1.0 mg/kg` into records whose
stored numeric dose is 0.3. Joining visual candidates directly to those four
contexts would create complete-looking but incorrect 1.0 mg/kg records.

For this benchmark, the six-arm inventory will therefore be checked against
the source evidence before replay. This manual check validates the benchmark;
it is not production logic and must not consult frozen gold during execution.
The reusable code will require source-supported identity fields and will split
contexts when formulation, payload, dose, model, route, or timepoint changes.

## Proposed data contract

Every visual task slot will contain:

```json
{
  "candidate_id": "FIG4_KUP_CKKE12_10",
  "experiment_id": "EXP::NP002::CRE::cKKE12::1.0",
  "formulation": "cKK-E12",
  "dose": 1.0,
  "recipient_cell": "Kupffer cell",
  "allowed_evidence_ids": ["..."]
}
```

The structured response must return both `candidate_id` and `experiment_id`.
The model is not allowed to create, select, or modify experiment IDs.

The preflight manifest will preserve the complete immutable mapping:

```text
candidate_id -> experiment_id
```

Validation will reject unknown candidates, unknown experiments, missing IDs,
duplicate candidates, and candidate/experiment pairs that differ from the
preflight manifest.

## Deterministic merge

For each validated visual outcome, the merger will:

1. Resolve its candidate ID in the immutable preflight mapping.
2. Resolve that mapping's experiment ID in the verified experiment inventory.
3. Copy formulation, payload, dose, route, species, experimental model, organ,
   and timepoint from that experiment.
4. Add recipient cell, assay, endpoint, comparator, qualitative outcome, and
   significance from the validated visual row.
5. Preserve field-level evidence IDs from their actual source.
6. Quarantine a row if paper-map and visual values conflict on an identity
   field; never silently choose one.

Multiple visual candidates may point to the same experiment. This is required
because one formulation/dose/model arm can produce separate Kupffer-cell,
endothelial-cell, and hepatocyte outcomes.

## Why this should work

The pipeline has already shown that fixed candidate IDs plus exact accounting
can force complete structural coverage. This design applies the same mechanism
to scientific joining:

- the identity is issued before the model call;
- the model echoes it rather than inventing it;
- local code verifies exact equality;
- local code performs the final join deterministically.

The existing paid responses can be replayed locally, so the mechanism can be
tested without spending more tokens. The model remains responsible for reading
the figure and expressing the outcome, while deterministic code handles record
identity.

## Acceptance gates

The merge fix is validated only when all of the following hold:

- all six source-supported experimental arms exist in the inventory;
- all 18 visual candidates map to their predetermined experiment;
- no unknown, invented, or swapped experiment IDs are accepted;
- wrong-arm links equal zero;
- complete-arm recall is at least 80%;
- precision does not decrease from the current benchmark;
- the existing Figure 2 and Figure 4 responses replay without a paid call;
- production merge code contains no NP-002 Figure 2/Figure 4 context rules.

## Bounded failure policy

This is a time-boxed repair, not an open-ended extraction rewrite.

After the first local replay, one bounded debugging pass may correct a narrow
implementation defect such as an alias mismatch, missing field projection, or
incorrect local mapping. It must not add another LLM stage, a global registry,
or paper-specific scientific inference.

If recall remains below 80% after that pass:

1. Save the score and classify remaining failures as inventory, merge,
   normalization, evaluator, or genuinely missing evidence.
2. Preserve the best validated artifact without claiming the merger succeeded.
3. Stop work on NP-002 extraction recall for today.
4. Move to the fastest useful product path: ingest many papers, retain
   evidence-backed partial rows, build the database, and expose those records
   in a minimal UI.

The extraction pipeline does not need perfect recall before database and UI
work begins. Records must instead carry completeness and provenance fields so
downstream features can distinguish complete, partial, and quarantined rows.

## Next product step if the gate fails

The next implementation slice will be:

1. batch-ingest a bounded set of liver-focused papers;
2. run the existing paper-map and selective routes without gold-set tuning;
3. store accepted partial and complete records with provenance and quality
   status;
4. create the initial searchable database schema;
5. build a minimal UI for filtering formulations, payloads, models, target
   cells, and qualitative outcomes.

This preserves momentum toward the four-week product goal instead of making
perfect NP-002 recall a prerequisite for the database, UI, nearest-neighbor
work, or later COMET training.

## Out of scope

- A global ID-registry rewrite.
- New paid extraction calls during implementation.
- Gold-driven production mappings.
- Graph-derived numeric estimates.
- Reworking the paper-map prompt beyond what is required to expose distinct,
  source-supported experiment identities.
- Indefinite attempts to force NP-002 above the acceptance threshold.
