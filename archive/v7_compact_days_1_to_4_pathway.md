# Archived v7 compact extraction pathway: Days 1-4

## Archive status

This document consolidates the original Day 1 afternoon, Day 2 morning and
afternoon, Day 3 morning, and Day 4 morning and afternoon implementation notes.
It is retained for historical and implementation-traceability purposes.

Plan version: **v7**

Authoritative planning source:

```text
LNP_Liver_Tool_v7.pdf
Title: LNP Liver Tool - Cost-effective RAG and COMET Five-Week Continuation
Created: 2026-07-27
Week 1: Implement and validate compact OpenAI extraction
```

The PDF's Day 1-4 instructions match the pathway implemented by these archived
notes. The implementation later received outcome-completeness corrections, so
the current source of truth remains:

```text
README.md
docs/extraction/corrected_compact_workflow.md
docs/extraction/outcome_complexity_workflow.md
```

## Purpose of the v7 pathway

The v7 plan was designed to reduce API cost without giving up scientific
traceability. Local code performs document parsing, retrieval, deduplication,
evidence selection, validation, caching, and merging. The LLM receives a
smaller evidence packet and returns structured records that cite local evidence
IDs.

The intended routine path was:

```text
locally parsed paper
  -> field-aware retrieval
  -> deduplicated compact evidence packet
  -> one structured LLM extraction call
  -> deterministic validation
  -> accepted records
```

The exception path was:

```text
validation failure or unresolved evidence
  -> one bounded field-level repair
  -> one targeted table/figure page or crop when required
  -> human review for visual estimates or ambiguity
  -> deterministic merge and revalidation
```

## Day 1 - Freeze the compact extraction contract

### Contract and schema

The existing relational entities were preserved:

- papers;
- formulations;
- components;
- experiments;
- outcomes; and
- evidence.

The compact response retained the product-critical scientific fields:

- formulation name and composition;
- component identity, role, and amount;
- payload type, name, encoded product, and molecular target;
- delivery-recipient cell;
- therapeutic-target cell;
- tissue or organ;
- species and disease model;
- experimental context;
- dose, route, and timepoint; and
- assay, endpoint, comparator, and outcome.

Instead of repeating evidence quotations, every reported field cites one or
more evidence IDs from the local packet. Unsupported fields must be explicitly
marked missing.

### Prompt boundary

The prompt was shortened to critical scientific rules and prohibited the model
from:

- inferring hepatocytes from whole-liver evidence;
- mixing separate experiments;
- storing an RNA payload as an LNP component; and
- converting mechanisms or interpretations into measured outcomes.

Prompt, schema, route, and baseline were versioned independently.

Historical implementation versions:

```text
Prompt: compact-prompt-1.1.0
Response contract: compact-1.1.0
Route: compact-route-1.1.0
Evidence packet: compact-packet-1.0.0
Frozen comparison baseline: fulltext-rag-evidence-graph-v4
```

## Day 2 morning - Build the deduplicated evidence packet

The packet assembler reused field-aware retrieval for formulation, payload,
experiment boundaries, recipient cells, therapeutic targets, model context,
and outcomes.

It then:

1. split retrieved text into conservative evidence clauses;
2. deduplicated repeated chunk IDs, clause IDs, and normalized text;
3. retained all retrieval field tags on the single stored clause;
4. preserved section, subsection, page, XML element, table, figure, source
   path, and source type;
5. attached neighboring clauses only for continuations or unresolved
   references; and
6. assigned stable evidence IDs and a deterministic checksum.

Main implementation:

```text
src/rag/compact_packet.py
```

Historical output:

```text
data/staging/rag/compact_packets_v1/
```

## Day 2 afternoon - Build the compact API packet and evidence budget

The API-facing packet removed repeated provenance and stored source locations
once. Evidence clauses referenced shared source IDs and neighboring evidence
IDs.

The v7 implementation:

- prioritized direct formulation, experiment, and outcome evidence;
- placed background discussion last;
- applied a 16,000 estimated-token evidence budget;
- recorded selected and excluded clauses;
- recorded duplicate and exclusion reasons;
- estimated prompt, schema, packet, and total input size; and
- preserved frozen-gold evidence locations during the original budget review.

