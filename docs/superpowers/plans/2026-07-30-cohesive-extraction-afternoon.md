# Cohesive Extraction Afternoon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unsafe Strategy 1 approval snapshot with one resumable end-to-end route whose paid execution is bound to reviewed bytes and whose merge accounts for every prepared candidate across text, vision, and human-review scopes.

**Architecture:** Keep the existing candidate, vision, coverage, runner, and merge implementations, but bind them with signed scope and approval artifacts. The task builder will treat experiment association as a retrieval hint and permit bounded semantic classification; the runners will send only exact preflighted request files after explicit confirmation; the merge will validate against the complete signed paper scope. A thin coordinator will order these existing stages without duplicating their scientific logic.

**Tech Stack:** Python 3.14, Pydantic v2, OpenAI Responses API, pytest, SHA-256 checksums, existing AI-LNP v1.2 compact extraction and structural-coverage modules.

## Global Constraints

- Continue from local Strategy 1 branch `codex/cohesive-morning`; do not push.
- Use no CodeRabbit or other paid review service. Use independent Codex review subagents only.
- Every production change follows TDD; every failure follows `superpowers:systematic-debugging`.
- Every task receives independent spec/quality review; the final branch receives a fresh whole-change review.
- No paid or provider call may occur during implementation, testing, regeneration, or review.
- Every paid call requires `confirm_paid_call=True`, an exact approved request file, its expected SHA-256, and a signed preflight manifest that contains that path/hash.
- The provider receives the parsed exact approved request dictionary; the runner must not rebuild a semantically equivalent request at execution time.
- Each request has estimated input `<= 6_000` tokens and `max_output_tokens == 4_000`.
- Candidate IDs, facts, evidence, every plausible compact experiment summary, and explicit resolution semantics remain in every request.
- Association is diagnostic context only. It must not force `permitted_new_experiments=0`; each repair task may permit at most one bounded new experiment.
- Text and visual candidates remain disjoint. Unsigned or ambiguous visual provenance remains explicit human review.
- The complete signed paper scope includes paid task candidates, oversized candidates, visual-human-review candidates, existing human-review candidates, contradicted candidates, and locally confirmed candidates.
- Merge finalization requires a disposition for the complete expected scope and is false whenever any expected candidate remains missing, unresolved, contradicted, invalid, or quarantined.
- Development success remains verified 13/15–15/15 recall, precision `>= 0.9`, zero unsupported accepted outcomes, and zero wrong experiment links.
- After development success, retrieve one new PubMed/Europe PMC paper absent from the gold set and current corpus, then run the unchanged successful route with separate paid approvals.

---

### Task 1: Bind Provider Execution to Exact Human-Approved Request Bytes

**Files:**
- Modify: `src/extraction/preflight_missing_record_repairs.py`
- Modify: `src/extraction/run_missing_record_repair.py`
- Modify: `src/extraction/run_missing_record_vision.py`
- Modify: `tests/test_preflight_missing_record_repairs.py`
- Modify: `tests/test_missing_record_workflow.py`
- Modify: `tests/test_missing_record_vision.py`

**Interfaces:**
- Produces: signed preflight manifest version `missing-record-request-preflight-1.2.0` with `manifest_checksum`.
- Produces: `load_approved_request(path: Path, *, expected_sha256: str, manifest_path: Path) -> dict[str, Any]`.
- Changes text and vision `run()` to require keyword-only `approved_request_path: Path`, `approved_request_sha256: str`, and `confirm_paid_call: bool`.
- Cache identity consumes the exact approved request SHA-256, including the 4,000 output limit.

- [ ] **Step 1: Write failing provider-boundary tests**

Add tests proving:

```python
def test_callable_runner_refuses_before_provider_use_without_confirmation(tmp_path):
    client = ExplodingClient()
    with pytest.raises(PermissionError, match="confirm_paid_call"):
        run(
            _v12_task(),
            client=client,
            approved_request_path=tmp_path / "request.json",
            approved_request_sha256="0" * 64,
            confirm_paid_call=False,
            output_root=tmp_path / "runs",
        )
    assert client.calls == 0


def test_runner_rejects_request_bytes_not_listed_in_signed_manifest(tmp_path):
    approved = _write_signed_preflight(tmp_path)
    approved.request_path.write_text('{"model":"different"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="approved request"):
        load_approved_request(
            approved.request_path,
            expected_sha256=approved.sha256,
            manifest_path=approved.manifest_path,
        )


def test_runner_sends_exact_approved_dictionary(tmp_path):
    approved = _write_signed_preflight(tmp_path)
    client = RecordingClient(_valid_fragment_json())
    run(
        _v12_task(),
        client=client,
        approved_request_path=approved.request_path,
        approved_request_sha256=approved.sha256,
        confirm_paid_call=True,
        output_root=tmp_path / "runs",
    )
    assert client.calls == [json.loads(approved.request_path.read_bytes())]


def test_approved_request_rejects_output_limit_other_than_4000(tmp_path):
    approved = _write_signed_preflight(tmp_path, max_output_tokens=4_001)
    with pytest.raises(ValueError, match="4,000"):
        load_approved_request(
            approved.request_path,
            expected_sha256=approved.sha256,
            manifest_path=approved.manifest_path,
        )
```

