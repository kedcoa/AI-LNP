# Streamlined Cohesive Extraction Morning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing bounded repair route carry enough semantic context and enforce explicit candidate resolutions, then prepare a safe GP-004/006/008 paid attempt that passes with verified recall of 13/15 through 15/15.

**Architecture:** Extend the existing missing-record contracts instead of adding another extraction layer. The current structural task builder will serialize compact existing experiment/outcome summaries, separate text from visual work, and greedily pack complete candidates under measured input and estimated output limits. Existing text/vision runners, structural validation, and additive merge remain authoritative, with stricter cross-link checks and raw-response persistence.

**Tech Stack:** Python 3.14, Pydantic v2, OpenAI Responses API, pytest, existing AI-LNP compact extraction and deterministic structural-coverage modules.

## Global Constraints

- Strategy 1 is limited to the existing repair contract, task builders, text/vision runners, preflight, audit, and merge verification; do not add a new orchestration layer.
- Every requested candidate ID must have exactly one explicit candidate resolution.
- Each task must include the atomic candidate fact, its exact evidence, and compact summaries of every plausibly relevant existing experiment.
- Text and visual candidates must never share a paid repair task.
- The serialized input ceiling is 6,000 estimated tokens per repair request; the configured output ceiling is 4,000 tokens.
- Candidate counts are dynamic. Pack the next scientifically compatible candidate only when its complete input and estimated worst-case output fit; otherwise start another task.
- Never drop a candidate, evidence item, or plausible experiment summary to make a task fit.
- Persist the raw provider response before parsing structured output.
- No automatic retries. One root-caused, small-bug correction and rerun is allowed only after a new user approval.
- No gold outcome IDs or gold answers may enter extraction-time requests.
- Every paid text or vision batch requires a displayed preflight and explicit `--confirm-paid-call`; execution stops for human approval before any real request.
- Development acceptance is verified merged recall of 13/15, 14/15, or 15/15, precision at least 0.9, zero unsupported accepted outcomes, and zero wrong experiment links.
- Use test-driven development, `superpowers:systematic-debugging` for every unexpected failure, per-task `superpowers:requesting-code-review`, and a final whole-change review.

---

### Task 1: Versioned Semantic Task and Candidate-Resolution Contracts

**Files:**
- Modify: `src/extraction/missing_record_contracts.py`
- Modify: `src/extraction/run_missing_record_repair.py`
- Modify: `tests/test_missing_record_workflow.py`
- Modify: `tests/test_preflight_missing_record_repairs.py`

**Interfaces:**
- Produces: `MissingRecordExperimentSummary`, `MissingRecordOutcomeSummary`, `MissingRecordCandidateResolution`, `MissingRecordTask` version `missing-record-task-1.2.0`, and stricter `validate_response(response, task) -> None`.
- Preserves: v1.0/v1.1 task and cached-fragment deserialization.
- Consumed by: Tasks 2–4.

- [ ] **Step 1: Write failing contract tests**

Add tests proving:

```python
def test_v12_task_requires_compact_existing_experiment_summaries():
    payload = _v12_task_payload()
    payload["existing_experiment_summaries"] = []
    with pytest.raises(ValueError, match="summary"):
        MissingRecordTask.model_validate(payload)


def test_response_requires_one_resolution_for_every_candidate():
    response = _fragment(candidate_resolutions=[_resolution("OC-1")])
    with pytest.raises(ValueError, match="candidate resolution"):
        validate_response(response, _v12_task())


def test_one_candidate_may_resolve_to_distinct_experiment_linked_outcomes():
    validate_response(
        _fragment(
            recovered=["OC-1"],
            outcomes=[
                _outcome("O2", "E1"),
                _outcome("O3", "E2"),
            ],
            candidate_resolutions=[
                _resolution(
                    "OC-1",
                    status="recovered_existing_experiment",
                    outcome_ids=["O2", "O3"],
                    experiment_ids=["E1", "E2"],
                )
            ],
        ),
        _v12_task(existing_experiment_ids=["E1", "E2"]),
    )


def test_unresolved_resolution_cannot_reference_records():
    response = _fragment(
        unresolved=["OC-1", "OC-2"],
        candidate_resolutions=[
            _resolution("OC-1", status="unresolved", reason="Ambiguous."),
            _resolution(
                "OC-2",
                status="unresolved",
                outcome_ids=["O2"],
                reason="Ambiguous.",
            ),
        ],
    )
    with pytest.raises(ValueError, match="unresolved"):
        validate_response(response, _v12_task())
```

