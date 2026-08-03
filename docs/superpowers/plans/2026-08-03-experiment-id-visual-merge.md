# Experiment-ID Visual Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Join every validated selective-vision outcome to a source-supported experiment through an immutable pre-call experiment ID, raising NP-002 complete-arm recall to at least 80% or ending after one bounded fix pass.

**Architecture:** Extend the existing visual slot contract with an experiment ID resolved from a six-arm evidence-backed inventory. Require future structured responses to echo that ID, validate the exact candidate/experiment pair, and have `merge_validated()` inherit arm metadata by ID rather than by figure-specific rules. Rebind the already validated responses locally to the new immutable tasks for a zero-cost replay.

**Tech Stack:** Python 3.14, Pydantic, pytest, JSON artifacts, existing full-paper benchmark evaluator.

## Global Constraints

- No paid provider call is authorized or required.
- Production construction and merging must not read frozen gold.
- Existing response, task, request, crop, and manifest integrity checks remain enforced.
- Do not add an LLM stage, global registry, or graph-derived numeric estimates.
- Accept only source-supported experiment identity fields with field-level evidence IDs.
- Stop after one narrow post-replay fix pass if complete-arm recall remains below 80%.
- If the gate fails, preserve the results and move next to multi-paper ingestion, database population, and a minimal UI.

---

### Task 1: Build the verified six-arm inventory and bind every visual slot

**Files:**
- Modify: `src/extraction/run_np002_selective_outcomes.py`
- Test: `tests/test_np002_selective_outcomes.py`

**Interfaces:**
- Produces: `_experiment_inventory(paper_map: Mapping[str, Any]) -> dict[str, dict[str, Any]]`
- Produces: `_experiment_id(formulation: str, payload: str, dose: float | None) -> str`
- Changes: `Slot.experiment_id: str` and every persisted `task["slots"]` entry.
- Consumes: the committed paper-map formulations, payloads, provisional contexts, and NP-002 source evidence already included in the task packet.

- [ ] **Step 1: Write failing inventory and slot-binding tests**

Add tests asserting that `prepare()` produces exactly six unique experiment IDs across 18 slots, that each ID maps to the literal expected formulation/payload/dose triple, and that no answer-key path can be read. Include the specific regression assertion that Figure 4's 1.0 mg/kg slots do not resolve to a 0.3 mg/kg experiment.

```python
expected = {
    ("MC3", "QUANT DNA", 0.3),
    ("cKK-E12", "QUANT DNA", 0.3),
    ("MC3", "Cre mRNA", 0.3),
    ("cKK-E12", "Cre mRNA", 0.3),
    ("MC3", "Cre mRNA", 1.0),
    ("cKK-E12", "Cre mRNA", 1.0),
}
actual = {
    (arm["formulation"], arm["payload"], arm["dose"]["value"])
    for arm in manifest["experiment_inventory"].values()
}
assert actual == expected
assert len({slot["experiment_id"] for task in tasks.values() for slot in task["slots"]}) == 6
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest tests/test_np002_selective_outcomes.py -k 'inventory or experiment_id' -q
```

Expected: FAIL because slots and the manifest do not expose experiment IDs or a six-arm inventory.

- [ ] **Step 3: Implement the minimal evidence-backed inventory**

Add `experiment_id` to `Slot`. Construct the two QUANT DNA arms from the matching paper-map contexts. Split the paper map's combined Figure 4 dose statement into four arms only because the existing Figure 4 task evidence explicitly supplies both 0.3 and 1.0 dose slots; retain the source paper-map evidence IDs on the inherited fields. Persist the inventory in the signed preflight manifest and its relevant subset in each immutable task envelope.

Use stable IDs derived from identity, not ordering:

```python
def _experiment_id(formulation: str, payload: str, dose: float | None) -> str:
    payload_key = "QUANT" if payload == "QUANT DNA" else "CRE"
    formulation_key = "MC3" if formulation == "MC3" else "cKKE12"
    return f"EXP::NP002::{payload_key}::{formulation_key}::{float(dose):.1f}"
```