Mirror direct-call and exact-dictionary tests for the vision runner.

- [ ] **Step 2: Run tests and verify RED**

```bash
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
  /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest \
  tests/test_preflight_missing_record_repairs.py \
  tests/test_missing_record_workflow.py \
  tests/test_missing_record_vision.py -q
```

Expected: failures because callable execution is not confirmed or byte-bound.

- [ ] **Step 3: Sign the preflight manifest**

Write the unsigned manifest with sorted request rows, then add:

```python
manifest_checksum = _sha(_canonical(unsigned_manifest))
```

`load_approved_request` must:

1. validate the manifest checksum;
2. locate exactly one row matching the resolved request path;
3. require the supplied expected SHA to equal the row SHA;
4. hash the request bytes and require equality;
5. parse JSON and require model, prompt/schema-bearing structure, and `max_output_tokens == 4_000`;
6. return the exact parsed dictionary.

- [ ] **Step 4: Enforce confirmation at the provider boundary**

Before cache-directory creation or any provider use, require confirmation and load the exact approved request. Cache hits may be read without confirmation, but a cache miss must fail before calling `client.responses.create` unless confirmation and approval validation pass.

The CLI must validate approval before constructing `OpenAI`. Send:

```python
api_response = client.responses.create(**approved_request)
```

Do not call `build_openai_request()` in the paid execution path.

- [ ] **Step 5: Include exact request identity in cache fingerprints**

Fingerprint fields must include `approved_request_sha256`, `max_output_tokens`, model from the approved dictionary, task checksum, and prompt version. Add a regression that two approved request files differing only in output limit cannot share a cache.

- [ ] **Step 6: Run GREEN, review, and commit**

Run the Step 2 command plus the full repository suite. Request independent review and fix all Critical/Important findings.

```bash
git add src/extraction/preflight_missing_record_repairs.py \
  src/extraction/run_missing_record_repair.py \
  src/extraction/run_missing_record_vision.py \
  tests/test_preflight_missing_record_repairs.py \
  tests/test_missing_record_workflow.py \
  tests/test_missing_record_vision.py
git commit -m "feat: bind repairs to approved request bytes"
```

### Task 2: Remove Binding Experiment Association and Define Resolution Semantics

**Files:**
- Modify: `src/extraction/build_v12_structural_repair_tasks.py`
- Modify: `src/extraction/run_missing_record_repair.py`
- Modify: `src/extraction/run_missing_record_vision.py`
- Modify: `tests/test_build_v12_structural_repair_tasks.py`
- Modify: `tests/test_missing_record_workflow.py`
- Modify: `tests/test_missing_record_vision.py`

**Interfaces:**
- Every v1.2 task sets `permitted_new_experiments=1` unless the task is explicitly human review.
- Bumps `PROMPT_VERSION` to `missing-record-repair-prompt-1.2.0` and vision prompt version to `missing-record-vision-prompt-1.2.0`.
- Existing association remains serialized only as provisional context and audit diagnostics.

- [ ] **Step 1: Write failing association and prompt tests**

```python
def test_associated_provisional_experiment_still_permits_bounded_new_experiment(tmp_path):
    task = _build_associated_task(tmp_path)
    assert task.permitted_new_experiments == 1


def test_repacking_accounts_for_new_experiment_output_allowance(tmp_path):
    manifest = build_for_run(_five_candidate_associated_run(tmp_path))
    assert all(
        row["estimated_worst_case_output_tokens"] <= 4_000
        for row in manifest["tasks"]
    )
    assert sum(row["candidate_count"] for row in manifest["tasks"]) == 5


@pytest.mark.parametrize(
    "required_text",
    [
        "already_represented",
        "recovered_existing_experiment",
        "recovered_new_experiment",
        "unresolved",
        "provisional experiment context is not a binding target",
        "distinct experiments require distinct outcomes",
        "preserve the comparator",
    ],
)
def test_text_and_vision_prompts_define_resolution_semantics(required_text):
    assert required_text in TEXT_PROMPT
    assert required_text in VISION_PROMPT
```