Also update the strict-schema test to assert the new response schema has no open or optional object properties.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest \
  tests/test_missing_record_workflow.py \
  tests/test_preflight_missing_record_repairs.py -q
```

Expected: failures because the semantic summary and resolution models do not exist.

- [ ] **Step 3: Implement the minimal versioned models**

Add strict models with these exact fields:

```python
class MissingRecordExperimentSummary(StrictModel):
    experiment_id: str
    formulation_id: str
    payload_type: str | None
    payload_name: str | None
    encoded_product: str | None
    molecular_target: str | None
    delivery_recipient_cell: str | None
    therapeutic_target_cell: str | None
    tissue_or_organ: str | None
    species: str | None
    disease_model: str | None
    experimental_context: str | None
    dose: float | None
    dose_unit: str | None
    route: str | None
    timepoint: float | None
    timepoint_unit: str | None
    outcome_endpoints: list[str]
    comparator_context: list[str]


class MissingRecordOutcomeSummary(StrictModel):
    outcome_id: str
    experiment_id: str
    assay: str | None
    endpoint: str | None
    comparator: str | None
    qualitative_outcome: str | None


class MissingRecordCandidateResolution(StrictModel):
    candidate_id: str
    status: Literal[
        "already_represented",
        "recovered_existing_experiment",
        "recovered_new_experiment",
        "unresolved",
    ]
    outcome_ids: list[str]
    experiment_ids: list[str]
    reason: str | None
```

Extend `MissingRecordTask.task_version` with `missing-record-task-1.2.0` and add:

```python
existing_experiment_summaries: list[MissingRecordExperimentSummary] = Field(
    default_factory=list
)
existing_outcome_summaries: list[MissingRecordOutcomeSummary] = Field(
    default_factory=list
)
```

Extend `MissingRecordFragment` with:

```python
candidate_resolutions: list[MissingRecordCandidateResolution] = Field(
    default_factory=list
)
```

For v1.2 tasks, validate exact summary ID equality with `existing_experiment_ids`, exact candidate-resolution ID equality, allowed status/list combinations, known outcome/experiment IDs, and explicit links from every returned outcome to at least one candidate resolution. Keep the old recovered/unresolved lists as compatibility/audit projections and require them to agree with resolution statuses.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Request task-scoped code review and fix all Critical/Important findings**

Use `superpowers:requesting-code-review` with the Task 1 brief and the exact Task 1 diff. Re-run the Step 2 test command after corrections.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/extraction/missing_record_contracts.py \
  src/extraction/run_missing_record_repair.py \
  tests/test_missing_record_workflow.py \
  tests/test_preflight_missing_record_repairs.py
git commit -m "feat: add semantic missing-record resolutions"
```

### Task 2: Compact Summaries and Dynamic Route-Aware Packing

**Files:**
- Modify: `src/extraction/build_v12_structural_repair_tasks.py`
- Modify: `src/extraction/audit_v12_structural_tasks.py`
- Modify: `tests/test_build_v12_structural_repair_tasks.py`
- Modify: `tests/test_missing_record_workflow.py`