Remove ambiguity by passing Figure 2's source-supported 0.3 dose into slot construction instead of storing `None`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/extraction/run_np002_selective_outcomes.py tests/test_np002_selective_outcomes.py
git commit -m "feat: bind visual slots to verified experiments"
```

### Task 2: Require and validate immutable candidate/experiment pairs

**Files:**
- Modify: `src/extraction/run_np002_selective_outcomes.py`
- Test: `tests/test_np002_selective_outcomes.py`

**Interfaces:**
- Changes: `OutcomeRow.experiment_id: str`.
- Changes: `_response_schema(slots)` requires `experiment_id` in every outcome.
- Changes: `validate_visual_response(response, task)` checks `outcome.experiment_id == expected[outcome.slot_id].experiment_id`.
- Produces: `_rebind_validated_response(response, task) -> dict[str, Any]` for authenticated legacy replay only.

- [ ] **Step 1: Write failing exact-pair validation tests**

Add one passing fixture with the expected experiment ID and separate tests proving that a missing, invented, or swapped experiment ID is rejected.

```python
response = _valid_response()
response["outcomes"][0]["experiment_id"] = "EXP::NP002::QUANT::cKKE12::0.3"
with pytest.raises(ValueError, match="experiment identity"):
    selective.validate_visual_response(response, figure_2_task)
```

Also assert the generated strict JSON schema requires `experiment_id`.

- [ ] **Step 2: Run the exact-pair tests and verify RED**

Run:

```bash
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest tests/test_np002_selective_outcomes.py -k 'experiment_identity or strict_dynamic_schema' -q
```

Expected: FAIL because the response schema does not carry experiment IDs.

- [ ] **Step 3: Implement exact-pair validation and bounded legacy rebinding**

Add the field to the Pydantic response model and strict API schema. Validate it beside the existing immutable formulation, payload, dose, recipient, assay, and endpoint fields.

Implement `_rebind_validated_response()` so it may add a missing experiment ID only after the legacy response has passed its original slot/evidence validation and only by looking up the exact slot ID in the newly signed task. It must not change scientific values, dispositions, evidence IDs, or outcomes. This function exists only to replay the two authenticated paid responses without another call.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command plus:

```bash
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest tests/test_np002_selective_outcomes.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/extraction/run_np002_selective_outcomes.py tests/test_np002_selective_outcomes.py
git commit -m "feat: enforce visual experiment identity"
```

### Task 3: Replace figure-based merging with deterministic ID joining

**Files:**
- Modify: `src/extraction/run_np002_selective_outcomes.py`
- Test: `tests/test_np002_selective_outcomes.py`

**Interfaces:**
- Removes: `_arm_context(task, slot)` as a source of scientific identity.
- Changes: `merge_validated()` resolves experiment metadata from the signed inventory and `row["experiment_id"]`.
- Produces: one outcome-level database row per visual candidate while allowing three rows to inherit the same six-arm experiment identity.

- [ ] **Step 1: Write failing deterministic-join tests**

Replace the old assertion that every outcome creates a separate `VIS::` experiment. Assert instead:

```python
assert len({row["source_experiment_id"] for row in artifact["experiments"]}) == 6
assert all(not row["experiment_id"].startswith("VIS::") for row in artifact["experiments"])
assert all(row["dose"]["evidence_ids"] for row in artifact["experiments"])
assert all(row["route"]["evidence_ids"] for row in artifact["experiments"])
```

Add a conflict test proving that a visual row whose formulation, payload, or dose disagrees with the bound experiment is rejected rather than merged. Retain the test that prevents answer-key access.

- [ ] **Step 2: Run deterministic-join tests and verify RED**

Run:

```bash
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest tests/test_np002_selective_outcomes.py -k 'merge_validated' -q
```

Expected: FAIL because the current merger creates `VIS::` identities and calls `_arm_context()`.

- [ ] **Step 3: Implement the minimal deterministic merger**

Resolve each row's experiment from the signed inventory. Build each outcome-level experiment record from inherited inventory fields plus the visual recipient. Preserve evidence IDs from the inventory for arm metadata and from the visual response for outcomes. Give the materialized row a stable ID such as `ROW::<experiment_id>::<slot_id>` and retain `source_experiment_id` for grouping.

Delete `_arm_context()` and all conditional Figure 2/Figure 4 scientific assignments. Do not implement fuzzy matching or post-hoc inference.

- [ ] **Step 4: Run focused and full tests and verify GREEN**

Run:

```bash
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest tests/test_np002_selective_outcomes.py -q
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q
```

Expected: focused tests pass; full suite remains at or above the 592-test baseline with zero failures.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/extraction/run_np002_selective_outcomes.py tests/test_np002_selective_outcomes.py
git commit -m "fix: join visual outcomes by experiment id"
```

