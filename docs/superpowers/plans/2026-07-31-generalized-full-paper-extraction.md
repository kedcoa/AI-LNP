# Generalized Full-Paper Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare a gold-blind, full-paper NP-002 benchmark using reusable shared-paper and experiment-level inventories, then report exact paid-call and token estimates before execution.

**Architecture:** Build generic, section-aware paper evidence and inventory contracts; create one shared paper-map request followed by token-packed context requests with mandatory candidate accounting; merge and score outputs against a separately loaded answer key only after extraction.

**Tech Stack:** Python 3.14, Pydantic, PyMuPDF, OpenAI strict JSON schema, pytest, JSON artifacts

## Global Constraints

- Generic modules must contain no NP-002-specific scientific names, fixed candidate count, or fixed cell types.
- The answer key must never be imported by ingestion, request building, validation, or execution modules.
- Reuse existing compact contracts, exact-request hashing, evidence-envelope validation, and selective-repair infrastructure.
- No paid API calls in this plan; stop after exact preflight preparation.

---

### Task 1: Generic full-paper evidence inventory

**Files:**
- Create: `src/extraction/full_paper_inventory.py`
- Test: `tests/test_full_paper_inventory.py`

**Interfaces:**
- `build_full_paper_evidence(paper_id: str, source_path: Path, *, docling_path: Path | None = None) -> FullPaperEvidenceInventory`
- Produces section-aware evidence with stable IDs, pages, headings, text, and generic retrieval tags.

- [ ] Write failing synthetic HTML, Docling, and PDF-fallback tests proving that formulation methods, ratios, payload/model/route/cell/outcome passages are retained without domain-name hardcoding.
- [ ] Run the tests and verify RED.
- [ ] Preserve HTML heading hierarchy and existing Docling structural labels; use raw PDF blocks only as conservatively retained unsectioned/page evidence.
- [ ] Implement block normalization, stable evidence hashing, generic tag rules, and category coverage diagnostics without text-based heading inference.
- [ ] Run the tests and verify GREEN.
- [ ] Commit `feat: build generic full-paper evidence inventory`.

### Task 2: Shared paper-map and generic arm contracts

**Files:**
- Create: `src/extraction/full_paper_contracts.py`
- Create: `src/extraction/full_paper_tasks.py`
- Test: `tests/test_full_paper_tasks.py`

**Interfaces:**
- `build_paper_map_request(inventory, model, token_budget) -> PreparedRequest`
- `build_context_tasks(paper_map, inventory, token_budget) -> list[ContextTask]`
- `validate_context_response(response, task) -> ValidationReport`

- [ ] Write failing tests with unrelated synthetic formulations/cells and variable candidate counts.
- [ ] Require exact anchor accounting in the map schema and exact arm accounting in each context schema.
- [ ] Implement data-driven arm identity fields and evidence-backed pairing; forbid unsupported cross-products.
- [ ] Implement token-driven packing by compatible recipient context.
- [ ] Reuse candidate-specific evidence projection and shared-record merge semantics.
- [ ] Run focused tests and commit `feat: prepare generic full-paper extraction tasks`.

### Task 3: Hidden answer key and evaluator

**Files:**
- Create: `data/benchmarks/full_paper/NP-002.json`
- Create: `src/extraction/evaluate_full_paper_benchmark.py`
- Test: `tests/test_full_paper_benchmark.py`

**Interfaces:**
- `evaluate(extraction_dir: Path, gold_path: Path) -> FullPaperScore`

- [ ] Create a human-audited atomic NP-002 reference covering shared formulations and all liver-cell contexts.
- [ ] Add source evidence for each gold item, including the 50:38.5:1.5:10 molar ratio and 10:1 lipid:nucleic-acid mass ratio.
- [ ] Write failing evaluator tests for recall, precision, complete-arm recall, wrong links, unsupported inventions, aliases, and missing IDs.
- [ ] Add a static gold-leak test that rejects production imports or prompt references to `data/benchmarks/full_paper`.
- [ ] Implement the evaluator and run focused tests.
- [ ] Commit `feat: score generalized full-paper extraction`.

### Task 4: Generic zero-call orchestrator

**Files:**
- Create: `src/extraction/prepare_full_paper_extraction.py`
- Test: `tests/test_prepare_full_paper_extraction.py`

**Interfaces:**
- `prepare(paper_id, pdf_path, model, output_root) -> PreparationManifest`

- [ ] Write failing tests proving preparation makes zero provider calls, hashes exact requests, and reports task/candidate/token counts.
- [ ] Implement ingestion → shared-map preflight.
- [ ] Implement a continuation boundary that accepts a validated paper-map artifact and prepares context calls without accessing gold.
- [ ] Reuse the existing explicit-approval and one-call execution boundary for every prepared request.
- [ ] Run focused tests and commit `feat: orchestrate generalized full-paper preflight`.

### Task 5: NP-002 gold-blind preparation

**Files:**
- Create through execution: `data/staging/extraction/full_paper_v1/NP-002/`
- Read: `data/staging/new_papers/NP-002/PMC6816632.pdf`

- [ ] Run the generic ingestion with `paper_id=NP-002`.
- [ ] Verify that global methods evidence includes formulation components, molar ratio, and lipid:nucleic-acid ratio.
- [ ] Prepare the shared paper-map call and report its exact input estimate and hash.
- [ ] Because context tasks depend on the returned map, document the projected context-call range and configured per-task budget.
- [ ] Stop for human approval of the first paid map call.

### Task 6: Post-map continuation

**Files:**
- Create through execution after approval: context task requests and final score artifacts

- [ ] Execute exactly the approved map call.
- [ ] Validate the map locally and prepare all packed context requests.
- [ ] Show exact context call count and total token estimate; pause for approval.
- [ ] Execute approved context calls sequentially.
- [ ] Merge, evaluate against the hidden key, and report whether overall recall exceeds 72%.
- [ ] Prepare selective repairs only for unresolved gold-blind candidates and require separate approval.