**Interfaces:**
- Consumes: Task 1 semantic models and `build_openai_request`.
- Produces: `compact_experiment_summaries(result: dict[str, Any]) -> list[MissingRecordExperimentSummary]`.
- Produces: `compact_outcome_summaries(result: dict[str, Any]) -> list[MissingRecordOutcomeSummary]`.
- Produces: `estimate_input_tokens(task: MissingRecordTask, *, model: str) -> int`.
- Produces: `estimate_worst_case_output_tokens(task: MissingRecordTask) -> int`.
- Produces: `pack_candidate_tasks(candidates: list[AtomicOutcomeCandidateV12], *, task_factory: Callable[[list[AtomicOutcomeCandidateV12]], MissingRecordTask], model: str, input_limit: int = 6_000, output_limit: int = 4_000) -> tuple[list[MissingRecordTask], list[str]]`.

- Task manifest adds `repair_route`, `estimated_input_tokens`, `estimated_worst_case_output_tokens`, and `visual_object_id`.
- Consumed by: Tasks 3–4.

- [ ] **Step 1: Write failing builder tests**

Add isolated fixtures and tests proving:

```python
def test_task_contains_semantic_summaries_for_every_existing_experiment(tmp_path):
    manifest = build_for_run(_semantic_run(tmp_path))
    task = _load_only_text_task(tmp_path)
    assert {row.experiment_id for row in task.existing_experiment_summaries} == {
        "EXP-EGFP",
        "EXP-HGF-EGF-1",
        "EXP-HGF-EGF-2",
    }
    assert task.existing_experiment_summaries[0].payload_name is not None


def test_dynamic_packing_spills_before_measured_token_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        builder,
        "estimate_input_tokens",
        lambda task, model: 5_900 if len(task.candidate_ids) == 2 else 6_100,
    )
    manifest = build_for_run(_run_with_candidates(tmp_path, count=4))
    assert [row["candidate_count"] for row in manifest["tasks"]] == [2, 2]


def test_text_and_visual_candidates_never_share_a_task(tmp_path):
    manifest = build_for_run(_mixed_route_run(tmp_path))
    assert {row["repair_route"] for row in manifest["tasks"]} == {
        "text",
        "vision",
    }
    assert all(
        not (set(row["candidate_ids"]) & set(manifest["visual_candidate_ids"]))
        for row in manifest["tasks"]
        if row["repair_route"] == "text"
    )


def test_candidate_that_cannot_fit_alone_goes_to_human_review(tmp_path):
    manifest = build_for_run(_oversized_single_candidate_run(tmp_path))
    assert manifest["oversized_candidate_ids"] == ["AOC-OVERSIZED"]
    assert "AOC-OVERSIZED" not in _all_paid_candidate_ids(manifest)
```

Add an audit test asserting exact repair-scope equality across text tasks, visual tasks, oversized review, existing human review, and confirmed candidates.

- [ ] **Step 2: Run builder/audit tests and verify RED**

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest \
  tests/test_build_v12_structural_repair_tasks.py \
  tests/test_missing_record_workflow.py -q
```

Expected: failures for absent summaries, route metadata, and token-aware packing.

- [ ] **Step 3: Implement compact serialization**

Read values from the existing compact `ReportedField` shape with one helper:

```python
def _reported_value(row: dict[str, Any], field_name: str) -> Any:
    field = row.get(field_name)
    return field.get("value") if isinstance(field, dict) else None
