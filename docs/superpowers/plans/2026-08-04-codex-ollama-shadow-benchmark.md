# Codex CLI and Ollama Shadow Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a read-only benchmark that independently decides whether Codex CLI is suitable for scientific auditing and whether Codex CLI with Ollama is safe enough for a later Gate B text shadow trial, retaining OpenAI whenever local extraction does not pass.

**Architecture:** A frozen case builder creates three paper-audit cases and twelve Gate B replay cases without gold labels. A subprocess adapter runs Codex CLI in an isolated read-only directory and normalizes every attempt into a strict result envelope. Existing extraction contracts validate Gate B output; a separate post-inference scorer loads 55 entity requirements plus seven arm judgments and emits independent auditor and extractor decisions.

**Tech Stack:** Python 3.14, Pydantic v2, pytest, Codex CLI 0.146.0-alpha.3.1, Ollama, existing AI-LNP v1.2 task and validation contracts.

## Global Constraints

- Make no paid OpenAI calls.
- Do not change accepted records, frozen inputs, production routing, Gate A, or selective vision.
- Gold labels may be loaded only after inference by the scorer; they must not enter prompts, request manifests, or model-readable run directories.
- Every issued attempt receives exactly one terminal disposition.
- Three consecutive systemic failures of the same class stop further inference and leave every unattempted case visible.
- Any extractor safety-gate failure produces `retain_openai`.
- Do not download or tune a local model within this plan.
- Preserve unrelated working-tree changes.

---

## File Map

- Create `src/extraction/shadow_benchmark_contracts.py`: strict case, attempt, score, gate, and decision models shared by the benchmark.
- Create `src/extraction/build_shadow_benchmark.py`: checksum-verified construction of three audit cases and twelve Gate B cases; no gold imports.
- Create `src/extraction/run_shadow_benchmark.py`: safe Codex CLI command construction, isolated subprocess execution, output parsing, append-only run artifacts, and early-stop accounting.
- Create `src/extraction/evaluate_shadow_benchmark.py`: post-inference 62-requirement construction, deterministic validation, scoring, safety gates, token/latency aggregation, and final decisions.
- Create `tests/fixtures/codex_ollama_shadow/arm_requirements.json`: the seven frozen application-critical arm definitions.
- Create `tests/fixtures/codex_ollama_shadow/fake_audit_response.json`: schema-valid auditor output used without inference.
- Create `tests/test_build_shadow_benchmark.py`: frozen inventory, checksum, and gold-separation tests.
- Create `tests/test_run_shadow_benchmark.py`: CLI command, terminal disposition, timeout, malformed output, append-only, and early-stop tests.
- Create `tests/test_evaluate_shadow_benchmark.py`: 62-item denominator, ID/evidence/numeric/arm safety, independent decision, and `retain_openai` tests.
- Create `reports/extraction/codex_ollama_shadow/2026-08-04-local-shadow/`: live benchmark manifest, attempts, evaluation, and decision report.

### Task 1: Strict benchmark contracts and frozen arm fixture

**Files:**
- Create: `src/extraction/shadow_benchmark_contracts.py`
- Create: `tests/fixtures/codex_ollama_shadow/arm_requirements.json`
- Create: `tests/test_build_shadow_benchmark.py`

**Interfaces:**
- Produces: `BenchmarkCase`, `AuditFinding`, `AuditResponse`, `AttemptResult`, `RequirementResult`, and `BenchmarkDecision` Pydantic models.
- Produces: `TerminalDisposition = Literal["accepted", "rejected_by_validation", "model_abstained", "schema_failure", "timeout_or_runtime_failure", "requires_human_review"]`.

- [ ] **Step 1: Write the failing contract and denominator tests**

```python
from pathlib import Path

from src.extraction.evaluate_shadow_benchmark import build_requirements
from src.extraction.shadow_benchmark_contracts import AttemptResult


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_application_requirement_denominator_is_62():
    requirements = build_requirements(
        ROOT / "data/annotations/gold_v1",
        ROOT / "tests/fixtures/codex_ollama_shadow/arm_requirements.json",
    )
    assert len(requirements) == 62
    assert {row.requirement_type for row in requirements} == {
        "component", "formulation", "experiment", "outcome", "arm"
    }


def test_attempt_rejects_unknown_terminal_disposition():
    payload = valid_attempt_payload()
    payload["terminal_disposition"] = "skipped"
    with pytest.raises(ValueError):
        AttemptResult.model_validate(payload)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_build_shadow_benchmark.py`

