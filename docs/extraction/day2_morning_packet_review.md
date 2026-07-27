# Week 1 Day 2 morning - compact packet human review

Status: **human approved on 2026-07-27**

## Completed morning work

The assembler in `src/rag/compact_packet.py`:

- reuses the existing field-aware retrieval packet for each paper;
- merges passages retrieved for formulation, payload, experiment boundary,
  recipient cell, therapeutic target, and outcomes;
- deduplicates repeated hits by chunk ID, clause ID, and normalized text;
- retains every retrieval field tag when text is stored once;
- preserves section, subsection, page, XML element, table, figure, source type,
  and source path;
- adds previous or next clause context only for anaphoric or continuation
  clauses;
- attaches a human-reviewed experiment candidate only when its exact anchor
  quote occurs in the evidence clause;
- assigns stable evidence IDs and a deterministic packet checksum.

Nine packets were generated in `data/staging/rag/compact_packets_v1/`.

## Representative packet

Review `data/staging/rag/compact_packets_v1/GP-002.json`.

Its morning deduplication result is:

- retrieval hits: 60
- unique chunks: 29
- duplicate chunk hits removed: 31
- input clauses: 194
- unique evidence items: 181
- blocked fields: none

Two clauses match the human-reviewed experiment anchors:

- one shared by experiment candidates `GP-002-E01` through `GP-002-E04`;
- one shared by experiment candidates `GP-002-E05` and `GP-002-E06`.

## Human decisions requested

Approved:

1. Sentence/clause-level evidence is the desired unit rather than whole
   retrieved paragraphs.
2. `field_tags` are understood as retrieval-selection metadata, not proof that
   every individual clause supports every tag. The API-facing packet therefore
   names this property `retrieval_field_tags`.
3. Exact-anchor-only experiment candidate assignment is appropriately
   conservative.
4. Selective neighboring context is acceptable. The implemented rule retains
   explicit references, continuation punctuation, shared experiment or
   formulation identifiers, and strongly shared scientific wording.

5. Packets retain original retrieval gate failures and their diagnostic
   messages locally. The API-facing packet sends only the blocked field names.

## Deferred to Day 2 afternoon

The clause-level files are currently larger on disk than the original
paragraph-level retrieval packets because they repeat validation metadata.
Day 2 afternoon will add token counting, debug logs, duplicate/exclusion
reports, and a compact API serialization that references shared provenance
instead of repeating it.
