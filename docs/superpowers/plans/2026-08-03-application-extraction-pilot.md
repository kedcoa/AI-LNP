# Application Extraction Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the validated experiment-ID merge, represent outcomes as auditable scientific assertions, and run an uninterrupted three-paper pilot that measures application-required extraction recall.

**Architecture:** Extend the existing full-paper contracts and task builder instead of replacing them. Stable experiment IDs are created locally and carried through text and visual requests; a generic merger joins shared facts and outcomes only through those validated IDs, while a separate evaluator compares raw-plus-canonical facts against a blinded reference. Paid execution uses two explicit approval gates because downstream requests depend on paper-map outputs, then runs the frozen downstream batch without retries or human intervention.

**Tech Stack:** Python 3.14, Pydantic v2, OpenAI strict JSON schema, existing Docling/PyMuPDF ingestion, pytest, JSON/JSONL artifacts, SQLite-compatible application schema

## Global Constraints

- No paid API call without explicit human approval of its exact request hash and estimated token use.
- Generic production code must contain no NP-002, KUP, MC3, cKK-E12, QUANT, Cre, Ai14, fixed-six, or fixed-cell-type behavior.
- Preserve raw scientific wording and exact evidence IDs; canonical values are additional fields, never replacements.
- No fuzzy scientific matching and no exact number inferred from an unlabeled graph bar.
- Every text and visual result must echo a locally issued candidate ID and experiment ID; invented or changed IDs are rejected.
- Conflicting experiment assignments are quarantined and never silently overwritten.
- The independent reference key is never imported by ingestion, request construction, execution, validation, or merge modules.
- Reuse `full_paper_inventory.py`, `full_paper_contracts.py`, `full_paper_tasks.py`, selective-vision infrastructure, and existing evidence-envelope validation.
- The pilot runs three new open-full-text liver-focused papers first; expansion to five papers requires the three-paper thresholds to pass.
- After downstream approval, run frozen calls sequentially with zero automatic retries and zero unapproved repair calls; record failures and continue.
- Do not modify the final UI, nearest-neighbor, or COMET systems in this plan; emit database-ready extraction artifacts for the next milestone.

---

### Task 1: Raw and canonical scientific values

**Files:**
- Create: `src/extraction/application_normalization.py`
- Test: `tests/test_application_normalization.py`

**Interfaces:**
- Produces: `CanonicalFact(raw_value: str, canonical_value: str, normalization_rule: str, evidence_ids: tuple[str, ...])`
- Produces: `canonicalize_fact(field_name: str, raw_value: str, evidence_ids: Sequence[str]) -> CanonicalFact`
- Consumes: field names used by the existing compact and full-paper contracts.

- [ ] **Step 1: Write failing tests for only safe normalization**

```python
def test_ratio_format_is_canonical_but_raw_is_preserved():
    fact = canonicalize_fact("component_ratio", "50 : 38.5 : 1.5 : 10", ["E-1"])
    assert fact.raw_value == "50 : 38.5 : 1.5 : 10"
    assert fact.canonical_value == "50:38.5:1.5:10"
    assert fact.evidence_ids == ("E-1",)

def test_unknown_scientific_text_is_not_fuzzy_rewritten():
    fact = canonicalize_fact("formulation", "Novel LNP-X", ["E-2"])
    assert fact.canonical_value == "novel lnp-x"
    assert fact.normalization_rule == "casefold_whitespace"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv-rag/bin/python -m pytest tests/test_application_normalization.py -q`

Expected: FAIL because `application_normalization` does not exist.

- [ ] **Step 3: Implement a closed normalization registry**

```python
@dataclass(frozen=True)
class CanonicalFact:
    raw_value: str
    canonical_value: str
    normalization_rule: str
    evidence_ids: tuple[str, ...]

def canonicalize_fact(field_name: str, raw_value: str, evidence_ids: Sequence[str]) -> CanonicalFact:
    normalized = " ".join(raw_value.strip().casefold().split())
    rule = "casefold_whitespace"
    if field_name in {"component_ratio", "mass_ratio", "molar_ratio"}:
        normalized = re.sub(r"\s*:\s*", ":", normalized)
        rule = "ratio_spacing"
    return CanonicalFact(raw_value, normalized, rule, tuple(dict.fromkeys(evidence_ids)))
```

Add only reviewed aliases for assay names and units; do not add substring or
edit-distance matching.

- [ ] **Step 4: Run focused tests and the existing full-paper evaluator tests**