Main implementation:

```text
src/rag/compact_api_packet.py
```

Historical output:

```text
data/staging/rag/compact_api_packets_v1/
```

Later testing showed that preserving known gold locations was not sufficient to
guarantee complete outcome recovery. The current workflow therefore adds a
larger local outcome inventory and post-extraction coverage checks.

## Day 3 - One-call structured extraction

Each paper packet was sent through one structured-output request. The model was
asked to:

- determine eligibility;
- inventory relevant experiments;
- extract formulations and components;
- link formulations to experiments;
- extract biological context and outcomes;
- identify unresolved items; and
- return schema data without a narrative response.

The local runner joined evidence IDs back to stored evidence and applied
schema, relationship, unit, provenance, paper-ID, and evidence-ID validation.

Requests were cached using:

- paper checksum;
- packet checksum;
- prompt version;
- schema version; and
- model.

An identical completed request was not allowed to create another paid call.
Raw responses and candidates were saved before semantic validation so a local
validator failure would not automatically require another extraction.

Main implementation:

```text
src/extraction/run_compact_one_call.py
src/extraction/compact_validation.py
```

## Day 4 morning - Narrow field repair

Deterministic validation findings were converted into bounded repair tasks.
Each task contained only:

- the invalid record;
- the exact validation finding;
- cited evidence;
- a few field-matched passages; and
- the required schema fragment.

The repair response could change only the requested field and had to return a
corrected, missing, or ambiguous disposition. Repair requests were cached
independently from the main extraction.

Main implementation:

```text
src/extraction/build_repair_tasks.py
src/extraction/repair_contracts.py
src/extraction/run_narrow_repair.py
```

## Day 4 afternoon - Selective vision

Visual processing was triggered only when text processing identified one
unresolved table or figure and could resolve it to a specific source.

The targeted request contained:

- one relevant page or crop;
- its caption;
- referring Results passages;
- necessary Methods context; and
- the schema for the unresolved field.

The response had to distinguish:

- an exact printed value;
- a deterministically derived value;
- missing evidence;
- ambiguity; or
- a visually estimated result requiring human review.

The full PDF was not sent during routine selective vision.

Main implementation:

```text
src/extraction/identify_selective_vision_referrals.py
src/extraction/build_selective_vision_tasks.py
src/extraction/selective_vision_contracts.py
src/extraction/run_selective_vision.py
```

## Deterministic merge

Validated narrow-repair and selective-vision fragments were merged only when:

- the task matched the same paper and finding;
- the source candidate checksum matched;
- only the requested field changed;
- evidence IDs were valid;
- visual values were exact or derived rather than estimated;
- corrections did not collide; and
- the complete result passed validation again.

Main implementation:

```text
src/extraction/merge_compact_results.py
```

## Post-v7 completeness correction

The original v7 Day 1-4 path could validate records returned by the LLM but
could not prove that every expected outcome group had been returned. The later
corrected workflow added:

```text
full local evidence view
  -> pre-call complexity assessment
  -> local outcome candidate inventory for complex papers
  -> one-to-one post-call coverage check
  -> missing text-record or visual-record routing
  -> deterministic merge
  -> coverage recheck
```

These additions are implemented in:

```text
src/extraction/assess_outcome_complexity.py
src/extraction/build_full_outcome_inventory.py
src/extraction/build_outcome_candidates.py
src/extraction/consolidate_outcome_candidates.py
src/extraction/check_outcome_coverage.py
src/extraction/route_compact_findings.py
src/extraction/run_missing_record_repair.py
src/extraction/run_missing_record_vision.py
src/extraction/merge_missing_records.py
src/extraction/evaluate_final_gold_dynamic.py
```

The frozen current result is 10/15 final recovered outcomes. Candidate
detection and final recovery must not be treated as the same metric.

## Original notes consolidated here

The original files are retained beside this document under
`archive/v7_day1_to_day4_source_notes/`:

```text
day1_afternoon_compact_route.md
day2_morning_packet_review.md
day2_afternoon_packet_budget_review.md
day3_morning_main_call_review.md
day4_morning_narrow_repair.md
day4_afternoon_selective_vision.md
day4_merge.md
```

