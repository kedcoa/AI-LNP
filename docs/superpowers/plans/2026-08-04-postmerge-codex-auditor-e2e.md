# Three-Paper Codex Audit Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blindly test whether `codex exec` can safely improve the saved post-merge extraction for PILOT-001, PILOT-002, and PILOT-003, then produce the appropriate next plan without implementing premature deployment machinery.

**Architecture:** Reuse the existing shadow-benchmark harness, but replace its final-report-derived model inputs with provider-free replay from saved Gate A, Gate B, table, and selective-vision artifacts. Run bounded audit packets through `codex exec --json`, validate and merge proposals into a copy, and expose the hidden benchmark only to the local scorer after inference.

**Tech Stack:** Python 3.14, Pydantic v2, pytest, existing v5.2 parsers/validators/merger/evaluator, Codex CLI 0.146.x, JSON/JSONL artifacts.

## Global Constraints

- Make zero new Gate A, Gate B, selective-vision, Ollama, or OpenAI API extraction calls.
- Hosted `codex exec` calls for the three-paper audit are authorized.
- Never expose reference answers, reference bindings, benchmark scores, known-miss prose, or prior human-audit corrections to Codex.
- Do not pass `reports/extraction/application_pilot_final.json` wholesale to Codex.
- Codex proposes patches; deterministic validation decides acceptance.
- Never modify production extraction artifacts; merge into a run-scoped copy.
- An audit failure retains the original merged record.
- Record every attempted packet's final status, actual model, reported tokens, latency, timeout, and errors.
- Stop after one retry per packet, three consecutive systemic failures, or 120 minutes of live audit time.
- Do not implement future-paper manifests, database integration, UI controls, or deployment modes in this benchmark.

## Schedule and Token Budget

| Phase | Time | Development tokens | Hosted audit tokens | New OpenAI API tokens |
|---|---:|---:|---:|---:|
| Clean replay and gold isolation | 15–25 min | 10k–20k | 0 | 0 |
| Bounded packet construction | 25–35 min | 10k–20k | 0 | 0 |
| CLI telemetry and strict parsing | 25–35 min | 10k–20k | 0 | 0 |
| Live three-paper audit | 45–90 min | 5k–10k | 80k–160k | 0 |
| Validation, merge, and hidden scoring | 30–45 min | 15k–25k | 0 | 0 |
| Decision report and next plan | 20–30 min | 10k–15k | 0 | 0 |
| **Total** | **2 h 40 min–4 h 20 min** | **60k–110k** | **80k–160k** | **0** |

## File Map

- Modify `src/extraction/build_shadow_benchmark.py`: construct model inputs from clean replay rather than benchmark-enriched final reports.
- Modify `src/extraction/run_shadow_benchmark.py`: create bounded packets and capture Codex JSONL telemetry and usage.
- Modify `src/extraction/evaluate_shadow_benchmark.py`: validate proposals, score before/after, and emit the three-way test conclusion.
- Create `src/extraction/replay_shadow_baseline.py`: provider-free reconstruction and evidence inventory.
- Create `src/extraction/validate_shadow_audit.py`: deterministic evidence, numeric, ID, and relationship validation plus copy-only merge.
- Add focused tests under `tests/test_shadow_benchmark_*.py` and fixtures under `tests/fixtures/codex_ollama_shadow/`.
- Produce run artifacts under `data/staging/extraction/codex_ollama_shadow/<run-id>/` and reports under `reports/extraction/codex_ollama_shadow/<run-id>/`.

---

### Task 1: Reconstruct gold-blind post-merge inputs

**Files:**
- Create: `src/extraction/replay_shadow_baseline.py`
- Modify: `src/extraction/build_shadow_benchmark.py`
- Test: `tests/test_shadow_benchmark_replay.py`

**Interfaces:**
- Produces: `replay_pilot_paper(paper_id: str, artifact_root: Path) -> dict[str, Any]`.
- Produces: `build_evidence_inventory(replayed: dict[str, Any]) -> list[dict[str, Any]]`.
- Produces: `assert_gold_blind(payload: Mapping[str, Any]) -> None`.

- [ ] **Step 1: Write tests proving all three papers replay without provider clients, contain 14 total experiments, and reject forbidden reference/audit keys.**
- [ ] **Step 2: Run `.venv/bin/python -m pytest -q tests/test_shadow_benchmark_replay.py` and verify failure because replay is missing.**
- [ ] **Step 3: Implement minimal saved-artifact replay using existing parsers and `merge_full_paper_results`; final-report metadata may resolve paths but may not enter model payloads.**
- [ ] **Step 4: Deduplicate evidence IDs, reject conflicting duplicate text, preserve source/page/table/figure provenance, and mark evidence already used by merged records.**
- [ ] **Step 5: Run the focused tests and `tests/test_merge_full_paper_results.py`; commit the task.**

### Task 2: Build bounded audit packets

**Files:**
- Modify: `src/extraction/build_shadow_benchmark.py`
- Test: `tests/test_shadow_benchmark_packets.py`
- Create fixtures: `tests/fixtures/codex_ollama_shadow/audit_packets/`