Run: `.venv-rag/bin/python -m pytest tests/test_application_normalization.py tests/test_full_paper_benchmark.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the independently testable normalization unit**

```bash
git add src/extraction/application_normalization.py tests/test_application_normalization.py
git commit -m "feat: preserve raw and canonical extraction facts"
```

### Task 2: Atomic outcome assertions in context responses

**Files:**
- Modify: `src/extraction/full_paper_contracts.py`
- Modify: `src/extraction/full_paper_tasks.py`
- Modify: `tests/test_full_paper_tasks.py`

**Interfaces:**
- Produces: `OutcomeAssertion(assertion_type, direction, subject, comparator, raw_text, value, unit, numeric_provenance, evidence_ids)`.
- Produces: `CandidateOutcomeBundle(candidate_id, experiment_id, foundational_outcomes, comparative_outcomes, exact_measurements)`.
- Extends: `build_context_response_schema(candidates)` with exact-keyed `candidate_outcomes` in addition to existing `context_candidate_accounting`.

- [ ] **Step 1: Add failing contract tests**

```python
def test_context_schema_requires_one_outcome_bundle_per_candidate():
    schema = build_context_response_schema([candidate("C-1"), candidate("C-2")])
    bundle = schema["properties"]["candidate_outcomes"]
    assert bundle["required"] == ["C-1", "C-2"]
    assert bundle["additionalProperties"] is False

def test_unlabeled_graph_number_cannot_be_exact():
    with pytest.raises(ValidationError):
        CandidateOutcomeBundle(
            candidate_id="C-1", experiment_id="EXP-1",
            foundational_outcomes=[], comparative_outcomes=[],
            exact_measurements=[OutcomeAssertion(
                assertion_type="measurement", direction="reported", subject="C-1",
                raw_text="bar appears near 40", value=40, unit="%",
                numeric_provenance="graph_estimated", evidence_ids=["FIG-2"]
            )]
        )
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-rag/bin/python -m pytest tests/test_full_paper_tasks.py -q`

Expected: FAIL because the new models and schema field do not exist.

- [ ] **Step 3: Add the strict models and dynamic exact-key schema**

Use these closed literals:

```python
AssertionType = Literal["foundational", "comparison", "measurement"]
Direction = Literal["present", "higher", "lower", "similar", "no_significant_difference", "reported"]
NumericProvenance = Literal["exact_reported", "graph_estimated", "not_reported"]
```

Require `value` only for `exact_reported`; require it to be absent for
`not_reported`. Keep `graph_estimated` available in provenance output but
exclude it from exact measurements and the pilot's exact-numeric score.

- [ ] **Step 4: Update prompt instructions and local validation**

Tell the model to decompose claims without inventing assertions. Validate that
each bundle key matches both its `candidate_id` and locally assigned
`experiment_id`, and that every cited evidence ID is within that candidate's
evidence envelope.

- [ ] **Step 5: Run focused and compatibility tests**

Run: `.venv-rag/bin/python -m pytest tests/test_full_paper_tasks.py tests/test_compact_contracts.py -q`

Expected: PASS with existing compact response behavior preserved.

- [ ] **Step 6: Commit the atomic outcome contract**

```bash
git add src/extraction/full_paper_contracts.py src/extraction/full_paper_tasks.py tests/test_full_paper_tasks.py
git commit -m "feat: require atomic candidate outcome assertions"
```

### Task 3: Generic stable experiment IDs and evidence-safe merge

**Files:**
- Modify: `src/extraction/full_paper_contracts.py`
- Modify: `src/extraction/full_paper_tasks.py`
- Create: `src/extraction/merge_full_paper_results.py`
- Create: `tests/test_merge_full_paper_results.py`

**Interfaces:**
- Produces: `stable_experiment_id(paper_id: str, candidate: ContextCandidate) -> str`.
- Produces: `merge_full_paper_results(paper_map: Mapping[str, Any], context_results: Sequence[Mapping[str, Any]], visual_results: Sequence[Mapping[str, Any]]) -> MergeResult`.
- `MergeResult` contains `shared_facts`, `experiments`, `quarantined_conflicts`, and `validation_findings`.

- [ ] **Step 1: Write failing join tests**

```python
def test_text_and_visual_facts_join_only_on_issued_experiment_id():
    result = merge_full_paper_results(paper_map, [text_for("EXP-A")], [vision_for("EXP-A")])
    assert len(result.experiments) == 1
    assert result.experiments[0].experiment_id == "EXP-A"

