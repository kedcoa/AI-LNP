# Six-Call Codex Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one final six-call, filesystem-isolated Codex-plan benchmark that preserves complete experiment relationships and makes a definitive stop/continue decision.

**Architecture:** A one-off coherent-packet builder produces two sealed packets per paper from the saved clean replay. A macOS sandbox wrapper proves the repository is unreadable, then invokes the existing JSONL runner; the frozen validator and scorer evaluate results only after all calls finish.

**Tech Stack:** Python 3.14, pytest, Pydantic/JSON Schema, Codex CLI 0.146.x, macOS `sandbox-exec`, existing replay/validator/scorer.

## Global Constraints

- Exactly six Codex-plan calls: two per paper, concurrency two, no retry.
- Zero OpenAI API, Ollama, Gate A, Gate B, or vision calls.
- Cancel before hosted calls unless the scorer reproduces 40/62 and the OS isolation canary denies repository reads.
- Each experiment remains intact with candidate, arm, formulation, outcome, and evidence mappings.
- Codex may not use shell, file, or other tools; any such JSONL event invalidates the run.
- Gold/reference data is opened only after all six calls are terminal.
- Pass threshold is at least 45/62 with zero regressions and zero accepted unsupported facts/wrong relationships.
- Stop live execution after 20 minutes and stop this approach permanently if it misses threshold.
- Do not build production integration, deployment modes, database loading, or UI controls.

---

### Task 1: Prove isolation and build six coherent packets

**Files:**
- Create: `src/extraction/build_coherent_codex_audit.py`
- Create: `src/extraction/run_isolated_codex_audit.py`
- Test: `tests/test_coherent_codex_audit.py`
- Test: `tests/test_isolated_codex_audit.py`

**Interfaces:**
- Produces: `build_coherent_packets(paper: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]` returning exactly two packets.
- Produces: `build_sandbox_profile(isolated_root: Path, codex_binary: Path) -> str`.
- Produces: `prove_repository_denied(profile_path: Path, repository_root: Path) -> dict[str, Any]`.

- [ ] Write failing tests proving exactly two packets per paper, no split experiments, complete mappings, mapped unused evidence, allowed field registry, size bounds, and deterministic hashes.
- [ ] Write failing isolation tests proving the profile permits isolated packet reads but denies repository, benchmark, `.env`, and parent-directory reads.
- [ ] Implement the minimal coherent builder and isolated runner wrapper.
- [ ] Build all six saved-paper packets; freeze their hashes and prove the scorer independently reproduces 40/62.
- [ ] Run focused tests and commit. Abort the entire benchmark if any preflight fails.

### Task 2: Run six calls and make the decision

**Files:**
- Create or modify: `src/extraction/finalize_coherent_codex_audit.py`
- Test: `tests/test_finalize_coherent_codex_audit.py`
- Produce: `reports/extraction/codex_ollama_shadow/<run-id>/coherent-six/decision.md`
- Produce: `reports/extraction/codex_ollama_shadow/<run-id>/coherent-six/evaluation.json`

**Interfaces:**
- Consumes six sealed packets, isolated attempt records, frozen validator, and hidden scorer.
- Produces one terminal decision containing before/after requirement IDs, arm completion, safety counts, tokens, latency, and stop/continue recommendation.

- [ ] Write failing finalizer tests for six-terminal gating, tool-event invalidation, immutable merge, hidden-gold ordering, and exact pass thresholds.
- [ ] Run exactly six `codex exec` calls with concurrency two, no retries, and a 20-minute cutoff.
- [ ] Reject the complete run if any JSONL contains a tool/file/shell event or isolation proof changes.
- [ ] Validate proposals, merge into copies, load hidden gold, and score the unchanged baseline and audited copies against the same 62 requirements.
- [ ] Record exact tokens, latency, model telemetry, 40/62 before score, after score, requirement transitions, complete arms, and safety decisions.
- [ ] Run focused and provider-disabled regression tests. If the score is below 45/62 or any safety gate fails, record `stop_codex_auditor` and make no further calls.