### Task 4: Replay existing responses, score, and enforce the stop rule

**Files:**
- Modify: `src/extraction/run_np002_selective_outcomes.py`
- Test: `tests/test_np002_selective_outcomes.py`
- Create: `reports/extraction/np002_experiment_id_merge_result.md`
- Generate: `reports/extraction/np002_selective_vision_score.json`

**Interfaces:**
- Produces: `replay_validated(source_manifest_path, source_run_root, target_manifest_path, target_run_root) -> dict[str, Any]`.
- Consumes: authenticated Figure 2 and Figure 4 validated responses plus their recorded SHA-256 values.
- Produces: newly validated local replay artifacts with `paid_api_requests: 0` and `source_paid_api_requests: 2`.

- [ ] **Step 1: Write a failing replay-provenance test**

Test that replay refuses a modified source response, records zero new paid requests, adds only predetermined experiment IDs, and produces responses accepted by the new validator.

- [ ] **Step 2: Run the replay test and verify RED**

Run:

```bash
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest tests/test_np002_selective_outcomes.py -k 'replay_validated' -q
```

Expected: FAIL because the replay function does not exist.

- [ ] **Step 3: Implement authenticated local replay**

Verify the source preflight, source run manifest, request hashes, response hashes, and validated responses before rebinding. Write new validated responses and a signed replay manifest without constructing an OpenAI client. Record both zero new calls and the two historical source calls.

- [ ] **Step 4: Run replay, merge, and score locally**

Prepare a new preflight, replay from `data/staging/extraction/np002_selective_outcomes_run`, merge to `data/staging/extraction/np002_experiment_id_merged/NP-002/merged_extraction.json`, and run `evaluate()` against the committed NP-002 benchmark only after the production artifact exists.

Record overall recall, complete-arm recall, precision, wrong-arm links, unsupported inventions, and missing fact categories in the result Markdown.

- [ ] **Step 5: Apply at most one narrow fix pass**

If complete-arm recall is below 80%, use `superpowers:systematic-debugging` to classify the failures. Correct only a narrow implementation defect in inventory projection, deterministic joining, alias normalization, or evaluator adaptation. Re-run once.

Do not add another model call, inference layer, or NP-002-specific figure rule.

- [ ] **Step 6: Record the go/no-go decision**

If all acceptance gates pass, document the merger as validated and identify generalization to a new paper as the next test. If any gate still fails, document the best score and remaining causes, stop NP-002 work, and set the next engineering task to multi-paper ingestion, provenance-aware database loading, and minimal UI construction.

- [ ] **Step 7: Run final verification and commit**

Run the full suite from Task 3 and `git diff --check`. Then commit implementation, tests, generated score, and the result report without staging `.env` or unrelated artifacts.

```bash
git add src/extraction/run_np002_selective_outcomes.py tests/test_np002_selective_outcomes.py reports/extraction/np002_experiment_id_merge_result.md reports/extraction/np002_selective_vision_score.json
git commit -m "test: replay experiment-id visual merge"
```
