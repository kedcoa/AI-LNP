# Read-Only Evidence Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and launch a simple Streamlit browser that shows every paper, one row per LNP formulation, explicit `NA` values, linked formulation/arm/outcome evidence, and automatic-resolution issues from the authoritative SQLite database.

**Architecture:** Add a dedicated read-only service in `src/ui/evidence_browser_service.py` that converts canonical SQLite rows and evidence links into immutable display models. Add a separate Streamlit entry point in `src/ui/evidence_browser_app.py`; it calls only the service boundary and cannot write to SQLite. Tests cover query correctness, one-row-per-formulation behavior, evidence provenance, missing values, screening-only papers, rendering, and byte-for-byte database immutability.

**Tech Stack:** Python 3.14, SQLite, dataclasses, Streamlit, pytest, `streamlit.testing.v1.AppTest`.

## Global Constraints

- The application is read-only and separate from the human-review application.
- Open SQLite with `mode=ro` and set `PRAGMA query_only=ON`.
- Use the canonical database at `/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db` in production.
- Preserve exactly these formulation columns in order: `lnp_name`, `chemical_formulation_total`, `lnp_molar_ratio`, `ionizable_lipid`, `helper_lipid`, `cholesterol`, `peg_lipid`, `others`.
- Display missing values as `NA`; never write `NA` into SQLite.
- Show only persisted evidence links and never infer new scientific relationships.
- Display unresolved work as automatic-resolution issues, not human-verification requirements.
- Keep nearest-neighbor and COMET eligibility separate.
- Do not make provider or network calls.

---

### Task 1: Read-only browser service and display contracts

**Files:**
- Create: `src/ui/evidence_browser_service.py`
- Create: `tests/test_evidence_browser_service.py`

**Interfaces:**
- Produces: `FORMULATION_COLUMNS: tuple[str, ...]`.
- Produces: immutable `BrowserPaper`, `BrowserCounts`, `BrowserEvidence`, `BrowserField`, `BrowserOutcome`, `BrowserArm`, `BrowserFormulation`, and `PaperBrowserView` dataclasses.
- Produces: `browser_database_path() -> Path`, `list_browser_papers() -> tuple[BrowserPaper, ...]`, and `load_paper_browser(paper_id: int) -> PaperBrowserView`.
- Consumers monkeypatch `browser_database_path` for tests; production callers cannot supply an arbitrary database path.

- [ ] **Step 1: Write failing service tests**

Create a temporary migrated database fixture containing:

- one paper with two formulations;
- two arms attached to the first formulation;
- one outcome;
- formulation, component, arm, and outcome field-evidence links;
- one explicit automatic-resolution issue; and
- one screening-only paper with no scientific rows.

Assert:

```python
assert FORMULATION_COLUMNS == (
    "lnp_name", "chemical_formulation_total", "lnp_molar_ratio",
    "ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid", "others",
)
assert len(view.formulations) == 2
assert len(view.formulations[0].arms) == 2
assert view.formulations[0].cells["helper_lipid"].display_value == "DSPC"
assert view.formulations[1].cells["lnp_molar_ratio"].display_value == "NA"
assert view.formulations[0].cells["helper_lipid"].evidence[0].text == "DSPC evidence"
assert screening_view.formulations == ()
```

Also hash the fixture before and after every service call and assert the bytes are unchanged.

- [ ] **Step 2: Run service tests and confirm the missing module failure**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_evidence_browser_service.py
```

Expected: FAIL because `src.ui.evidence_browser_service` does not exist.

- [ ] **Step 3: Implement the immutable display models and read-only connection**

Implement:

```python
FORMULATION_COLUMNS = (
    "lnp_name", "chemical_formulation_total", "lnp_molar_ratio",
    "ionizable_lipid", "helper_lipid", "cholesterol", "peg_lipid", "others",
)

def _connect() -> sqlite3.Connection:
    path = browser_database_path().resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection
```

Define `BrowserField` with `value: str | None`, `display_value: str`, and `evidence: tuple[BrowserEvidence, ...]`. `display_value` is `NA` only when `value` is missing or blank.

- [ ] **Step 4: Implement paper inventory and access-link loading**

Load paper metadata, counts, DOI/PubMed/PMC/source links, import status, and the first existing local HTML/XML/PDF contributor path. Omit unavailable links.

- [ ] **Step 5: Implement formulation and component evidence projection**

Load one canonical formulation row per `formulation.formulation_id`. Build the approved eight cells from formulation columns and component roles. Join persisted evidence only through `import_field_evidence`; aggregate component evidence for the appropriate wide cell. Preserve multiple evidence excerpts as separate `BrowserEvidence` records.

- [ ] **Step 6: Implement arm, outcome, eligibility, and issue loading**

For each formulation, load every linked experiment independently. Load arm fields, its `arm_assessment`, both `eligibility_result` profiles, linked outcomes, outcome evidence, and `import_review` rows. Do not concatenate different arms into formulation cells.

- [ ] **Step 7: Run service tests**

Run the Task 1 test command. Expected: PASS.

- [ ] **Step 8: Commit the service boundary**

```bash
git add src/ui/evidence_browser_service.py tests/test_evidence_browser_service.py
git commit -m "feat: add read-only evidence browser service"
```

---

### Task 2: Streamlit paper and formulation browser

**Files:**
- Create: `src/ui/evidence_browser_app.py`
- Create: `tests/test_evidence_browser_app.py`

**Interfaces:**
- Consumes: all Task 1 dataclasses and `list_browser_papers`, `load_paper_browser`.
- Produces: `main() -> None` Streamlit entry point.

- [ ] **Step 1: Write failing UI boundary tests**

Assert that the new source:

```python
assert "from src.ui.evidence_browser_service import" in source
assert "sqlite3" not in source.lower()
assert ".execute(" not in source
assert "Submit review decision" not in source
assert "Needs human verification" not in source
```

Assert the eight labels occur in order and the app includes `Paper`, `Paper access`, `LNP formulations`, `Formulation evidence`, `Experimental arms`, `Outcomes`, and `Automatic-resolution issues`.

- [ ] **Step 2: Run the UI tests and confirm failure**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_evidence_browser_app.py
```