- [ ] **Step 2: Verify RED**

Run the three affected test files. Expected: the old association assertion and incomplete prompts fail.

- [ ] **Step 3: Remove the Boolean permission rule**

Delete the `associated_experiments` permission branch. Build every paid v1.2 task with one bounded permitted new experiment, then run the existing greedy packer again so the 500-token worst-case allowance can split tasks.

- [ ] **Step 4: Define exact semantics in both prompts**

Both prompts must state:

- every candidate receives one resolution;
- `already_represented` references only existing outcomes and experiments;
- `recovered_existing_experiment` references at least one new outcome on existing experiments;
- `recovered_new_experiment` references at least one new outcome on the one permitted new experiment;
- `unresolved` returns no records and a specific reason;
- provisional association is a hint, not a target;
- one candidate may reference several outcomes only when they link to genuinely distinct experiments;
- a multi-arm comparison produces one outcome on the encompassing experiment with its comparator preserved.

- [ ] **Step 5: Run GREEN, review, and commit**

Run affected tests and full suite. Independently review prompt/schema alignment and repacking.

```bash
git add src/extraction/build_v12_structural_repair_tasks.py \
  src/extraction/run_missing_record_repair.py \
  src/extraction/run_missing_record_vision.py \
  tests/test_build_v12_structural_repair_tasks.py \
  tests/test_missing_record_workflow.py \
  tests/test_missing_record_vision.py
git commit -m "fix: permit bounded experiment classification"
```

### Task 3: Sign and Recompute Visual Task Dispositions

**Files:**
- Modify: `src/extraction/missing_record_contracts.py`
- Modify: `src/extraction/build_missing_record_vision_tasks.py`
- Modify: `src/extraction/preflight_missing_record_repairs.py`
- Modify: `tests/test_missing_record_vision.py`
- Modify: `tests/test_preflight_missing_record_repairs.py`

**Interfaces:**
- Produces strict `MissingRecordVisionBuildManifest` and `MissingRecordVisionDisposition` models.
- Manifest version: `missing-record-vision-build-manifest-1.1.0`.
- Every manifest contains `manifest_checksum`, source structural-task checksums, accepted-registry SHA-256, generated task checksums, sendable candidate IDs, and human-review dispositions.

- [ ] **Step 1: Write failing tampering and recomputation tests**

```python
def test_preflight_rejects_edited_visual_human_review_manifest(tmp_path):
    prepared = _trusted_visual_preparation(tmp_path)
    manifest = json.loads(prepared.manifest_path.read_text())
    manifest["visual_human_review_candidate_ids"].append("AOC-FORGED")
    prepared.manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest checksum"):
        preflight(run_root=prepared.run_root, output_root=tmp_path / "out")


def test_preflight_rejects_signed_but_incorrect_visual_disposition(tmp_path):
    prepared = _trusted_visual_preparation(tmp_path)
    _rewrite_and_resign_reason(prepared.manifest_path, "accepted_visual_claim_missing")
    with pytest.raises(ValueError, match="recomputed visual disposition"):
        preflight(run_root=prepared.run_root, output_root=tmp_path / "out")
```

- [ ] **Step 2: Verify RED**

Run vision/preflight tests. Expected: the unsigned manifest is trusted.

- [ ] **Step 3: Implement strict signed manifest models**

Each disposition contains:

```python
candidate_ids: list[str]
visual_object_id: str
status: Literal["sendable", "human_review"]
reason: Literal[
    "accepted_visual_claim_missing",
    "accepted_visual_claim_not_unique",
    "accepted_visual_claim_missing_image_sha256",
    "accepted_visual_claim_image_sha256_mismatch",
]
source_text_task_checksum: str
accepted_visual_claim_sha256: str | None
vision_task_checksum: str | None
```

Distinguish zero accepted-claim matches from multiple matches.

- [ ] **Step 4: Recompute every disposition in preflight**

Load each signed structural visual task and the current accepted registry. Re-run the deterministic selection/provenance function, then require exact equality with the signed disposition and generated vision task. Require:

```python
structural_visual_ids == sendable_ids | human_review_ids
not (sendable_ids & human_review_ids)
```

- [ ] **Step 5: Run GREEN, review, and commit**

Run vision/preflight tests and full suite, independently review, then commit.

