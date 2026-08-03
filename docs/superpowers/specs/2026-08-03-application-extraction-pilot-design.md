# Application Extraction Pilot: Human-Readable Design

## Where the pipeline stands

The NP-002 work proved the central extraction route is viable:

- the model recovered the important experiment setup fields;
- selective vision recovered the liver-cell findings;
- fixed experiment IDs prevented outcomes from being attached to the wrong arm;
- the merged result had zero wrong-arm links;
- the low `62.4%` score was partly a scoring and representation problem, not a
  claim that only 62.4% of the useful application data was recovered.

The remaining problem is that equivalent scientific facts are represented in
different forms. For example, the extraction may preserve the exact component
ratio while the evaluator expects a differently formatted version, or the
model may return a specific qualitative comparison while the answer key uses a
broader phrase. The current evaluator can mark those as missing even though the
underlying information is present.

## What will change

### 1. Preserve both the source wording and a safe canonical value

Every important fact will keep:

- `raw_value`: exactly what the paper or model said;
- `canonical_value`: a conservative standardized form used for matching;
- `evidence_ids`: the source passages, table cells, captions, or figures;
- `provenance`: whether the fact came from text, a table, a printed figure
  label, or an unsupported graph estimate.

Canonicalization will handle safe differences such as capitalization,
spacing, recognized aliases, and ratio formatting. It will not use fuzzy
matching to turn scientifically different facts into matches.

### 2. Store outcomes as small scientific assertions

One large `qualitative_outcome` sentence is too difficult to compare reliably.
Each experiment will instead retain separate assertions:

- foundational outcome: what delivery or expression occurred;
- comparative outcome: which arm was higher, lower, similar, or not
  significantly different;
- exact measurement: a number printed in text, a table, or a figure label;
- raw finding text and significance statement.

Numbers estimated from bar heights will not be treated as exact. For the first
pilot they will be stored only as `graph_estimated` metadata or omitted from
the application score.

### 3. Generalize the experiment-ID merge

The successful NP-002 rule will become paper-independent:

1. local code assigns each candidate a stable experiment ID before the paid
   extraction call;
2. every text or visual task carries that ID;
3. the model must echo the same ID;
4. local validation rejects invented or changed IDs;
5. shared paper facts and experiment-specific outcomes join only through the
   validated ID;
6. conflicting results are quarantined instead of silently overwriting one
   another.

This improves the join. It does not guarantee that the upstream experiment
inventory is scientifically correct, so the pilot includes a lightweight
inventory sanity check before any downstream calls.

### 4. Score what the application actually needs

The new evaluator will report separate recall for:

- formulation identity, components, ratios, and ratio basis;
- payload, dose, and administration route;
- species, model or disease context, tissue, and recipient cell;
- assay and endpoint;
- foundational and comparative outcomes;
- exact numerical outcomes only when the paper explicitly reports them;
- evidence provenance and arm linkage.

It will also keep strict safety counts: wrong-arm links, invented IDs, and
unsupported exact numbers must all remain zero.

## What will not change

- Existing ingestion, Docling/table handling, selective vision, evidence
  envelopes, candidate accounting, and token packing will be reused.
- The model will not receive an answer key.
- Generic production modules will not contain NP-002, KUP, fixed-six, or other
  paper-specific rules.
- The pipeline will not estimate exact values from unlabeled graph bars.
- This milestone will produce database-ready records, but will not expand into
  the final database loader, nearest-neighbor model, COMET training, or UI.
  Those begin after the extraction pilot is accepted.

## The three-paper uninterrupted pilot

Three new, open-full-text, liver-focused LNP papers will be selected. Together
they should exercise text, tables, and figures. They must not be existing gold
papers.

Each paper will follow the same route:

1. ingest the complete paper;
2. build and inspect the local evidence inventory;
3. run the shared paper-map extraction;
4. create stable experiment IDs and context tasks;
5. run text extraction and selective vision only where required;
6. validate every returned ID and evidence citation;
7. merge shared and experiment-level facts;
8. score application-required information against a separate, human-audited
   reference that was never included in the prompts.

There are two necessary paid-call approval gates. Context and vision requests
cannot be frozen until the paper-map outputs exist:

- Gate A shows the exact three paper-map calls, hashes, and token estimates.
- Gate B shows every exact downstream text/vision call, hash, and token
  estimate after the maps have been validated.

After Gate B approval, all frozen downstream calls run sequentially without
human review, retry, repair, or interruption. A failed call is recorded and
the runner continues to the next approved call.

## Success bar

The pilot is accepted when the aggregate result reaches:

- at least 90% core experiment-setup recall;
- at least 90% formulation component/ratio recall;
- at least 80% qualitative outcome recall;
- at least 80% exact-numeric recall where exact numbers truly exist;
- at least 80% overall required-information recall;
- zero wrong-arm links;
- zero invented IDs;
- zero unsupported exact numerical values.

Scores will also be shown per paper so one easy paper cannot hide a failure on
another.

## Fastest realistic timeline

- canonical values and atomic outcomes: 1.5–2 hours;
- generic experiment-ID merge: 1.5–2.5 hours;
- application-focused evaluator and batch controls: 1–1.5 hours;
- select, ingest, and sanity-check three papers: 1–2 hours;
- prepare and run calls after approval: 1–3 hours;
- final merged report: 0.5–1 hour.

The first paper-map approval package should be reachable after roughly 4–6
focused hours. A complete three-paper result is a same-day or next-working-day
target, depending mainly on provider latency and the number of figures.

## Decision after the pilot

- If the thresholds pass, freeze this extraction version and move immediately
  to multi-paper database loading and the first UI.
- If recall is slightly below target because of small normalization or evidence
  routing defects, make one bounded local correction and replay saved responses
  before considering another paid call.
- If the same fundamental failure remains, stop extending this paper-specific
  benchmark. Preserve confidence/provenance flags, begin extracting many
  sources, build the database and UI, and surface uncertain rows for later
  review rather than spending the remaining project time on another major
  extraction redesign.