Expected: FAIL because the Streamlit app does not exist.

- [ ] **Step 3: Implement the page shell and paper selector**

Use the existing green-gray visual language. Add a sidebar text search and paper selectbox. Display screening-only papers and a clear no-scientific-rows empty state.

- [ ] **Step 4: Implement paper access and summary metrics**

Render only non-null DOI, PubMed, PMC, source, and local-artifact links. Show formulation, component, arm, outcome, evidence, and automatic-resolution counts.

- [ ] **Step 5: Implement the one-row-per-formulation table**

Create dataframe rows exclusively from `FORMULATION_COLUMNS`:

```python
rows = [
    {column: formulation.cells[column].display_value for column in FORMULATION_COLUMNS}
    for formulation in view.formulations
]
st.dataframe(rows, hide_index=True, width="stretch")
```

Loop over formulations afterward and render one `st.expander` per formulation.

- [ ] **Step 6: Implement evidence, arms, outcomes, and issue expanders**

Within each formulation expander, render a field-evidence table. Render each arm as its own nested expander with field evidence, outcome rows and evidence, eligibility badges/blockers, and automatic-resolution issues. Every blank value or missing evidence is shown as `NA`.

- [ ] **Step 7: Add an AppTest rendering test**

Monkeypatch `browser_database_path` to the Task 1 fixture, run `AppTest.from_file`, and assert:

```python
assert not app.exception
assert any("LNP formulations" in item.value for item in app.subheader)
assert not app.button
assert database_hash_before == database_hash_after
```

- [ ] **Step 8: Run UI and service tests**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_evidence_browser_service.py tests/test_evidence_browser_app.py
```

Expected: PASS.

- [ ] **Step 9: Commit the Streamlit interface**

```bash
git add src/ui/evidence_browser_app.py tests/test_evidence_browser_app.py
git commit -m "feat: add read-only evidence browser"
```

---

### Task 3: Authoritative-data verification and local launch

**Files:**
- Modify only if a defect is found: `src/ui/evidence_browser_service.py`
- Modify only if a rendering defect is found: `src/ui/evidence_browser_app.py`
- Create: `reports/database/evidence_browser_smoke_test.json`

**Interfaces:**
- Consumes: the promoted authoritative database and Task 2 Streamlit entry point.
- Produces: a live local Streamlit process and a deterministic smoke-test report.

- [ ] **Step 1: Verify production data through the service**

Hash the authoritative database, load all 14 papers, and assert the aggregate service counts match the final report: 24 formulations, 37 arms, 29 outcomes, and 403 evidence records. Confirm GP-008 includes `αCD163/LNP-FAPCAR` with ratio `45:30:23.5:1.5`.

- [ ] **Step 2: Run the full repository suite**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Launch Streamlit on an unused local port**

```bash
/Users/renemilywei/Desktop/AI-LNP/.venv/bin/streamlit run src/ui/evidence_browser_app.py --server.port 8506 --server.headless true
```

If port 8506 is occupied, use the next free port and record it.

- [ ] **Step 4: Verify the live health endpoint and immutable database hash**

Check `http://127.0.0.1:<port>/_stcore/health` returns `ok`. Re-hash the authoritative database and require an exact match with the pre-launch hash.

- [ ] **Step 5: Write the smoke-test report**

Record the application path, port, health status, authoritative database path/hash before and after, aggregate counts, test command/result, and `provider_calls: 0` in `reports/database/evidence_browser_smoke_test.json`.

- [ ] **Step 6: Commit the verification artifact**

```bash
git add reports/database/evidence_browser_smoke_test.json
git commit -m "test: verify evidence browser against authoritative data"
```

---

### Task 4: Completion verification

**Files:**
- Verify: `src/ui/evidence_browser_service.py`
- Verify: `src/ui/evidence_browser_app.py`
- Verify: `tests/test_evidence_browser_service.py`
- Verify: `tests/test_evidence_browser_app.py`
- Verify: `reports/database/evidence_browser_smoke_test.json`

**Interfaces:**
- Produces: final evidence that the browser satisfies the approved specification.

- [ ] **Step 1: Check exact requirements**

Confirm the app is read-only, has one formulation row per canonical formulation, preserves the eight-column order, renders `NA`, shows paper links, exposes linked evidence/arms/outcomes, separates NN from COMET, and contains no human-review controls.

- [ ] **Step 2: Run final targeted and full tests**

Run the Task 2 targeted command and the Task 3 full-suite command. Expected: all pass.

- [ ] **Step 3: Confirm live app and database immutability**

Recheck the health endpoint and compare the database hash to the final promoted hash `a8655d9c7a2a1b1aa235cad0a4b173e836070c055f84e51398869487be5879c3`.

- [ ] **Step 4: Hand off the local URL and files**

Report the local browser URL, service/app paths, tests, smoke report, and any data limitations without claiming that unresolved source facts are canonical usable facts.