```bash
git add src/extraction/missing_record_contracts.py \
  src/extraction/build_missing_record_vision_tasks.py \
  src/extraction/preflight_missing_record_repairs.py \
  tests/test_missing_record_vision.py \
  tests/test_preflight_missing_record_repairs.py
git commit -m "fix: sign visual repair dispositions"
```

### Task 4: Bind Merge to the Complete Signed Paper Scope

**Files:**
- Modify: `src/extraction/missing_record_contracts.py`
- Modify: `src/extraction/merge_v12_structural_repairs.py`
- Modify: `tests/test_merge_v12_structural_repairs.py`

**Interfaces:**
- Produces strict `MissingRecordRepairScopeManifest`.
- Changes `merge()` to require `scope_manifest_path: Path`.
- The manifest binds paper/source hashes, all text and vision task checksums, paid candidate IDs, visual/oversized/existing-human/contradicted/confirmed IDs, and `manifest_checksum`.

- [ ] **Step 1: Write failing scope and cross-task tests**

```python
def test_partial_fragment_pairs_cannot_finalize_complete_scope(tmp_path):
    report = merge(
        **_two_task_inputs_with_only_first_fragment(tmp_path),
        scope_manifest_path=_signed_scope(tmp_path),
    )
    assert report["missing_candidate_ids"] == ["AOC-2"]
    assert report["finalization_allowed"] is False


def test_visual_quarantine_is_carried_into_merge_report(tmp_path):
    report = merge(
        **_all_text_fragments(tmp_path),
        scope_manifest_path=_scope_with_visual_review(tmp_path),
    )
    assert report["quarantined_candidate_ids"] == ["AOC-VIS"]
    assert report["finalization_allowed"] is False


def test_cross_task_cloned_outcomes_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="non-claimant"):
        merge(
            **_two_tasks_with_cross_matching_clones(tmp_path),
            scope_manifest_path=_signed_scope(tmp_path),
        )
```

Retain the distinct-experiment one-to-many passing regression.

- [ ] **Step 2: Verify RED**

Run merge tests. Expected: arbitrary pairs can finalize and cross-task clones pass.

- [ ] **Step 3: Build and validate the signed scope**

Require checksum, paper/source identity, unique/disjoint groups, exact task checksum set, and:

```python
all_candidate_ids == (
    paid_candidate_ids
    | visual_human_review_candidate_ids
    | oversized_candidate_ids
    | existing_human_review_candidate_ids
    | contradicted_candidate_ids
    | confirmed_candidate_ids
)
```

- [ ] **Step 4: Verify outcomes against complete relevant scope**

For every returned outcome, run structural assessment against every expected repair candidate in the same provisional experiment across all task batches. Reject raw-confirmed non-claimants and same-experiment duplicates; permit distinct outcomes only for distinct experiments.

- [ ] **Step 5: Report every final disposition**

The merge report must list recovered, unresolved, quarantined, contradicted, confirmed-local, invalid, and missing IDs. Set `finalization_allowed` only when no missing, unresolved, quarantined, contradicted, or invalid IDs remain.

- [ ] **Step 6: Run GREEN, review, and commit**

Run merge tests and full suite, independently review, then commit.

```bash
git add src/extraction/missing_record_contracts.py \
  src/extraction/merge_v12_structural_repairs.py \
  tests/test_merge_v12_structural_repairs.py
git commit -m "fix: bind merge to complete repair scope"
```

### Task 5: Add the Thin Resumable Coordinator

**Files:**
- Add: `src/extraction/run_cohesive_pipeline.py`
- Add: `tests/test_run_cohesive_pipeline.py`
- Modify: `docs/extraction/v12_recall_workflow.md`

**Interfaces:**
- CLI modes: `prepare`, `execute-text`, `execute-vision`, `finalize`, `status`.
- `prepare` and `status` are always local.
- Paid modes require `--confirm-paid-call`, `--preflight-manifest`, `--request-path`, and `--request-sha256`.
- The coordinator calls existing stage functions and reads their authoritative artifacts; it writes only one summary referencing those artifacts.

- [ ] **Step 1: Write failing coordinator tests**

```python
def test_prepare_stops_at_human_gate_without_client_factory(tmp_path):
    summary = run_pipeline(
        mode="prepare",
        paths=_prepared_paths(tmp_path),
        client_factory=ExplodingClientFactory(),
    )
    assert summary["next_gate"] == "human_paid_call_approval"
    assert summary["paid_api_requests"] == 0


def test_execute_text_requires_confirmation_and_exact_approval(tmp_path):
    with pytest.raises(PermissionError):
        run_pipeline(
            mode="execute-text",
            paths=_prepared_paths(tmp_path),
            confirm_paid_call=False,
        )


def test_resume_uses_valid_cache_without_second_provider_call(tmp_path):
    first = _run_one_approved_fake_response(tmp_path)
    second = run_pipeline(mode="status", paths=first.paths)
    assert second["cache_hits"] == 1
    assert second["paid_api_requests"] == 0
```

