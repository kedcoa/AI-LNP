# Target-Scope Rescreen and ChatPDF Gap Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct organ-level versus cell-level delivery interpretation for the 10 PDF-ready papers, rebuild readiness without treating an absent target cell as a failure when a supported target/recipient organ exists, and run a provenance-gated ChatPDF pilot on GP-002, GP-004, and GP-005.

**Architecture:** Preserve the lossless source ledger and add an explicit target-scope layer that separates intended target cell, target/recipient organ, and observed transfected cell. Re-screen existing evidence into staged candidate corrections, rebuild and audit a fresh SQLite candidate, and only then promote it. ChatPDF remains an independent candidate generator: its JSON and page references go into staging and a comparison report, never directly into the authoritative database.

**Tech Stack:** Python 3.14, SQLite, Pydantic/dataclass import contracts, pytest, local PDF/XML evidence, ChatPDF REST API, Streamlit.

## Global Constraints

- Do not use CodeRabbit CLI.
- Do not make a ChatPDF request until `CHATPDF_API_KEY` is present and the exact free-plan request budget is recorded.
- The pilot budget is at most 74 uploaded PDF pages and 12 messages: GP-002 (19 pages), GP-004 main plus three supplements (38 pages), and GP-005 (17 pages).
- Never infer intentional cell targeting merely from biodistribution, uptake, staining, or expression.
- Every promoted value must retain paper, PDF, page, quotation, arm, field, extraction method, and validation status.
- Use `null`/missing for absent facts; never turn `not_reported`, `unknown`, or `NA` into scientific values.
- Keep one row per true intervention/model/dose/route/timepoint arm and keep multiple outcomes in an array/cell.
- ChatPDF output cannot overwrite SQLite directly.
- Paid calls or calls beyond the stated free-plan pilot require a new explicit approval.

---

### Task 1: Define target-scope semantics and readiness rules

**Files:**
- Create: `src/database/target_scope.py`
- Modify: `src/database/status.py`
- Modify: `src/schema.sql`
- Modify: `src/database/migrations.py`
- Test: `tests/test_target_scope.py`
- Test: `tests/test_database_status.py`

**Interfaces:**
- Produces: `TargetScope(intended_target_cell, target_or_recipient_organ, observed_transfected_cell)`.
- Produces: `classify_target_statement(text: str) -> TargetStatementCandidate`.
- Produces: `has_supported_delivery_destination(connection, experiment_id) -> bool`.
- Readiness consumes: a supported intended target cell **or** supported target/recipient organ.

- [ ] **Step 1: Write failing semantic tests**

```python
def test_observed_expression_is_not_intentional_targeting():
    candidate = classify_target_statement(
        "Transfection of hepatocytes was widespread in most livers."
    )
    assert candidate.intended_target_cell is None
    assert candidate.target_or_recipient_organ == "liver"
    assert candidate.observed_transfected_cell == "hepatocyte"

def test_systemic_liver_scan_is_complete_without_target_cell(connection, arm_id):
    set_target_scope(connection, arm_id, target_or_recipient_organ="liver")
    result = evaluate_arm_status(connection, arm_id)
    assert "cell_type" not in result.missing_fields
    assert "delivery_destination" not in result.missing_fields
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_target_scope.py tests/test_database_status.py`

- [ ] **Step 3: Add non-destructive schema columns**

Add nullable `intended_target_cell`, `target_or_recipient_organ`, and `observed_transfected_cell` columns to `experiment`; increment `MIGRATION_VERSION`; preserve `cell_type` and `tissue_or_organ` for backward compatibility.

- [ ] **Step 4: Implement conservative statement classification**

Classify `target/designed/ligand-directed` language as intentional targeting, `delivered to/accumulated in/scanned in` language as organ destination, and `expression/staining/uptake/transfection in` language as observed cell. Return an ambiguous candidate instead of filling competing interpretations.

- [ ] **Step 5: Change completeness logic**

Replace the mandatory `cell_type` gate with `delivery_destination`, satisfied by a supported intended target cell or target/recipient organ. Keep observed cell optional and keep formulation, ratio, species, payload, dose, route, outcome, and timepoint mandatory.

