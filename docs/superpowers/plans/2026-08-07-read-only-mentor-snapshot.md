# Read-only Mentor Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the evidence browser fully read-only, show four database-backed headline metrics, and export a portable frozen mentor snapshot with matching SQLite, CSV, summary, and launch instructions.

**Architecture:** Keep `evidence_browser_service.py` as the read-only SQLite boundary and add one summary API used by the Streamlit page and snapshot exporter. Remove the correction workflow from the application module. Build the mentor package deterministically from the authoritative database, then verify the copied database and exported row/count reconciliation before writing its completion summary.

**Tech Stack:** Python 3.14, SQLite URI read-only mode, Streamlit, pytest, standard-library `csv`, `hashlib`, `json`, `shutil`, and `pathlib`.

## Global Constraints

- The four headline metrics are unique chemical formulations, general-use-ready experimental arms, nearest-neighbor-ready arms, and COMET-ready arms.
- Readiness counts apply to experimental arms and must match the combined table.
- Do not change scientific evidence or readiness definitions.
- Do not run paid extraction calls.
- Do not include `.env`, API keys, provider responses, licensed PDFs, or local source-file links in the mentor package.
- The working Streamlit application must expose no user-triggered write path.
- The mentor SQLite connection must use URI `mode=ro` and `PRAGMA query_only=ON`.
- Do not use CodeRabbit CLI or the CodeRabbit review workflow.

---

### Task 1: Canonical browser summary

**Files:**
- Modify: `src/ui/evidence_browser_service.py`
- Test: `tests/test_evidence_browser_service.py`

**Interfaces:**
- Consumes: `list_combined_arm_rows(filters=None, database_path=...)` and the canonical formulation/component tables.
- Produces: `BrowserSummary` and `summarize_browser_database(database_path: Path | None = None) -> BrowserSummary`.

- [ ] **Step 1: Write the failing summary test**

Add a test that calls `summarize_browser_database(evidence_browser_database)` and asserts that its arm counts equal counts derived from `list_combined_arm_rows(database_path=evidence_browser_database)`. Assert that duplicate formulation rows with the same normalized component/amount identity count once.

```python
summary = service.summarize_browser_database(evidence_browser_database)
rows = service.list_combined_arm_rows(database_path=evidence_browser_database)
assert summary.general_use_ready_arms == sum(row.general_usable for row in rows)
assert summary.nearest_neighbor_ready_arms == sum(row.nearest_neighbor_ready for row in rows)
assert summary.comet_ready_arms == sum(row.comet_ready for row in rows)
assert summary.experimental_arms == len(rows)
assert summary.unique_chemical_formulations == 1
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_evidence_browser_service.py -k browser_summary
```

Expected: failure because `summarize_browser_database` is not defined.

- [ ] **Step 3: Implement the immutable summary type and function**

Add:

```python
@dataclass(frozen=True)
class BrowserSummary:
    unique_chemical_formulations: int
    general_use_ready_arms: int
    nearest_neighbor_ready_arms: int
    comet_ready_arms: int
    experimental_arms: int
```

Calculate readiness counts from the returned `BrowserArmRow` objects. Calculate unique formulations from normalized, ordered component role/name/amount/unit tuples, excluding formulations with no component identity, matching the report's existing composition-fingerprint definition. Export the new symbols in `__all__`.

- [ ] **Step 4: Run the focused service tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_evidence_browser_service.py
```

Expected: all service tests pass.

- [ ] **Step 5: Commit the summary boundary**

```bash
git add src/ui/evidence_browser_service.py tests/test_evidence_browser_service.py
git commit -m "feat: add canonical browser summary"
```

### Task 2: Fully read-only working Streamlit browser

**Files:**
- Modify: `src/ui/evidence_browser_app.py`
- Modify: `tests/test_evidence_browser_app.py`

**Interfaces:**
- Consumes: `summarize_browser_database()` from Task 1.
- Produces: a read-only page with four headline metrics and no correction imports, form, or write controls.

- [ ] **Step 1: Replace the old mutation expectation with failing read-only tests**

Update source and rendered-app assertions:

```python
assert "review_service" not in source
assert "apply_review_decision" not in source
assert "Save correction" not in source
assert "Almost COMET-ready corrections" not in source
assert [metric.label for metric in app.metric[:4]] == [
    "Unique chemical formulations",
    "General-use-ready arms",
    "Nearest-neighbor-ready arms",
    "COMET-ready arms",
]
```

Retain the before/after database SHA-256 assertion.

- [ ] **Step 2: Run the app tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_evidence_browser_app.py
```