def test_changed_experiment_id_is_rejected_not_reassigned():
    result = merge_full_paper_results(paper_map, [text_for("EXP-A")], [vision_for("EXP-Z")])
    assert result.experiments[0].experiment_id == "EXP-A"
    assert result.quarantined_conflicts[0].code == "unknown_experiment_id"
```

Also cover shared formulation metadata used by multiple experiments and two
experiments that differ only by dose or timepoint.

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-rag/bin/python -m pytest tests/test_merge_full_paper_results.py -q`

Expected: FAIL because the generic merger does not exist.

- [ ] **Step 3: Assign deterministic IDs before request creation**

Compute the ID from the paper ID plus the candidate's already-validated
scientific identity tuple and evidence identity. Add `experiment_id` to
`ContextCandidate`; include it in every context and visual task. The LLM is
never allowed to create this value.

- [ ] **Step 4: Implement non-destructive merge semantics**

Merge identical facts by `(experiment_id, field_name, canonical_value)` while
unioning evidence IDs and preserving every raw value. Quarantine unknown IDs,
candidate/experiment mismatches, and conflicting canonical values. Do not
choose a winner silently.

- [ ] **Step 5: Replay NP-002 saved responses for free**

Run: `.venv-rag/bin/python -m pytest tests/test_merge_full_paper_results.py tests/test_np002_selective_outcomes.py -q`

Then run the existing NP-002 replay entry point with API keys blank and confirm
that no provider call occurs, all known valid visual findings join their issued
experiment IDs, and wrong-arm links remain zero.

- [ ] **Step 6: Commit the generalized merger**

```bash
git add src/extraction/full_paper_contracts.py src/extraction/full_paper_tasks.py src/extraction/merge_full_paper_results.py tests/test_merge_full_paper_results.py
git commit -m "feat: merge extraction facts by issued experiment id"
```

### Task 4: Application-required information evaluator

**Files:**
- Create: `src/extraction/evaluate_application_requirements.py`
- Create: `tests/test_evaluate_application_requirements.py`

**Interfaces:**
- Produces: `evaluate_application_requirements(extraction: Mapping[str, Any], reference: Mapping[str, Any]) -> ApplicationScore`.
- `ApplicationScore` contains category numerators/denominators, per-paper recall, overall recall, precision, wrong-arm links, invented IDs, unsupported numerics, and missing reference IDs.

- [ ] **Step 1: Write failing scoring tests**

```python
def test_equivalent_ratio_format_matches_without_losing_raw_text():
    score = evaluate_application_requirements(extraction_with("50 : 38.5 : 1.5 : 10"), reference_with("50:38.5:1.5:10"))
    assert score.categories["formulation"].recall == 1.0

def test_unreported_numeric_fact_is_not_in_denominator():
    score = evaluate_application_requirements(extraction_without_number(), reference_marked_not_reported())
    assert score.categories["exact_numeric"].denominator == 0
```

Add tests proving that specific supported comparisons match compatible
reference assertions, contradictions do not match, and an estimated graph
value cannot satisfy an exact-numeric expectation.

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-rag/bin/python -m pytest tests/test_evaluate_application_requirements.py -q`

Expected: FAIL because the evaluator does not exist.

- [ ] **Step 3: Implement category scoring and safety counts**

Use explicit reference IDs and controlled aliases. Report formulation,
payload/administration, biological model, assay, qualitative outcome, exact
numeric, and provenance categories separately. Compute both aggregate and
per-paper scores.

- [ ] **Step 4: Add a reference-leak test**

Scan production extraction modules and serialized prompts for
`data/benchmarks/application_pilot`; fail if the path or reference IDs appear.

- [ ] **Step 5: Run the evaluator and existing benchmark tests**

Run: `.venv-rag/bin/python -m pytest tests/test_evaluate_application_requirements.py tests/test_full_paper_benchmark.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the application evaluator**

```bash
git add src/extraction/evaluate_application_requirements.py tests/test_evaluate_application_requirements.py
git commit -m "feat: score application-required extraction recall"
```

### Task 5: Two-gate pilot preparation and uninterrupted runner

**Files:**
- Create: `src/extraction/prepare_application_pilot.py`
- Create: `src/extraction/run_application_pilot.py`
- Create: `tests/test_application_pilot_runner.py`

