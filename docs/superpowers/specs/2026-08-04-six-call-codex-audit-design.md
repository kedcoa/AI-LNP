# Six-Call Codex Audit Design

## Objective

Test whether preserving complete experiment–candidate–arm relationships materially improves the Codex auditor over the prior 28-fragment benchmark.

## Design

Build exactly two coherent packets per paper, six total. Every packet repeats a compact paper map and merged-paper summary, contains complete experiment groups with candidate and arm mappings, includes only evidence relevant to those groups, and includes mapped unused evidence that could expose omissions. No experiment may be split across packets.

Run each packet with `codex exec` using the authenticated Codex plan, never OpenAI API billing. Execute from a temporary non-repository root under a macOS `sandbox-exec` profile that denies access to the AI-LNP repository and other user files while allowing only the isolated input/output tree, required system/runtime paths, isolated Codex authentication state, and outbound network. A canary must prove repository reads fail before any hosted call. Any model tool/file/shell event invalidates the benchmark.

Freeze the validator and hidden scorer before inference. The scorer must reproduce the untouched 40/62 baseline. Codex outputs only evidence-backed proposals using issued IDs and an allowed field registry. Gold is loaded only after all six calls are terminal.

## Decision

Pass only at 45/62 or better, with no requirement regression, no accepted unsupported fact or wrong relationship, and no complete-arm regression. Otherwise stop Codex-auditor work and retain v5.2.

## Cutoff

Cancel before hosted calls if isolation, six-packet construction, frozen validation, or 40/62 scorer reproduction cannot be proven quickly. Maximum six calls, concurrency two, no retry, and 20-minute live-call cutoff. Total target: 30–45 minutes.
