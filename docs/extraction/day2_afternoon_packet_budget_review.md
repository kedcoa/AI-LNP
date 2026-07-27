# Week 1 Day 2 afternoon - evidence budget review

Status: **human approved on 2026-07-27**

## Implemented

`src/rag/compact_api_packet.py` converts each morning review packet into a
smaller API-facing packet while leaving both the frozen retrieval packets and
the morning packets unchanged.

The API packet:

- stores each source location once and refers to it by `source_id`;
- stores each evidence clause once and refers to neighboring context by
  `evidence_id`;
- uses `retrieval_field_tags` to make clear that tags are candidates supplied
  by retrieval, not proof of field support;
- retains only blocked field names for the future LLM call while keeping full
  gate diagnostics in the local manifest;
- prioritizes direct formulation, experiment, and outcome signals over
  background discussion;
- enforces a configurable, approved 16,000 estimated-token evidence-packet
  budget;
- logs every selected and excluded passage, its candidate fields, priority
  score, source IDs, exclusion reason, duplicate counts, and estimated tokens.

No OpenAI request was made.

## Token-estimation method

The extraction model has not been selected and `tiktoken` is not installed in
the project environment. The provisional deterministic estimate is:

`ceil(compact UTF-8 JSON bytes / 4)`

The manifest separately estimates the prompt, response schema, evidence
packet, and total request input. Day 3 must record the provider's actual token
usage once a model is selected.

## Generated outputs

Nine API packets and their detailed local manifests are in:

`data/staging/rag/compact_api_packets_v1/`

The readable cross-paper summary is:

`data/staging/rag/compact_api_packets_v1/manifest.md`

With the approved budget, each evidence packet is at or below 16,000
estimated tokens. Including the prompt and response schema, estimated total
input is approximately 17,723-17,768 tokens per paper.

Day 3 amendment: after explicit eligibility was added in compact contract
1.1.0, the refreshed estimates became 18,111-18,156 tokens per paper. Evidence
selection and the 16,000-token evidence budget did not change.

## Frozen-gold preservation

The frozen annotations contain 31 evidence locations:

- 29 were present in the original retrieval packets;
- all 29 remain available after deduplication;
- all 29 remain available after the approved evidence budget;
- zero locations were lost during deduplication;
- zero available locations were lost to the evidence budget.

`EVID-009` and `EVID-010` were absent before deduplication. They are visually
verified values in image-based GP-006 supplemental tables S1 and S2, so the
text packet assembler cannot recover them. They remain explicit unresolved
retrieval gaps for the later targeted-vision path.

## Human decisions

Approved on 2026-07-27:

1. Use a 16,000 estimated-token evidence-packet budget.
2. Use the deterministic tokenizer-free estimate for planning, with the
   selected provider's exact input counter and reported usage becoming
   authoritative when API execution is implemented.
3. Prioritize direct formulation, experiment, and outcome evidence; place
   background discussion last.
4. Leave the two image-table gold locations explicitly unresolved until the
   targeted-vision stage rather than inserting manually known answers into the
   LLM packet.