Expected: failures because the correction UI remains and metrics are absent.

- [ ] **Step 3: Remove the correction workflow**

Delete the `review_service` imports, `_render_comet_gap_correction`, its call in `main`, and the correction-only divider. Change the footer to:

```python
st.caption("Read-only evidence browser · no database editing controls")
```

- [ ] **Step 4: Add the four headline metrics**

After loading `all_arm_rows`, call `summarize_browser_database()` and render:

```python
for column, label, value in zip(
    st.columns(4),
    (
        "Unique chemical formulations",
        "General-use-ready arms",
        "Nearest-neighbor-ready arms",
        "COMET-ready arms",
    ),
    (
        summary.unique_chemical_formulations,
        summary.general_use_ready_arms,
        summary.nearest_neighbor_ready_arms,
        summary.comet_ready_arms,
    ),
):
    column.metric(label, value)
```

- [ ] **Step 5: Run app and service tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_evidence_browser_app.py tests/test_evidence_browser_service.py
```

Expected: all tests pass and the fixture database hash is unchanged.

- [ ] **Step 6: Commit the read-only browser**

```bash
git add src/ui/evidence_browser_app.py tests/test_evidence_browser_app.py
git commit -m "feat: make evidence browser fully read only"
```

### Task 3: Report reconciliation

**Files:**
- Modify: `src/database/report_current_database.py`
- Modify: `tests/test_report_current_database.py`
- Regenerate: `reports/database/final_current_evidence_database.json`
- Regenerate: `reports/database/final_current_evidence_database.md`

**Interfaces:**
- Consumes: canonical SQLite state and the same direct-or-field-linked usable-evidence rule used by the browser.
- Produces: a `general_use_ready_arms` report count alongside the existing formulation, NN, and COMET counts.

- [ ] **Step 1: Write a failing report assertion**

Extend the required count definitions and assert:

```python
assert report["counts"]["general_use_ready_arms"] == 1
assert "general_use_ready_arms" in report["definitions"]
```

The fixture should include one complete arm whose evidence is connected through `import_field_evidence`, proving the report does not require `evidence.experiment_id`.

- [ ] **Step 2: Run the focused report test and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_report_current_database.py
```

Expected: failure because the report lacks `general_use_ready_arms`.

- [ ] **Step 3: Add the report definition and evidence-aware SQL count**

Add the definition:

```python
"general_use_ready_arms": (
    "Complete canonical arms with accepted direct evidence or accepted "
    "evidence linked through arm/outcome fields."
),
```

Count complete arms with non-rejected evidence attached directly or through `import_field_evidence`, using the same entity scopes as the browser. Keep NN and COMET counts sourced from `eligibility_result`.

- [ ] **Step 4: Run report tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_report_current_database.py
```

Expected: all tests pass.

- [ ] **Step 5: Regenerate the authoritative JSON and Markdown reports**

Use the existing report command or a small checked invocation of `report_current_database` and `write_report` against `/Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db`. Verify counts are 17 unique formulations, 38 general-use-ready arms, 32 NN-ready arms, and 4 COMET-ready arms.

- [ ] **Step 6: Commit report reconciliation**

```bash
git add src/database/report_current_database.py tests/test_report_current_database.py reports/database/final_current_evidence_database.json reports/database/final_current_evidence_database.md
git commit -m "fix: reconcile readiness report counts"
```

### Task 4: Deterministic mentor snapshot exporter

**Files:**
- Create: `src/ui/export_mentor_snapshot.py`
- Create: `src/ui/mentor_snapshot_app.py`
- Create: `tests/test_export_mentor_snapshot.py`
- Modify: `src/ui/evidence_browser_service.py`

**Interfaces:**
- Consumes: `summarize_browser_database(database_path)`, `list_combined_arm_rows(database_path=...)`, and the authoritative database path.
- Produces: `export_mentor_snapshot(database_path: Path, output_dir: Path) -> dict[str, object]` and a snapshot entry point that reads `LNP_MENTOR_SNAPSHOT_DB`.

- [ ] **Step 1: Write failing exporter tests**

The test must assert that export creates:

```python
expected = {
    "lnp_evidence.db",
    "combined_experimental_arms.csv",
    "snapshot_summary.json",
    "README.md",
    "app.py",
}
assert expected <= {path.name for path in output_dir.iterdir()}
```

Also assert source and copied database hashes match, CSV data-row count equals `summary.experimental_arms`, summary counts equal the service summary, no exported text contains `file://`, `OPENAI_API_KEY`, or `.env`, and a write attempted through the snapshot connection raises `sqlite3.OperationalError`.