```

Build one summary for every existing experiment. Populate `outcome_endpoints` and `comparator_context` from outcomes linked by `experiment_id`; build the separate existing-outcome summaries from the same records. Do not include evidence wrappers or unrelated narrative.

- [ ] **Step 4: Implement greedy measured packing**

Partition first by `(repair_route, provisional_experiment_id, visual_object_id)`, where `repair_route` is `vision` only when `candidate.route_hint == "vision"`. Add candidates in stable `candidate_id` order. For each proposed batch:

1. Construct the complete signed v1.2 task with all summaries and evidence.
2. Measure the exact OpenAI request with `estimate_input_tokens`.
3. Estimate worst-case output as:

```python
600 + 650 * len(task.candidate_ids) + 500 * task.permitted_new_experiments
```

4. Accept only when input is `<= 6_000`, output is `<= 4_000`, candidate facts are `<= 8`, and unique evidence is `<= 12`.
5. Otherwise close the current batch and retry the same candidate in a new task.
6. If one complete candidate cannot fit alone, route it to `oversized_candidate_ids` for human review.

For the morning papers, include all existing experiment summaries. This is conservative and guarantees every plausible experiment is present; do not implement semantic top-k retrieval.

- [ ] **Step 5: Update the audit and run tests**

Audit exact candidate conservation and assert:

```python
repair_ids == text_task_ids | vision_task_ids | oversized_candidate_ids
not (text_task_ids & vision_task_ids)
all(task.estimated_input_tokens <= 6_000 for task in tasks)
all(task.estimated_worst_case_output_tokens <= 4_000 for task in tasks)
```

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Request task-scoped review and fix findings**

Review the complete Task 2 diff. Re-run the Step 2 test command after corrections.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/extraction/build_v12_structural_repair_tasks.py \
  src/extraction/audit_v12_structural_tasks.py \
  tests/test_build_v12_structural_repair_tasks.py \
  tests/test_missing_record_workflow.py
git commit -m "feat: pack semantic repair tasks by route"
```

### Task 3: Safe Text/Vision Execution and Exact Approval Preflight

**Files:**
- Modify: `src/extraction/missing_record_contracts.py`
- Modify: `src/extraction/build_missing_record_vision_tasks.py`
- Modify: `src/extraction/run_missing_record_repair.py`
- Modify: `src/extraction/run_missing_record_vision.py`
- Modify: `src/extraction/preflight_missing_record_repairs.py`
- Modify: `tests/test_missing_record_workflow.py`
- Modify: `tests/test_preflight_missing_record_repairs.py`
- Add or Modify: `tests/test_missing_record_vision.py`

**Interfaces:**
- Consumes: route-aware Task 2 manifests and Task 1 candidate resolution.
- Produces: v1.1 vision tasks carrying candidate facts, compact experiment/outcome summaries, and the accepted visual image; `persist_raw_response(run_dir, api_response) -> Path`; approval report fields `local_match_count`, `text_candidate_count`, `text_request_count`, `visual_candidate_count`, `visual_object_count`, `vision_request_count`, `total_paid_request_count`, token estimates, and request paths.
- Stops before calling the provider unless `--confirm-paid-call` is explicitly supplied.

- [ ] **Step 1: Write failing raw-persistence and vision-contract tests**

Add tests proving:

```python
def test_raw_response_is_persisted_before_invalid_json_is_parsed(tmp_path):
    client = _client_with_output("truncated {")
    with pytest.raises(ValidationError):
        run(_v12_task(), model="test", client=client, output_root=tmp_path)
    assert list(tmp_path.rglob("response.raw.json"))


def test_visual_task_carries_candidate_facts_and_semantic_summaries(tmp_path):
    task = build(_visual_builder_inputs(tmp_path))
    assert task.candidate_facts
    assert task.existing_experiment_summaries
    assert task.crop_path.endswith(".png")


def test_preflight_reports_exact_paid_call_and_route_totals(tmp_path):
    report = preflight(run_root=_prepared_run(tmp_path), output_root=tmp_path / "out")
    assert report["text_request_count"] == 2
    assert report["vision_request_count"] == 2
    assert report["total_paid_request_count"] == 4
    assert report["server_request_sent"] is False
    assert report["paid_api_requests"] == 0
```

- [ ] **Step 2: Run focused runner/preflight tests and verify RED**

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest \
  tests/test_missing_record_workflow.py \
  tests/test_missing_record_vision.py \
  tests/test_preflight_missing_record_repairs.py -q