**Interfaces:**
- Produces: `prepare_map_gate(papers: Sequence[PilotPaper], output_root: Path) -> ApprovalManifest`.
- Produces: `prepare_downstream_gate(map_artifacts: Sequence[Path], output_root: Path) -> ApprovalManifest`.
- Produces: `run_approved_manifest(manifest_path: Path, approval_hash: str) -> RunSummary`.
- `ApprovalManifest` freezes request hashes, models, estimated input tokens, maximum output tokens, call count, and total estimated tokens.
- Define `PilotPaper`, `ApprovalRequest`, `ApprovalManifest`, and `RunSummary` as strict Pydantic models in `prepare_application_pilot.py`; import those models in the runner rather than duplicating their fields.

- [ ] **Step 1: Write failing safety tests**

```python
def test_preparation_makes_zero_provider_calls(fake_provider):
    manifest = prepare_map_gate(papers, tmp_path)
    assert fake_provider.calls == []
    assert manifest.call_count == 3

def test_runner_continues_after_one_failed_call(fake_provider):
    fake_provider.fail_request("REQ-2")
    summary = run_approved_manifest(manifest_path, manifest_hash)
    assert summary.attempted_request_ids == ["REQ-1", "REQ-2", "REQ-3"]
    assert summary.retry_count == 0
```

Also test that an incorrect approval hash, altered request file, extra request,
or missing exact token estimate fails before the first provider call.

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-rag/bin/python -m pytest tests/test_application_pilot_runner.py -q`

Expected: FAIL because the preparation and runner modules do not exist.

- [ ] **Step 3: Implement zero-call preparation**

Reuse existing exact-request hashing and token estimation. Gate A may contain
only the three paper-map calls. After their validated responses exist, Gate B
freezes all context and selective-vision requests.

- [ ] **Step 4: Implement the bounded sequential runner**

The runner may execute only request files listed in the approved manifest. It
runs once per item, writes response/error artifacts atomically, never retries,
never creates a repair task, and continues after individual failures.

- [ ] **Step 5: Run focused tests**

Run: `.venv-rag/bin/python -m pytest tests/test_application_pilot_runner.py tests/test_full_paper_tasks.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the approval-safe runner**

```bash
git add src/extraction/prepare_application_pilot.py src/extraction/run_application_pilot.py tests/test_application_pilot_runner.py
git commit -m "feat: add approval-gated extraction pilot runner"
```

### Task 6: Select and prepare three new liver-focused papers

**Files:**
- Create: `data/benchmarks/application_pilot/pilot_manifest.json`
- Create at runtime: `data/benchmarks/application_pilot/{paper_id}.json` for each of the three IDs frozen in `pilot_manifest.json`
- Create at runtime: `data/staging/extraction/application_pilot/{paper_id}/inventory.json`

**Interfaces:**
- Consumes: open-full-text PDFs or publisher XML/HTML plus `build_full_paper_evidence(...)`.
- Produces: three independent reference files containing atomic expected facts and source locations, excluded from every extraction request.

- [ ] **Step 1: Select papers using fixed eligibility rules**

Choose three non-gold papers that are open full text, liver-focused, report an
LNP formulation and biological outcome, and collectively contain text, table,
and figure evidence. Record DOI/PMCID, source URL, publication license, and
SHA-256 source hash.

- [ ] **Step 2: Ingest all three papers locally**

Run the existing full-paper inventory builder and verify its category report
contains formulation, payload, biological model, recipient/organ, and outcome
evidence. Missing categories block that paper before any call and trigger
selection of a replacement paper.

- [ ] **Step 3: Create a lightweight blinded reference**

For each paper, record only facts explicitly supported by a page, paragraph,
table cell, caption, or printed figure label. Mark numeric facts as
`exact_reported` or `not_reported`; do not transcribe values from bar height.

- [ ] **Step 4: Sanity-check the experiment inventories**

Compare each locally detected provisional experiment against the source for
formulation, payload, dose, route, model, recipient, and timepoint. Correct
inventory-construction defects in generic code, not by editing output IDs to
match the reference.

- [ ] **Step 5: Run the gold-leak test and commit only benchmark metadata**

Run: `.venv-rag/bin/python -m pytest tests/test_evaluate_application_requirements.py -q`

Expected: PASS with no reference content in production prompts.

```bash
git add data/benchmarks/application_pilot
git commit -m "test: add blinded three-paper extraction pilot"
```

### Task 7: Gate A — prepare and show the three paper-map calls

**Files:**
- Create through execution: `data/staging/extraction/application_pilot/map_gate/manifest.json`
- Create through execution: `reports/extraction/application_pilot_map_preflight.md`