- [ ] **Step 2: Run the exporter test and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_export_mentor_snapshot.py
```

Expected: import failure because the exporter does not exist.

- [ ] **Step 3: Add portable row serialization**

Add `combined_arm_rows_for_export(...) -> list[dict[str, str]]` to the service so both the Streamlit table and exporter can use pure row dictionaries without importing the Streamlit module. Include paper metadata, approved formulation columns, arm fields, stacked outcomes, readiness statuses, blockers, and issues. Replace local `file://` values with `NA` when `include_local_links=False`.

- [ ] **Step 4: Implement fail-closed export creation**

`export_mentor_snapshot` will:

1. open the source with `mode=ro` and `query_only=ON`;
2. require `PRAGMA integrity_check` to equal `ok` and zero `PRAGMA foreign_key_check` rows;
3. copy with `shutil.copy2` and require identical SHA-256;
4. open the copy with `mode=ro` and repeat integrity/foreign-key checks;
5. write UTF-8 CSV from portable rows;
6. write a standalone `app.py` wrapper that sets `LNP_MENTOR_SNAPSHOT_DB` to the adjacent database and invokes the packaged read-only browser;
7. write README prerequisites and the command `streamlit run app.py`;
8. write `snapshot_summary.json` last, containing timestamp, database hash, integrity results, row count, and four headline metrics.

The exporter must refuse a non-empty output directory so it cannot mix snapshots.

- [ ] **Step 5: Make the snapshot database path explicit**

Update `browser_database_path()` to use `LNP_MENTOR_SNAPSHOT_DB` when set. Require that override to be an existing file and continue opening it through `_connect` with `mode=ro`. Suppress local-source links when `LNP_MENTOR_SNAPSHOT_DB` is active.

- [ ] **Step 6: Run exporter, service, and app tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_export_mentor_snapshot.py tests/test_evidence_browser_service.py tests/test_evidence_browser_app.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit the exporter**

```bash
git add src/ui/export_mentor_snapshot.py src/ui/mentor_snapshot_app.py src/ui/evidence_browser_service.py tests/test_export_mentor_snapshot.py tests/test_evidence_browser_service.py
git commit -m "feat: export portable mentor snapshot"
```

### Task 5: Build and verify the real mentor snapshot

**Files:**
- Create: `exports/mentor_snapshot_2026-08-07/`
- Modify only if verification exposes a defect: files from Tasks 1–4 and their tests.

**Interfaces:**
- Consumes: the authoritative database and completed exporter.
- Produces: the final shareable directory and a verified live read-only browser.

- [ ] **Step 1: Run the complete relevant test suite**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_evidence_browser_service.py tests/test_evidence_browser_app.py tests/test_report_current_database.py tests/test_export_mentor_snapshot.py
```

Expected: all tests pass.

- [ ] **Step 2: Export the real snapshot**

Run the exporter with:

```bash
.venv/bin/python -m src.ui.export_mentor_snapshot \
  --database /Users/renemilywei/Desktop/AI-LNP/data/curated/lnp_evidence.db \
  --output exports/mentor_snapshot_2026-08-07
```

Expected: completion summary reports 17, 38, 32, and 4 with 48 CSV arm rows.

- [ ] **Step 3: Verify package safety and database immutability**

Run integrity and secret/path scans. Open the snapshot through `file:...?...mode=ro`, attempt a harmless write inside a rolled-back transaction, and require `OperationalError`. Confirm no package file contains `.env`, API-key names, provider-response paths, or `file://`.

- [ ] **Step 4: Restart and inspect the working browser**

Restart port 8506 from the worktree, open the page, and confirm the four metrics and absence of the correction section or save controls.

- [ ] **Step 5: Launch and inspect the mentor snapshot**

Run `streamlit run app.py` from the export directory on a separate localhost port. Confirm counts, combined rows, paper links, and read-only footer; confirm local-source links are absent.

- [ ] **Step 6: Run the repository test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass, with only previously documented skips.

- [ ] **Step 7: Commit the verified export manifest and package**

```bash
git add exports/mentor_snapshot_2026-08-07
git commit -m "chore: publish mentor database snapshot"
```