Expected: FAIL because the new modules do not exist.

- [ ] **Step 3: Add strict contracts**

Implement frozen `Literal` values, `extra="forbid"`, non-negative token and duration fields, SHA-256 string validation, unique finding IDs, and a model validator requiring exactly one terminal disposition per `AttemptResult`. Token counts are `int | None` and require `token_measurement_reason` when null.

- [ ] **Step 4: Add the seven arm requirements**

Write these exact definitions to the fixture:

```json
[
  {"requirement_id":"ARM-001","paper_id":"GP-004","experiment_id":"GX-001","required_outcome_ids":["GO-001","GO-002"]},
  {"requirement_id":"ARM-002","paper_id":"GP-006","experiment_id":"GX-002","required_outcome_ids":["GO-003","GO-004"]},
  {"requirement_id":"ARM-003","paper_id":"GP-006","experiment_id":"GX-003","required_outcome_ids":["GO-005","GO-006","GO-007"]},
  {"requirement_id":"ARM-004","paper_id":"GP-008","experiment_id":"GX-008","required_outcome_ids":["GO-015"]},
  {"requirement_id":"ARM-005","paper_id":"GP-008","experiment_id":"GX-008","required_outcome_ids":["GO-016"]},
  {"requirement_id":"ARM-006","paper_id":"GP-008","experiment_id":"GX-009","required_outcome_ids":["GO-017"]},
  {"requirement_id":"ARM-007","paper_id":"GP-008","experiment_id":"GX-009","required_outcome_ids":["GO-018"]}
]
```

- [ ] **Step 5: Run the contract tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_build_shadow_benchmark.py`

Expected: PASS for strict model and 62-item construction tests.

- [ ] **Step 6: Commit**

```bash
git add src/extraction/shadow_benchmark_contracts.py tests/fixtures/codex_ollama_shadow/arm_requirements.json tests/test_build_shadow_benchmark.py
git commit -m "test: define shadow benchmark contracts"
```

### Task 2: Gold-blind case construction

**Files:**
- Create: `src/extraction/build_shadow_benchmark.py`
- Modify: `tests/test_build_shadow_benchmark.py`

**Interfaces:**
- Consumes: `BenchmarkCase` from Task 1 and `MissingRecordTask` from `src.extraction.missing_record_contracts`.
- Produces: `build_audit_cases(root: Path) -> list[BenchmarkCase]`.
- Produces: `build_gate_b_cases(root: Path) -> list[BenchmarkCase]`.
- Produces: `write_case_manifest(cases: list[BenchmarkCase], destination: Path) -> Path`.

- [ ] **Step 1: Write failing inventory and leak tests**

```python
def test_builds_three_audit_and_twelve_gate_b_cases():
    assert [row.paper_id for row in build_audit_cases(ROOT)] == [
        "GP-004", "GP-006", "GP-008"
    ]
    gate_b = build_gate_b_cases(ROOT)
    assert len(gate_b) == 12
    assert Counter(row.paper_id for row in gate_b) == {
        "GP-004": 4, "GP-006": 4, "GP-008": 4
    }


def test_case_payloads_do_not_contain_gold_paths_or_ids():
    serialized = json.dumps(
        [row.model_dump(mode="json") for row in build_all_cases(ROOT)]
    ).lower()
    assert "data/annotations/gold_v1" not in serialized
    assert "gold_" not in serialized
    assert not re.search(r"\b(?:gf|gx|go|gc)-\d{3}\b", serialized)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_build_shadow_benchmark.py`

Expected: FAIL because the builder functions do not exist.

- [ ] **Step 3: Implement Gate B case construction**

Read the twelve files under `data/staging/extraction/v12_structural_primary_v6/<paper>/structural_repair_tasks/task_*.json`, validate each as `MissingRecordTask`, sort by `(paper_id, filename)`, compute source SHA-256, and embed only the model-safe task payload.

- [ ] **Step 4: Implement audit case construction**

For each pilot paper, include the accepted graph, structural coverage report, bounded task audit subset, and quarantined/conflict information when present. The prompt requests only structured findings with issued IDs, evidence IDs, severity, finding type, explanation, and suggested disposition. Do not include any file under `data/annotations/` or any evaluation report.

- [ ] **Step 5: Implement append-only manifest writing**

Refuse an existing destination, serialize canonical JSON, record source checksums and `paid_api_requests: 0`, and emit counts of three audit plus twelve Gate B cases.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_build_shadow_benchmark.py`