**Interfaces:**
- Consumes: replayed record and complete evidence inventory from Task 1.
- Produces: `build_audit_packets(replayed: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write failing tests for shared-paper, per-experiment, unused-evidence, and final-consistency packets; require every packet to stay below 45,000 characters and 15 evidence items.**
- [ ] **Step 2: Verify the focused tests fail for missing packet construction.**
- [ ] **Step 3: Implement deterministic packet construction with paper-independent instructions, issued IDs, current merged facts, evidence excerpts, and explicit abstention.**
- [ ] **Step 4: Hash every packet and write a sealed manifest containing packet IDs and hashes but no gold paths.**
- [ ] **Step 5: Run focused tests and commit.**

### Task 3: Capture reliable `codex exec` output and usage

**Files:**
- Modify: `src/extraction/run_shadow_benchmark.py`
- Test: `tests/test_shadow_benchmark_runner.py`
- Add fixtures: `tests/fixtures/codex_ollama_shadow/codex_jsonl/`

**Interfaces:**
- Produces: `parse_codex_jsonl(lines: Iterable[str]) -> dict[str, Any]`.
- Produces: `run_codex_packet(packet_path: Path, output_schema: Path, timeout_seconds: int) -> dict[str, Any]`.

- [ ] **Step 1: Write failing tests for successful JSONL, malformed final output, timeout, nonzero exit, missing token telemetry, and one-retry accounting.**
- [ ] **Step 2: Verify tests fail because the existing runner captures only final stdout.**
- [ ] **Step 3: Invoke `codex exec --json --output-schema ... --output-last-message ...` in a packet-specific read-only working directory and persist raw JSONL unchanged.**
- [ ] **Step 4: Parse actual model, input/output/cached tokens when reported, latency, exit status, and terminal disposition; never fabricate zero usage when unavailable.**
- [ ] **Step 5: Implement one retry and the three-consecutive-systemic-failure circuit breaker; run focused tests and commit.**

### Task 4: Validate, merge, and score without leaking gold

**Files:**
- Create: `src/extraction/validate_shadow_audit.py`
- Modify: `src/extraction/evaluate_shadow_benchmark.py`
- Test: `tests/test_shadow_benchmark_validation.py`
- Test: `tests/test_shadow_benchmark_evaluation.py`

**Interfaces:**
- Produces: `validate_proposal(proposal: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any]`.
- Produces: `merge_validated_proposals(baseline: Mapping[str, Any], validations: Sequence[Mapping[str, Any]]) -> dict[str, Any]`.
- Produces: `classify_result(before: Mapping[str, Any], after: Mapping[str, Any], safety: Mapping[str, Any]) -> Literal["works", "promising_but_inconclusive", "does_not_work"]`.

- [ ] **Step 1: Write failing tests rejecting unknown evidence/record IDs, unsupported exact numbers, quote mismatches, cross-experiment evidence, wrong arm links, and malformed proposals.**
- [ ] **Step 2: Write failing merge tests proving the baseline is immutable and only accepted proposals appear in the audited copy with provenance.**
- [ ] **Step 3: Implement minimal validators and copy-only merge using existing v5.2 validators where available.**
- [ ] **Step 4: Write and implement hidden evaluation tests for the exact three-way thresholds in the approved design. Gold paths are provided only to the evaluator after inference.**
- [ ] **Step 5: Run focused tests plus the existing shadow evaluator tests and commit.**

### Task 5: Run the three-paper benchmark and issue the decision

**Files:**
- Produce: `reports/extraction/codex_ollama_shadow/<run-id>/audit_summary.json`
- Produce: `reports/extraction/codex_ollama_shadow/<run-id>/evaluation.json`
- Produce: `reports/extraction/codex_ollama_shadow/<run-id>/decision.md`
- Create only after scoring: `docs/superpowers/plans/2026-08-04-codex-auditor-generalization.md` or `reports/extraction/codex_ollama_shadow/<run-id>/failure_analysis.md`

**Interfaces:**
- Consumes the sealed packet manifest, validated proposals, audited copies, and hidden benchmark.
- Produces one evidence-backed conclusion and the next-step artifact appropriate to that conclusion.

- [ ] **Step 1: Run all focused tests and `git diff --check`; stop if gold isolation or deterministic validation fails.**
- [ ] **Step 2: Build a fresh run ID and verify the model-readable tree contains none of the forbidden gold/reference/audit markers.**
- [ ] **Step 3: Run the authorized three-paper `codex exec` audit with concurrency two, one retry maximum, and a 120-minute cutoff.**
- [ ] **Step 4: Validate and merge proposals locally, then invoke the hidden scorer only after all Codex attempts are terminal.**
- [ ] **Step 5: Report before/after 62-item coverage, full/partial/absent counts, complete arms, accepted/rejected patches, exact rejection reasons, actual tokens, latency, and safety violations.**
- [ ] **Step 6: If `works` or `promising_but_inconclusive`, write a separate generalization plan covering automatic invocation, manifests, database projection, failure behavior, and held-out validation. If `does_not_work`, write a failure analysis and retain the existing OpenAI route.**
- [ ] **Step 7: Run the complete provider-disabled pytest suite and record the exact result in `decision.md`.**

## Completion Boundary

Today is complete when the three-paper benchmark has a reproducible, gold-blind before/after result and an evidence-backed decision. Generalized pipeline integration is intentionally not part of this implementation; it becomes the next plan only if the benchmark supports further investment.
