# Week 1 Day 1 afternoon - compact extraction route

Status: **complete; route defined but not active**

## Versioned artifacts

- Prompt: `compact-prompt-1.1.0`
- Response contract: `compact-1.1.0`
- Route: `compact-route-1.1.0`
- Planned evidence packet: `compact-packet-1.0.0`
- Frozen comparison baseline: `fulltext-rag-evidence-graph-v4`

## Prompt boundary

The short prompt contains only scientific extraction rules. It does not repeat
the response schema or examples because the OpenAI Structured Outputs call will
derive the JSON Schema from `CompactExtractionResponse`.

The prompt explicitly prohibits:

1. inferring hepatocytes from liver-level evidence;
2. mixing facts from different experiments;
3. storing an RNA payload as an LNP component; and
4. converting a mechanism, hypothesis, or interpretation into a measured
   outcome.

It also requires evidence IDs for reported values, explicit `missing` values
when the packet is insufficient, and correct handling of reported negative
results.

The Day 3 pilot exposed that empty record lists could not distinguish an
ineligible paper from failed extraction. Version 1.1 therefore adds an
explicit evidence-grounded eligibility record and requires empty extraction
lists for ineligible or uncertain papers.

## Routing boundary

The compact route is intentionally inactive on Day 1. Day 2 will implement the
compact evidence-packet assembler, and Day 3 will implement the one-call API
runner. The existing evidence-graph v4 runner and contract are frozen by path
and checksum for later quality and cost comparison.

## Why

Separating prompt, response contract, packet version, and route version makes
cost and quality comparisons reproducible without changing the existing
baseline.