**Interfaces:**
- Consumes: three validated local evidence inventories.
- Produces: exact paper-map request hashes, per-call input estimates, output caps, and total estimated tokens.

- [ ] **Step 1: Run map-gate preparation with API keys disabled**

Verify the manifest contains exactly three requests and provider call count is
zero.

- [ ] **Step 2: Run unit and integration verification**

Run: `.venv-rag/bin/python -m pytest tests/test_application_normalization.py tests/test_full_paper_tasks.py tests/test_merge_full_paper_results.py tests/test_evaluate_application_requirements.py tests/test_application_pilot_runner.py -q`

Expected: PASS.

- [ ] **Step 3: Show the human-readable approval package and stop**

Report each paper, exact request hash, estimated input tokens, maximum output
tokens, total estimated tokens, and price estimate if the configured model's
current price is available. Do not execute Gate A without explicit approval.

### Task 8: Gate B — freeze downstream calls, run without interruption, and score

**Files:**
- Create through execution: `data/staging/extraction/application_pilot/downstream_gate/manifest.json`
- Create through execution: `data/staging/extraction/application_pilot/results/`
- Create through execution: `reports/extraction/application_pilot_final.json`
- Create through execution: `reports/extraction/application_pilot_final.html`

**Interfaces:**
- Consumes: three validated map responses and the approved Gate B manifest.
- Produces: merged database-ready paper/formulation/experiment/outcome/evidence records and aggregate/per-paper scores.

- [ ] **Step 1: After Gate A execution, validate all paper-map responses**

Reject invented evidence IDs and incomplete anchor accounting. Record a failed
paper and continue preparing the other papers; do not issue an automatic map
retry.

- [ ] **Step 2: Build all context and selective-vision tasks**

Assign stable experiment IDs, project candidate-specific evidence envelopes,
render the necessary figure/table crops, and freeze every downstream request.

- [ ] **Step 3: Show Gate B and stop for one combined approval**

Report exact call count, per-call hashes and token estimates, total tokens, and
which experiment IDs each call may update.

- [ ] **Step 4: Execute the approved manifest sequentially**

Run every frozen call once. Continue after validation or provider failure.
Create no retries and no repair calls.

- [ ] **Step 5: Merge, score, and apply the acceptance gate**

Produce per-paper and aggregate category recall. The pilot passes only if core
setup is at least 90%, formulation components/ratios at least 90%, qualitative
outcomes at least 80%, exact numerics where reported at least 80%, overall
required information at least 80%, and wrong-arm links, invented IDs, and
unsupported exact numerics are all zero.

- [ ] **Step 6: Verify database-ready output without loading production data**

Validate required paper, formulation, experiment, outcome, and evidence fields
against `src/schema.sql`. Keep raw values and provenance in the extraction
artifact even where the current SQL schema will later need an additive
migration.

- [ ] **Step 7: Produce the decision report**

If the pilot passes, recommend freezing the extractor and starting bulk
database loading plus the UI. If it narrowly misses due to a local
normalization or routing defect, replay saved responses after one bounded fix.
If it repeats a fundamental extraction failure, stop redesigning this
benchmark and move to multi-source database/UI work with confidence flags and
review queues.

### Task 9: Final verification and implementation review

**Files:**
- Review: all files modified by Tasks 1–8

**Interfaces:**
- Consumes: the full feature diff and test results.
- Produces: a review finding list and verified handoff state.

- [ ] **Step 1: Run the full extraction test suite with paid keys disabled**

Run: `OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest tests/test_application_normalization.py tests/test_full_paper_tasks.py tests/test_merge_full_paper_results.py tests/test_evaluate_application_requirements.py tests/test_application_pilot_runner.py -q`

Expected: PASS and zero provider calls.

- [ ] **Step 2: Inspect the diff for hardcoded paper facts and secrets**

Run: `rg -n "NP-002|KUP|MC3|cKK-E12|QUANT|Ai14|OPENAI_API_KEY|SENSENOVA_API_KEY" src/extraction tests`

Expected: paper-specific values occur only in explicit benchmark/replay tests;
no key values or `.env` contents appear.

- [ ] **Step 3: Request code review**

Use `superpowers:requesting-code-review` on the implementation diff. Address
high-confidence correctness or safety findings, rerun the relevant tests, and
record any intentionally deferred scope.

- [ ] **Step 4: Verify before declaring completion**

Use `superpowers:verification-before-completion`, inspect `git status`, and
report test evidence, paid-call artifacts, remaining failures, and the next
database/UI milestone without staging unrelated run artifacts.