- [ ] **Step 6: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_target_scope.py tests/test_database_status.py tests/test_database_migrations.py`

---

### Task 2: Re-screen target evidence for all 10 PDF-ready papers

**Files:**
- Create: `src/database/rescreen_target_scope.py`
- Create: `tests/test_rescreen_target_scope.py`
- Create during execution: `data/staging/database/target_scope_rescreen_v1/<paper_id>.json`
- Create during execution: `reports/database/target_scope_rescreen_v1.json`
- Create during execution: `reports/database/target_scope_rescreen_v1.md`

**Interfaces:**
- Consumes: registered `source_artifact`, `evidence`, `source_fact`, local PDF/XML paths, and canonical arms.
- Produces: `TargetScopeCandidate` records with `paper_id`, `experiment_id`, three target-scope fields, evidence IDs, PDF path, page, quote, and disposition.

- [ ] **Step 1: Write failing coverage and abstention tests**

```python
def test_gp002_widespread_hepatocyte_statement_separates_organ_and_observation():
    result = rescreen_paper("GP-002", fixture_database, fixture_corpus)
    assert any(row.target_or_recipient_organ == "liver" for row in result.candidates)
    assert any(row.observed_transfected_cell == "hepatocyte" for row in result.candidates)
    assert not any(row.intended_target_cell == "hepatocyte" for row in result.candidates)

def test_rescreen_abstains_when_quote_cannot_be_linked_to_one_arm():
    result = resolve_candidate(ambiguous_multi_arm_quote)
    assert result.disposition == "unresolved"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_rescreen_target_scope.py`

- [ ] **Step 3: Build the evidence-first rescreener**

Search registered quotes and local full text for liver/cell targeting, delivery, uptake, staining, expression, transfection, and biodistribution statements. Resolve a candidate only when the formulation/intervention/model/dose/route/timepoint context identifies one canonical arm or an explicitly shared protocol.

- [ ] **Step 4: Re-screen these papers**

Run against `GP-001` through `GP-009` and `NP-002`. Report per paper: intentional target cells, target/recipient organs, observed cells, safely resolved fields, ambiguous fields, and remaining missing delivery destinations.

- [ ] **Step 5: Add an arm-grain audit**

Flag likely duplicate arms only when formulation, payload, biological model, dose, route, and timepoint match or share the same explicit intervention entity. Specifically test whether GP-002 fibrosis and cirrhosis are subgroups/outcomes of one Mdr2 administration rather than separate administration arms.

- [ ] **Step 6: Run focused tests and inspect the report**

Run: `.venv/bin/python -m pytest -q tests/test_rescreen_target_scope.py tests/test_accepted_graph_arm_projection.py`

---

### Task 3: Rebuild and verify the corrected SQLite candidate

**Files:**
- Modify: `src/database/run_current_corpus_import.py`
- Modify: `src/database/report_current_database.py`
- Modify: `src/ui/evidence_browser_service.py`
- Modify: `src/ui/evidence_browser_app.py`
- Test: `tests/test_current_corpus_import.py`
- Test: `tests/test_evidence_browser_service.py`
- Create during execution: `reports/database/target_scope_candidate_audit.json`

**Interfaces:**
- Consumes: approved target-scope candidate corrections from Task 2.
- Produces: a fresh SQLite candidate and updated combined table columns for target organ, intended target cell, and observed cell.

- [ ] **Step 1: Write failing import and UI tests**

```python
def test_organ_level_arm_is_general_ready_without_intended_target_cell(database):
    arm = load_gp002_healthy_arm(database)
    assert arm.target_or_recipient_organ == "liver"
    assert arm.intended_target_cell is None
    assert arm.observed_transfected_cell == "hepatocyte"
    assert arm.general_usable is True

def test_combined_table_displays_target_dimensions_separately(database):
    row = load_combined_gp002_row(database)
    assert row["Target / recipient organ"] == "liver"
    assert row["Intended target cell"] == "NA"
    assert row["Observed transfected cell"] == "hepatocyte"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_current_corpus_import.py tests/test_evidence_browser_service.py`

- [ ] **Step 3: Import target-scope candidates without deleting source facts**

Register the re-screen report as a source artifact, attach every promoted field to exact evidence, and leave ambiguous candidates in the automatic-resolution queue.

- [ ] **Step 4: Rebuild a fresh candidate database**

Use `rebuild_database(...)` with a new `/tmp/ai-lnp-target-scope-v1.db` target. Do not mutate the authoritative database in place.

- [ ] **Step 5: Audit scientific counts and readiness**

Require `PRAGMA integrity_check = ok`, zero foreign-key violations, zero silent fact/evidence omissions, zero readiness inconsistencies, and an explicit before/after table for every arm whose readiness changed.

- [ ] **Step 6: Promote only after verified comparison**

Back up the authoritative database, atomically promote the verified candidate, regenerate the final reports, and refresh the local Streamlit browser.

---

### Task 4: Implement a bounded ChatPDF client and strict response contract

**Files:**
- Create: `src/extraction/chatpdf_client.py`
- Create: `src/extraction/chatpdf_contracts.py`
- Create: `tests/test_chatpdf_client.py`
- Create: `tests/fixtures/chatpdf/`

**Interfaces:**
- Produces: `ChatPdfClient.add_file(path: Path) -> str`.
- Produces: `ChatPdfClient.ask(source_id: str, prompt: str, reference_sources: bool = True) -> ChatPdfResponse`.
- Produces: `ChatPdfPaperExtraction` with arms, outcomes, missing fields, page references, and quotations.

- [ ] **Step 1: Write fake-client tests**

Test successful upload, authentication failure, quota failure, invalid JSON, absent references, timeouts without silent retry, and deletion of pilot sources.

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_chatpdf_client.py`