Expected: PASS with exactly 15 gold-blind cases.

- [ ] **Step 7: Commit**

```bash
git add src/extraction/build_shadow_benchmark.py tests/test_build_shadow_benchmark.py
git commit -m "feat: build gold-blind shadow cases"
```

### Task 3: Codex CLI adapter and complete attempt accounting

**Files:**
- Create: `src/extraction/run_shadow_benchmark.py`
- Create: `tests/fixtures/codex_ollama_shadow/fake_audit_response.json`
- Create: `tests/test_run_shadow_benchmark.py`

**Interfaces:**
- Consumes: `BenchmarkCase`, `AttemptResult`, and the `MissingRecordFragment` JSON schema.
- Produces: `codex_command(case: BenchmarkCase, *, backend: str, model: str, schema_path: Path, workdir: Path) -> list[str]`.
- Produces: `run_case(case: BenchmarkCase, *, backend: str, model: str, run_root: Path, timeout_seconds: int, runner: Callable = subprocess.run) -> AttemptResult`.
- Produces: `run_cases(cases: list[BenchmarkCase], ...) -> list[AttemptResult]`.

- [ ] **Step 1: Write failing command and disposition tests**

```python
def test_ollama_command_is_ephemeral_read_only_and_local(tmp_path):
    command = codex_command(case(), backend="ollama", model="qwen3:8b", schema_path=SCHEMA, workdir=tmp_path)
    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert ["--oss", "--local-provider", "ollama"] == command_slice(command)
    assert ["--sandbox", "read-only"] == sandbox_slice(command)


@pytest.mark.parametrize(
    ("returncode", "stdout", "timed_out", "expected"),
    [
        (0, valid_json(), False, "accepted"),
        (0, "not-json", False, "schema_failure"),
        (1, "", False, "timeout_or_runtime_failure"),
        (None, "", True, "timeout_or_runtime_failure"),
    ],
)
def test_every_issued_attempt_has_one_terminal_disposition(...):
    assert result.terminal_disposition == expected
```