```

Expected: failures for early raw persistence, semantic visual tasks, and route totals.

- [ ] **Step 3: Persist raw responses before structured parsing**

In both paid runners, immediately after `client.responses.create` returns, write:

```python
raw_response_path = run_dir / "response.raw.json"
raw_response_path.write_text(
    json.dumps(api_response.model_dump(mode="json"), ensure_ascii=False, indent=2)
    + "\n",
    encoding="utf-8",
)
```

Only then check `output_text`, parse, and validate. Keep incomplete run directories non-retryable.

- [ ] **Step 4: Extend candidate-level visual tasks without adding a vision route**

Version `MissingRecordVisionTask` to `missing-record-vision-task-1.1.0` and carry the same `candidate_facts`, `existing_experiment_summaries`, and `existing_outcome_summaries` used by text repair. Resolve `crop_path` from the accepted visual claim’s `image_path` and verify its checksum. Adapt `_as_text_task` to a v1.2 task so the identical resolution validation applies to the visual fragment.

- [ ] **Step 5: Build the exact approval report**

Preflight both task roots, serialize exact text and visual requests, verify schemas/checksums/source hashes, and report:

```python
{
    "local_match_count": int,
    "missing_candidate_count": int,
    "text_candidate_count": int,
    "text_request_count": int,
    "visual_candidate_count": int,
    "visual_object_count": int,
    "vision_request_count": int,
    "total_paid_request_count": int,
    "estimated_input_tokens": int,
    "max_output_tokens": int,
    "estimated_cost": str | None,
    "request_paths": list[str],
    "server_request_sent": False,
    "paid_api_requests": 0,
    "human_approval_required": True,
}
```

If current official model pricing is unavailable locally, set `estimated_cost` to `null` and label the report `pricing_not_configured`; do not guess.

- [ ] **Step 6: Run tests and request code review**

Run the Step 2 command. Request task-scoped review, address Critical/Important findings, and rerun.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/extraction/missing_record_contracts.py \
  src/extraction/build_missing_record_vision_tasks.py \
  src/extraction/run_missing_record_repair.py \
  src/extraction/run_missing_record_vision.py \
  src/extraction/preflight_missing_record_repairs.py \
  tests/test_missing_record_workflow.py \
  tests/test_missing_record_vision.py \
  tests/test_preflight_missing_record_repairs.py
git commit -m "feat: preflight safe text and vision repairs"
```

### Task 4: Resolution-Aware Merge, Regression Gate, and Frozen Request Preparation

**Files:**
- Modify: `src/extraction/merge_v12_structural_repairs.py`
- Modify: `tests/test_merge_v12_structural_repairs.py`
- Modify: `tests/test_evaluate_v12_combined_recall.py`
- Modify: `docs/extraction/v12_recall_workflow.md`
- Generated after tests: `data/staging/extraction/v12_structural_primary_v7/**`
- Generated after tests: `data/staging/extraction/v12_structural_primary_v7_preflight/**`
- Generated after tests: `reports/extraction/v12_structural_primary_v7/**`

**Interfaces:**
- Consumes: Task 1 resolutions, Task 2 tasks, Task 3 text/vision results.
- Produces: merge report with per-candidate candidate/outcome/experiment disposition; frozen local preflight for GP-004/006/008.
- Ends at: human approval gate. It does not execute a paid call.

- [ ] **Step 1: Write failing merge tests**

Add tests proving:

```python
def test_merge_rejects_returned_outcome_absent_from_resolutions(tmp_path):
    with pytest.raises(ValueError, match="candidate resolution"):
        merge(**_merge_inputs_with_unlinked_outcome(tmp_path))


def test_merge_rejects_resolution_with_wrong_experiment_link(tmp_path):
    with pytest.raises(ValueError, match="experiment"):
        merge(**_merge_inputs_with_wrong_resolution_link(tmp_path))


def test_merge_accepts_one_candidate_with_distinct_verified_experiment_outcomes(tmp_path):
    report = merge(**_valid_multi_experiment_inputs(tmp_path))
    assert report["candidate_resolutions"][0]["experiment_ids"] == ["EXP1", "EXP2"]


def test_unresolved_candidate_is_quarantined_without_discarding_verified_peer(tmp_path):
    report = merge(**_mixed_resolution_inputs(tmp_path))
    assert report["recovered_candidate_ids"] == ["AOC-1"]
    assert report["quarantined_candidate_ids"] == ["AOC-2"]
```

- [ ] **Step 2: Run merge/evaluation tests and verify RED**

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest \
  tests/test_merge_v12_structural_repairs.py \
  tests/test_evaluate_v12_combined_recall.py -q
```

Expected: failures for absent resolution-aware merge behavior.

- [ ] **Step 3: Implement resolution-aware verification**

Before mutating the merged result:

1. Validate every fragment against its task.
2. Build maps for existing and returned outcomes.
3. Verify each resolution’s outcome IDs point to outcomes whose `experiment_id` is in that resolution.
4. Verify every returned outcome appears in at least one recovered resolution.
5. Verify every returned experiment is referenced and has at least one linked returned outcome.
6. Run existing compact validation and structural coverage.
7. Add only structurally confirmed outcomes; retain unresolved candidates in `quarantined_candidate_ids`.
8. Persist the auditable resolution list in the merge report.

Do not weaken existing collision, checksum, evidence, unrelated-outcome, or structural-confirmation checks.

- [ ] **Step 4: Run the complete focused morning suite**

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest \
  tests/test_missing_record_workflow.py \
  tests/test_build_v12_structural_repair_tasks.py \
  tests/test_preflight_missing_record_repairs.py \
  tests/test_missing_record_vision.py \
  tests/test_merge_v12_structural_repairs.py \
  tests/test_deterministic_coverage_v12.py \
  tests/test_evaluate_v12_combined_recall.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Run final whole-change code review**

Use `superpowers:requesting-code-review` against the entire morning implementation range. Fix all Critical and Important findings. Use systematic debugging before modifying code for any failed test. Repeat Step 4 after fixes.

- [ ] **Step 6: Commit reviewed merge and documentation changes**

```bash
git add src/extraction/merge_v12_structural_repairs.py \
  tests/test_merge_v12_structural_repairs.py \
  tests/test_evaluate_v12_combined_recall.py \
  docs/extraction/v12_recall_workflow.md
git commit -m "feat: verify semantic structural repairs"
```

- [ ] **Step 7: Prepare fresh GP-004/006/008 tasks locally**

Run the existing preparation functions with a fresh `v7` output root, then audit and preflight. No OpenAI client may be constructed in this step. Confirm:

```text
server_request_sent: false
paid_api_requests: 0
human_approval_required: true
```

- [ ] **Step 8: Present the exact paid-call gate and stop**

Report local matches, text candidates/calls, visual candidates/objects/calls, total calls, token estimates, cost status, checksums, and exact request paths. Ask for explicit approval. Do not execute any provider request in this plan execution turn.

## Post-Approval Evaluation Procedure

This section is deliberately not authorized by plan execution alone.

1. After explicit user approval, run each exact preflighted request once with `--confirm-paid-call`.
2. Validate, structurally verify, and merge cached responses locally.
3. Run the existing dynamic gold evaluator for GP-004/006/008.
4. Pass Strategy 1 only for verified 13/15–15/15 recall, precision `>= 0.9`, zero unsupported accepted outcomes, and zero wrong experiment links.
5. For a below-threshold or unsafe result, invoke `superpowers:systematic-debugging` and classify the cause.
6. If it is one small isolated defect, write one failing regression test, implement one bounded fix, review it, preflight again, and request approval for a single rerun.
7. Otherwise begin the separately planned Strategy 2 fuller workflow.