- [ ] **Step 2: Verify RED**

Run the new coordinator test file. Expected: module absent.

- [ ] **Step 3: Implement stage dispatch only**

Use small functions:

```python
prepare(paths: PipelinePaths) -> PipelineSummary
execute_approved_text(paths: PipelinePaths, approval: Approval) -> PipelineSummary
execute_approved_vision(paths: PipelinePaths, approval: Approval) -> PipelineSummary
finalize(paths: PipelinePaths) -> PipelineSummary
status(paths: PipelinePaths) -> PipelineSummary
```

Each delegates to existing builders/runners/audit/preflight/merge/evaluator. Do not copy scientific matching logic or create a new canonical state store.

- [ ] **Step 4: Print one exact approval/status summary**

Include paper IDs, local matches, text and vision candidate/call counts, quarantined groups/reasons, per-request and total token ceilings, pricing status, exact request paths/hashes, cache status, and the next required action.

- [ ] **Step 5: Run GREEN, review, and commit**

Run coordinator tests and full suite. Independently review all paid-mode paths for confirmation bypass.

```bash
git add src/extraction/run_cohesive_pipeline.py \
  tests/test_run_cohesive_pipeline.py \
  docs/extraction/v12_recall_workflow.md
git commit -m "feat: coordinate cohesive extraction stages"
```

### Task 6: Regenerate, Audit, and Stop at the New Human Gate

**Files:**
- Generated: `data/staging/extraction/v12_structural_primary_v8/**`
- Generated: `data/staging/extraction/v12_structural_primary_v8_preflight/**`
- Generated: `reports/extraction/v12_structural_primary_v8/**`

**Interfaces:**
- Produces the exact unsent v8 approval snapshot for GP-004, GP-006, and GP-008.
- Executes no provider request.

- [ ] **Step 1: Run full verification**

```bash
PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages \
  /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run final whole-branch review**

Review the entire Strategy 2 range against the approved design and all Strategy 1 final-review findings. Fix every Critical/Important issue, rerun tests, and re-review.

- [ ] **Step 3: Generate fresh v8 artifacts locally**

Run coordinator `prepare` for GP-004/006/008 with fresh roots. Assert:

```text
server_request_sent: false
generation_requests: 0
paid_api_requests: 0
human_approval_required: true
```

- [ ] **Step 4: Independently audit the exact snapshot**

Recompute manifest checksums, request byte hashes/counts, task/scope checksums, candidate conservation, route separation, token ceilings, prompt/schema versions, gold scan, and visual dispositions. Require every request to permit one bounded new experiment and fit both token ceilings.

- [ ] **Step 5: Present the exact paid-call gate and stop**

Report each request path/hash, candidate count, experiment-summary count, input estimate, 4,000 output ceiling, total calls/tokens, visual quarantines, pricing status, and expected evaluation limitation. Ask for explicit human approval. Do not execute a provider request.

## Post-Approval Development Evaluation

This section remains unauthorized until the user approves the exact v8 snapshot.

1. Execute each exact approved request once through the coordinator with `--confirm-paid-call`.
2. Validate/cache raw responses, merge against the complete signed scope, and run the existing dynamic gold evaluator.
3. Pass development at verified 13/15–15/15 recall, precision `>= 0.9`, zero unsupported accepted outcomes, and zero wrong experiment links.
4. If a small isolated defect is demonstrated, permit the one previously approved bounded fix/review/re-preflight/rerun cycle; otherwise stop.

## New-Paper Generalization After Development Success

1. Search PubMed and Europe PMC for an open full-text original LNP experimental paper.
2. Exclude every PMID/PMCID/DOI/title already present in the gold set or corpus.
3. Record identifier, DOI, source URL, retrieval date, full-text license/access, and corpus-overlap evidence.
4. Prefer a paper with identifiable formulation, payload, experiment, and outcome evidence and at least one table or figure route.
5. Ingest it without gold annotations and run the unchanged coordinator through local preparation.
6. Present a separate exact paid-call gate and wait for explicit approval.
7. Evaluate auditability, evidence support, linkage safety, and candidate dispositions; do not invent a recall denominator.