- [ ] **Step 2: Run adapter tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_run_shadow_benchmark.py`

Expected: FAIL because the runner does not exist.

- [ ] **Step 3: Implement safe command construction**

Hosted audit command:

```python
["codex", "exec", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check", "--sandbox", "read-only", "--output-schema", str(schema_path), "-C", str(workdir), "-"]
```

Ollama extraction adds:

```python
["--oss", "--local-provider", "ollama", "--model", model]
```

The isolated work directory contains only the case payload and output schema. The prompt is passed on stdin. Do not use `--dangerously-bypass-approvals-and-sandbox`.

- [ ] **Step 4: Implement normalized execution and parsing**

Use `subprocess.run(..., input=prompt, text=True, capture_output=True, timeout=timeout_seconds, check=False)`. Classify timeout/nonzero exit, validate JSON with the task-specific Pydantic model, run `validate_response()` for Gate B, preserve stdout/stderr, and record null token counts with `token_measurement_reason="Codex CLI final output did not report usage"` when necessary.

- [ ] **Step 5: Implement append-only output and early stop**

Write each attempt under `<run-root>/attempts/<case-id>/`. Refuse overwrite. Stop after three consecutive `schema_failure` results or three consecutive `timeout_or_runtime_failure` results, and list remaining cases as unattempted in `run_manifest.json`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_run_shadow_benchmark.py`

Expected: PASS for all disposition and stop paths.

- [ ] **Step 7: Commit**

```bash
git add src/extraction/run_shadow_benchmark.py tests/fixtures/codex_ollama_shadow/fake_audit_response.json tests/test_run_shadow_benchmark.py
git commit -m "feat: run codex shadow attempts"
```

### Task 4: Deterministic scoring and independent decisions

**Files:**
- Create: `src/extraction/evaluate_shadow_benchmark.py`
- Create: `tests/test_evaluate_shadow_benchmark.py`

**Interfaces:**
- Consumes: frozen `gold_v1` CSVs, seven-arm fixture, `AttemptResult`, existing `validate_response`, and cached hosted results.
- Produces: `build_requirements(gold_root: Path, arm_fixture: Path) -> list[ApplicationRequirement]`.
- Produces: `evaluate_auditor(attempts, requirements) -> RouteEvaluation`.
- Produces: `evaluate_extractor(attempts, requirements, hosted_baseline) -> RouteEvaluation`.
- Produces: `decide(auditor: RouteEvaluation, extractor: RouteEvaluation) -> BenchmarkDecision`.

- [ ] **Step 1: Write failing denominator, safety, and independence tests**

```python
def test_requirement_types_total_62():
    counts = Counter(row.requirement_type for row in build_requirements(GOLD, ARMS))
    assert counts == {"component": 26, "formulation": 6, "experiment": 8, "outcome": 15, "arm": 7}


def test_wrong_arm_or_unsupported_number_forces_retain_openai():
    extractor = route_evaluation(wrong_arm_links=1, unsupported_exact_numbers=1, recall_ratio=1.0)
    decision = decide(passing_auditor(), extractor)
    assert decision.auditor_recommendation == "adopt_shadow_auditor"
    assert decision.extractor_recommendation == "retain_openai"


def test_missing_token_measurement_is_not_counted_as_zero():
    summary = aggregate_usage([attempt(input_tokens=None, output_tokens=None)])
    assert summary["known_input_tokens"] == 0
    assert summary["attempts_missing_token_measurement"] == 1
```

- [ ] **Step 2: Run scorer tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_evaluate_shadow_benchmark.py`

Expected: FAIL because scoring functions do not exist.

- [ ] **Step 3: Implement the reproducible 62-item requirement set**

Create one requirement for every row in `components.csv`, `formulations.csv`, `experiments.csv`, and `outcomes.csv`, preserving its gold primary ID and evidence ID. Add the seven arm requirements from the fixture. Assert the exact type counts and total; fail closed on duplicates or changes.

- [ ] **Step 4: Implement deterministic safety aggregation**

Count schema-invalid accepted outputs, invented IDs, unsupported exact numbers, wrong-arm links, missing candidate dispositions, attempt coverage, and production writes. Accepted Gate B results must already have passed `validate_response`; independently re-check each exact numeric field against cited task evidence text.

- [ ] **Step 5: Implement quality scoring**

Reuse the existing one-to-one outcome matching logic in `evaluate_final_gold_dynamic.py`. Score component, formulation, experiment, and audit finding matches with normalized identifiers plus evidence overlap. An arm is complete only when its experiment and every listed outcome requirement are fully recovered. The cached hosted baseline is scored on the same case set without a new call.

- [ ] **Step 6: Implement independent decisions**

Auditor passes at full recall >= 0.90, all frozen unsafe relationships flagged, and complete arms >= 5/7. Ollama passes only when every safety gate passes, recall >= 0.85 of cached hosted recall, and complete arms >= 5/7. Infrastructure failure yields `insufficient_evidence`; any completed unsafe or low-quality extraction yields `retain_openai`.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_evaluate_shadow_benchmark.py`

Expected: PASS for denominator, safety, usage, and independent decisions.

- [ ] **Step 8: Commit**

```bash
git add src/extraction/evaluate_shadow_benchmark.py tests/test_evaluate_shadow_benchmark.py
git commit -m "feat: score codex ollama shadow benchmark"
```

### Task 5: Local verification and live zero-paid-call benchmark

**Files:**
- Modify only if a verified defect is found: benchmark files from Tasks 1-4.
- Create at runtime: `reports/extraction/codex_ollama_shadow/2026-08-04-local-shadow/` and matching append-only staging artifacts.

**Interfaces:**
- Consumes: all prior task interfaces.
- Produces: `run_manifest.json`, `evaluation.json`, and `decision.json` for one timestamped run.

- [ ] **Step 1: Run the complete local test suite with credentials blanked**

Run: `OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q`

Expected: PASS; no paid provider client is constructed.

- [ ] **Step 2: Preflight Codex CLI and Ollama**

Run: `codex --version`

Run: `ollama --version`

Run: `ollama list`

Expected: Codex and Ollama clients are installed, the Ollama server is reachable, and at least one text-capable installed model is listed. Record exact versions and model digest. Do not pull a model.

- [ ] **Step 3: Build the immutable live case manifest**

Run: `.venv/bin/python -m src.extraction.build_shadow_benchmark --run-id 2026-08-04-local-shadow`

Expected: three audit cases, twelve Gate B cases, 15 unique case IDs, source checksums, and `paid_api_requests: 0`.

- [ ] **Step 4: Run the Codex CLI auditor**

Run: `.venv/bin/python -m src.extraction.run_shadow_benchmark --run-id 2026-08-04-local-shadow --route audit --backend codex --timeout-seconds 300`

Expected: three terminal attempt dispositions and no production writes. Hosted plan usage may be consumed, but no OpenAI API key or paid API client is used.

- [ ] **Step 5: Run Ollama Gate B replay**

Run: `.venv/bin/python -m src.extraction.run_shadow_benchmark --run-id 2026-08-04-local-shadow --route gate-b --backend ollama --model auto-installed --timeout-seconds 300`

Expected: the runner selects the first installed text model in the fixed preference order `qwen3:8b`, `qwen3:4b`, `gemma3:12b`, `gemma3:4b`, then lexicographic installed-name order; it records the exact selected tag and digest, produces up to twelve terminal attempt dispositions, and stops early after three consecutive failures of one systemic class.

- [ ] **Step 6: Evaluate and write the decisions**

Run: `.venv/bin/python -m src.extraction.evaluate_shadow_benchmark --run-id 2026-08-04-local-shadow`

Expected: separate `auditor_recommendation` and `extractor_recommendation`, all denominators and safety findings, known token totals plus missing-measurement counts, latency, and `paid_api_requests: 0`.

- [ ] **Step 7: Re-run focused and full tests after any fixes**

Run: `.venv/bin/python -m pytest -q tests/test_build_shadow_benchmark.py tests/test_run_shadow_benchmark.py tests/test_evaluate_shadow_benchmark.py`

Run: `OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q`

Expected: PASS.

- [ ] **Step 8: Commit the verified harness, not volatile run data**

```bash
git add src/extraction/shadow_benchmark_contracts.py src/extraction/build_shadow_benchmark.py src/extraction/run_shadow_benchmark.py src/extraction/evaluate_shadow_benchmark.py tests/test_build_shadow_benchmark.py tests/test_run_shadow_benchmark.py tests/test_evaluate_shadow_benchmark.py tests/fixtures/codex_ollama_shadow
git commit -m "feat: benchmark codex ollama shadow routes"
```

### Task 6: End-of-day decision and next-phase handoff

**Files:**
- Create: `reports/extraction/codex_ollama_shadow/2026-08-04-local-shadow/summary.md`
- Modify: `docs/extraction/v12_recall_workflow.md`

**Interfaces:**
- Consumes: verified live `decision.json`.
- Produces: a concise evidence-backed go/no-go record and the operational next step.

- [ ] **Step 1: Write the decision summary from measured results**

Include versions, installed model, case counts, every safety gate, 62-item recall, complete arms, cached hosted comparison, known/missing token measurements, latency, early-stop status, and the two independent recommendations.

- [ ] **Step 2: Document the production rule**

If local extraction does not pass, state: `Retain OpenAI for Gate B; do not spend additional time tuning Ollama today.` If the auditor passes, state that it is eligible only for non-destructive shadow auditing. If Ollama passes, state that it is eligible only for a larger low-risk text shadow trial.

- [ ] **Step 3: Document the handoff**

Add the benchmark result to `docs/extraction/v12_recall_workflow.md`, then explicitly release paper discovery, database loading, and UI work from this investigation.

- [ ] **Step 4: Verify documentation and repository state**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors; unrelated pre-existing changes remain untouched.

- [ ] **Step 5: Commit**

```bash
git add docs/extraction/v12_recall_workflow.md reports/extraction/codex_ollama_shadow/2026-08-04-local-shadow/summary.md
git commit -m "docs: record shadow benchmark decision"
```