- [ ] **Step 3: Implement the minimal REST client**

Read only `CHATPDF_API_KEY`; upload one PDF at a time to `/v1/sources/add-file`; ask `/v1/chats/message` with `referenceSources: true`; record request hashes and response hashes; never log the API key.

- [ ] **Step 4: Enforce the strict extraction contract**

Reject prose-wrapped JSON, unknown fields, missing arm IDs, unsupported populated fields, missing page references, and outcomes not nested under an arm. Preserve rejected responses for audit without importing them.

- [ ] **Step 5: Run client tests**

Run: `.venv/bin/python -m pytest -q tests/test_chatpdf_client.py`

---

### Task 5: Run the GP-002/GP-004/GP-005 ChatPDF gap pilot

**Files:**
- Create: `src/extraction/run_chatpdf_gap_pilot.py`
- Create: `tests/test_chatpdf_gap_pilot.py`
- Create during execution: `data/staging/extraction/chatpdf_gap_pilot_v1/`
- Create during execution: `reports/extraction/chatpdf_gap_pilot_v1.json`
- Create during execution: `reports/extraction/chatpdf_gap_pilot_v1.md`

**Interfaces:**
- Consumes: the strict SQLite missing-field list and six PDF files totaling 74 pages.
- Produces: full extraction candidates, targeted gap candidates, and a field-by-field comparison; it produces no authoritative DB writes.

- [ ] **Step 1: Write the exact prompt fixture**

The prompt must request JSON only; one arm per formulation/intervention/model/dose/route/timepoint; outcomes nested in the arm; separate target organ, intended target cell, and observed cell; `null` when absent; shared-protocol scope; and page/quote evidence for every populated field.

- [ ] **Step 2: Write dry-run budget tests**

Assert that the run contains exactly six uploads, no more than 74 pages, and no more than 12 messages. Refuse dispatch when the API key is absent or the budget is exceeded.

- [ ] **Step 3: Run the dry-run preflight**

Produce request hashes and the six-file inventory without uploading. Present the exact hashes before dispatch.

- [ ] **Step 4: Dispatch the approved free-plan pilot**

For each PDF, send one complete extraction prompt and, only when necessary, one targeted missing-field follow-up. Do not retry a failed request silently.

- [ ] **Step 5: Validate page evidence locally**

Extract each cited page from the original local PDF and require the cited quotation or a normalized exact substring match. Mark unsupported fields rejected and ambiguous arm links unresolved.

- [ ] **Step 6: Generate the comparison report**

Report fields recovered, fields still absent, conflicting values, arm merges/splits proposed, supported versus unsupported ChatPDF claims, pages/messages consumed, and whether GP-002/GP-005 shared setup was recovered.

---

### Task 6: Decide whether ChatPDF belongs in the pipeline

**Files:**
- Create: `reports/extraction/chatpdf_gap_pilot_decision.md`
- Modify only if approved after pilot: `config/database/current_corpus_v1.json`

**Interfaces:**
- Consumes: the validated pilot comparison from Task 5.
- Produces: `adopt_as_gap_filler`, `adopt_as_independent_extractor`, or `reject` with evidence.

- [ ] **Step 1: Apply objective gates**

Require zero unsupported claims eligible for promotion, 100% provenance retention for accepted fields, successful recovery of at least one known source-supported gap, and no incorrect arm merge.

- [ ] **Step 2: Classify the integration**

Choose gap filler when targeted recovery is reliable but full arm reconstruction is not; choose independent extractor only when full arm grain and shared setup are reliable; otherwise reject it.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`

- [ ] **Step 4: Report without silently changing the authoritative DB**

Show exactly which candidate values could be promoted and wait for explicit approval before any ChatPDF-derived value enters the final SQLite database.

