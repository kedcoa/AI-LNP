# Codex–Ollama shadow benchmark summary

Run ID: `2026-08-04-local-shadow-v2`

## Decision

- Keep OpenAI as the production Gate B extraction provider.
- Do not adopt Codex CLI as the audit gate yet. The integration harness works,
  but the hosted audit did not produce a terminal response within the
  five-minute per-case timebox, so today's run does not establish audit quality.
- Proceed with paper discovery, database construction, and UI work without
  waiting for either candidate.

## Benchmark basis

The shadow run used the authoritative v5.2 application pilot: 62 required facts
across three papers and seven experimental arms. The cached hosted baseline is
40/62 evidence-grounded facts (64.5% recall), with five of seven scientifically
complete arms. Its prior provider-free replay reports 293,531 cumulative hosted
tokens: 95,012 for Gate A, 163,087 for initial Gate B, and 35,432 for retry.

The audit route received the merged extraction and validation artifacts but not
the benchmark references. The local route received the same 14 saved text Gate B
requests used by the v5.2 pilot. Both routes wrote only to isolated benchmark
directories.

## Observed results

| Route | Candidate | Terminal results | Duration | Operational result |
|---|---|---:|---:|---|
| Audit | Codex CLI hosted default | 1 timeout; 2 cases not completed | 300.0 s measured | Insufficient evidence; do not adopt today |
| Gate B | `qwen3-vl:8b-instruct` (`0533d74300e4`) through Codex CLI/Ollama | 3/3 schema failures; 11 cases stopped by the planned failure circuit breaker | 308.1 s | Retain OpenAI |

The three local failures were malformed JSON: two invalid control characters
and one missing JSON value. No output passed schema validation, so no local
response was eligible for scientific scoring or merging. The reported 0/62 is
therefore a zero-accepted-output result, not an estimate of the model's latent
scientific recall.

## Usage and safety

- Paid API requests: **0**
- OpenAI API tokens used by this live shadow run: **0**
- Hosted Codex and local Ollama token counts: unavailable because the CLI did
  not return usage for the timed-out or schema-failed attempts; these are
  recorded as unmeasured, not as zero.
- Production writes: **0**
- Every terminal attempt was captured with timestamps, hashes, stdout/stderr,
  disposition, and validation issues. This is the meaning of 100% failures
  recorded: complete failure telemetry, not a 100% target failure rate.

## Next action

Use the existing OpenAI path for new-paper extraction. Codex can remain a
non-blocking audit experiment only after reducing the audit payload or splitting
the audit into smaller bounded cases and demonstrating three clean terminal
responses inside the timebox. The current local 8B model should not receive more
today-timebox work unless its structured-output behavior is changed and first
passes a small schema smoke test.
