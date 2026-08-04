# Three-Paper Codex Audit Benchmark Design

## Objective

Determine whether a non-interactive `codex exec` auditor can improve the saved, post-merge extraction results for PILOT-001, PILOT-002, and PILOT-003 without seeing the gold standard and without making new Gate A, Gate B, selective-vision, Ollama, or OpenAI API extraction calls.

## Scope

Today's work is only the decision benchmark. It reconstructs clean post-merge inputs from saved artifacts, gives Codex bounded audit packets containing the merged record and its evidence, validates proposed corrections deterministically, and compares the corrected result with the hidden 62-requirement benchmark after Codex has finished.

Automatic invocation for future papers, generalized manifests, database integration, user controls, and deployment modes are explicitly deferred. If the benchmark succeeds, the final deliverable includes a separate implementation plan for generalization. If it fails, the final deliverable documents why and retains the current OpenAI v5.2 pipeline unchanged.

## Data Flow

1. Reconstruct each paper's pre-audit merged record from saved Gate A, Gate B, table, and selective-vision artifacts.
2. Build a complete evidence inventory and bounded audit packets. No reference answers, scores, or prior human-audit corrections enter model-readable files.
3. Run `codex exec --json` non-interactively with a strict output schema and capture model, token, timing, timeout, and error telemetry.
4. Accept only proposals whose evidence IDs, quoted support, numeric values, entity IDs, and relationships pass deterministic validation.
5. Merge accepted patches into a copy of the baseline; never modify accepted production artifacts.
6. After all model calls finish, score baseline and corrected results against the same hidden benchmark.

## Test Decision

- **Works:** no hard safety failure, no evidence-level regression from 57 full / 3 partial / 2 absent, automated score reaches at least 45/62 from 40/62, and at least two partial/absent requirements become fully supported or one absence plus five deterministic undercounts are recovered.
- **Promising but inconclusive:** no hard safety failure and at least one supported improvement, but the full success threshold is missed.
- **Does not work:** gold leakage, an accepted unsupported/invented fact, an accepted wrong relationship, three consecutive systemic CLI failures, or no supported improvement.

The classification is evidence for the next engineering decision; it does not automatically alter the production pipeline.

## Safety and Failure Handling

Codex receives read-only inputs and returns proposals only. Every proposal is validated locally. Unsupported or malformed output is rejected without changing the baseline. Each attempted packet receives a terminal status. A CLI failure preserves the raw attempt and the original merged record. The benchmark makes zero new OpenAI API extraction calls.

## Deliverables

- Reproducible gold-blind inputs for all three papers.
- Bounded audit packets and strict output schema.
- JSONL-aware Codex runner with measured usage and latency.
- Deterministic proposal validator and copy-only merger.
- Baseline-versus-audited hidden evaluation and a concise decision report.
- If successful or promising, a separate generalization plan; if unsuccessful, a failure analysis and recommendation to retain the existing OpenAI route.

## Estimate

The target is 3 to 4 hours 20 minutes. Estimated development usage is 60k–110k Codex tokens. Estimated hosted audit usage is 80k–160k tokens. New OpenAI API usage is zero.
