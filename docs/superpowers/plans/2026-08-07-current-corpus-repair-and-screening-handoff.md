# Current-Corpus Repair and Screening Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a verified lossless SQLite database, one combined arm table, a compact near-COMET correction interface, honest final counts, and a proven handoff that can begin screening and extracting new papers the same day.

**Architecture:** Keep the existing manifest, source-fact ledger, normalized database, asset resolver, and Streamlit browser. Repair GP graph-to-arm projection and source-asset recovery at their existing boundaries, recalculate readiness from the final rows, rebuild once from immutable artifacts, and expose all evidence-backed arms through one display service. Reuse the append-only review service only for evidence-backed COMET corrections, then prove a new paper can use the same path without paper-specific code.

**Tech Stack:** Python 3.14, SQLite, JSON/JATS/HTML, PyMuPDF, openpyxl, Streamlit, pytest, SHA-256 manifests, existing search/RAG/extraction modules.

## Global Constraints

- Use `config/database/current_corpus_v1.json`; do not create another corpus manifest.
- Use `data/curated/lnp_evidence.db` as the final authoritative database only after temporary-rebuild verification.
- Do not use CodeRabbit CLI or the CodeRabbit review workflow.
- Do not download every link; resolve only declared or scientifically classified supplements, protocols, datasets, and patents.
- Do not infer that the paper used a patent formulation unless paper evidence identifies that formulation.
- Do not require human verification for general-use or nearest-neighbor rows.
- Keep COMET verification separate from automatic extraction and general application status.
- Keep every approved source fact in projected, unresolved, quarantined, or rejected state; silent omission fails the build.
- Keep normalized outcomes as separate SQLite rows; compress them only in the combined table display.
- Show every evidence-backed arm by default, including incomplete arms.
- Display missing values as `NA`; never store `NA` as a scientific value.
- Paid reruns require an exact request hash and explicit approval; never retry silently.
- Preserve original JSON, source assets, database backups, and append-only correction history.

---

## Caveman map

1. Count JSON experiments. Count SQLite arms. Make every difference explain itself.
2. Fix graph translator. One real experiment becomes one real arm.
3. Look for supplement locally. Then inspect named science links. Download only useful files.
4. Stop calling every paper “Needs Review.” Calculate what each arm can actually do.
5. Rebuild database. Import everything. Deduplicate science, not proof.
6. Rerun only papers still missing extractable information.
7. Show one big table: one arm per row, all outcomes in one cell.
8. Give user a small COMET gap form at the top, not a giant evidence scroll.
9. Freeze database and print honest counts.
10. Push one new-paper fixture through the whole machine. If it works, start the real new-paper batch.

---

### Task 1: Paper-by-paper JSON-to-SQLite arm accounting

**Estimated time:** 30–45 minutes

**Files:**
- Create: `src/database/arm_projection_audit.py`
- Create: `tests/test_arm_projection_audit.py`
- Create during execution: `reports/database/arm_projection_audit.json`

**Interfaces:**
- Produces: `GraphExperimentIdentity`, `ArmProjectionDisposition`, `audit_arm_projection(root: Path, database: Path) -> dict[str, object]`.
- A disposition is exactly `projected`, `incomplete`, `quarantined`, `rejected`, or `screening_only`.

- [ ] **Step 1: Write the failing accounting test**

```python
def test_every_graph_experiment_has_one_explained_disposition(tmp_path: Path) -> None:
    report = audit_arm_projection(FIXTURE_ROOT, build_projection_fixture(tmp_path))
    paper = report["papers"]["GP-T01"]
    assert paper["graph_experiment_count"] == 2
    assert paper["accounted_count"] == 2
    assert paper["unexplained_experiment_ids"] == []
    assert paper["sqlite_arm_count"] == 1
```

- [ ] **Step 2: Run it and confirm RED**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_arm_projection_audit.py
```

Expected: FAIL because `src.database.arm_projection_audit` does not exist.

- [ ] **Step 3: Implement identity comparison without changing scientific data**

Read explicit experiment IDs from each approved GP `accepted_graph.json`, source experiment keys from NP and PILOT bundles, and `import_record_map`/`experiment` identities from SQLite. Require a reason and source JSON path for every non-projected identity.

- [ ] **Step 4: Generate the real report and verify the known GP gaps are visible**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m src.database.arm_projection_audit --root . --database data/curated/lnp_evidence.db --output reports/database/arm_projection_audit.json
```

Expected: no unexplained IDs; count differences are explicitly classified rather than hidden.

- [ ] **Step 5: Commit**

```bash
git add src/database/arm_projection_audit.py tests/test_arm_projection_audit.py reports/database/arm_projection_audit.json
git commit -m "test: account for graph experiment projection"
```

---

### Task 2: Repair GP graph experiments into canonical SQLite arms

**Estimated time:** 60–90 minutes

**Files:**
- Modify: `src/database/adapters/accepted_graph.py`
- Modify: `src/database/import_contracts.py`
- Create: `tests/test_accepted_graph_arm_projection.py`
- Modify: `tests/test_current_corpus_import.py`

**Interfaces:**
- Produces: `resolve_graph_experiment(graph, experiment_id) -> ResolvedGraphExperiment`.
- `ResolvedGraphExperiment` contains formulation IDs, arm fields, linked outcome IDs, evidence IDs, and a resolution disposition/reason.
- `adapt_accepted_graph_losslessly(...)` emits one `ArmRecord` per safely resolved explicit experiment.

- [ ] **Step 1: Write failing fixtures for explicit, study-wide, ambiguous, and absent links**

```python
def test_explicit_graph_experiments_become_distinct_arms() -> None:
    bundle = adapt_fixture("two_explicit_experiments.json")
    assert [arm.source_experiment_key for arm in bundle.arms] == ["EXP-1", "EXP-2"]
    assert bundle.arms[0].payload_name == "mRNA-A"
    assert bundle.arms[1].payload_name == "mRNA-B"

def test_ambiguous_formulation_link_is_preserved_but_not_guessed() -> None:
    bundle = adapt_fixture("ambiguous_formulation.json")
    assert not bundle.arms
    issue = next(item for item in bundle.reviews if item.source_record_key == "EXP-1")
    assert issue.reason_code == "formulation_link_ambiguous"
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_accepted_graph_arm_projection.py tests/test_current_corpus_import.py
```

- [ ] **Step 3: Implement deterministic relationship rules**

Use explicit graph edges first. Use a study-wide formulation only when exactly one supported formulation applies to the paper or the fact is marked study-wide. Never resolve by list position. Link outcomes only through experiment membership or shared evidence-supported context. Preserve every unresolved claim in the source ledger.

- [ ] **Step 4: Add paper-level regression assertions**

For GP-002, GP-004, GP-005, and GP-007, assert that every explicit graph experiment is either a canonical arm or has one named quarantine/rejection reason. Assert GP-006 and GP-008 gold enrichment does not duplicate an identical source arm.

- [ ] **Step 5: Run tests and commit**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_accepted_graph_arm_projection.py tests/test_current_corpus_import.py tests/test_source_fact_audit.py
git add src/database/adapters/accepted_graph.py src/database/import_contracts.py tests/test_accepted_graph_arm_projection.py tests/test_current_corpus_import.py
git commit -m "fix: project graph experiments into arms"
```

---

### Task 3: Generalize selective supplement, protocol, and patent discovery

**Estimated time:** 45–75 minutes

**Files:**
- Modify: `src/rag/current_corpus_assets.py`
- Modify: `tests/test_current_corpus_assets.py`
- Create: `tests/fixtures/assets/paper_with_scientific_links.nxml`
- Modify: `src/database/corpus_manifest.py`

**Interfaces:**
- Extends: `classify_link(label, href, element_name=None, citation_context=None) -> str | None`.
- Produces asset kinds: `supplement`, `protocol`, `dataset`, `patent`, or `None`.
- Produces: `discover_declared_assets(source_paths: Sequence[Path]) -> tuple[DeclaredAsset, ...]`.
- `DeclaredAsset` records URL, label, kind, declaring source, local match, SHA-256, access status, and direct/indirect provenance.

- [ ] **Step 1: Write failing local-first and keyword tests**

```python
def test_science_links_are_selected_but_navigation_is_ignored(tmp_path: Path) -> None:
    assets = discover_declared_assets((fixture_path("paper_with_scientific_links.nxml"),))
    assert {(row.kind, row.filename) for row in assets} == {
        ("supplement", "mmc1.xlsx"),
        ("patent", "US10221127"),
    }

def test_existing_local_asset_prevents_network_download(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("urllib.request.urlopen", fail_network)
    result = resolve_declared_assets(local_entry(tmp_path), root=tmp_path, allow_network=True)
    assert result.downloaded_files == ()
```

- [ ] **Step 2: Run and confirm RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_current_corpus_assets.py
```

- [ ] **Step 3: Implement declared-link discovery and safe resolution**

Search local registered paths and adjacent package files first. Parse JATS tags and downloaded HTML anchors. Classify using semantic element names, label/context keywords, filename conventions, and allowed file types. Use browser fallback only for an already-declared relevant link whose final asset URL is hidden by JavaScript.

- [ ] **Step 4: Preserve direct versus indirect evidence**

Supplement facts may be direct evidence for the paper. Patent facts default to `indirect_reference`; they may populate a paper field only when a paper sentence or exact named formulation bridges the patent fact to the studied LNP.

- [ ] **Step 5: Verify GP-008 and GP-004 behavior**

Assert GP-008 finds its existing local supplement without network access. Assert GP-004 records the cited patent but does not fabricate a molar ratio unless the paper/patent bridge identifies the exact formulation used.

- [ ] **Step 6: Run tests and commit**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_current_corpus_assets.py tests/test_corpus_manifest.py
git add src/rag/current_corpus_assets.py src/database/corpus_manifest.py tests/test_current_corpus_assets.py tests/fixtures/assets/paper_with_scientific_links.nxml
git commit -m "feat: resolve declared scientific assets"
```

---

### Task 4: Replace blanket review labels with live usability and COMET-gap status

**Estimated time:** 35–50 minutes

**Files:**
- Modify: `src/database/status.py`
- Modify: `src/database/run_current_corpus_import.py`
- Create: `src/database/readiness.py`
- Create: `config/database/readiness_profiles_v3.json`
- Modify: `tests/test_database_status.py`
- Create: `tests/test_readiness.py`

**Interfaces:**
- Produces: `ReadinessSummary(general_usable, nearest_neighbor_ready, comet_ready, comet_blockers, queue_label)`.
- Produces: `evaluate_readiness(connection, experiment_id) -> ReadinessSummary`.
- Queue labels are `comet_ready`, `almost_comet_ready`, `comet_gap`, `conflict`, or `quarantined`.
- `readiness_profiles_v3.json` is the single versioned field matrix used by status calculation, the UI, and final reporting. COMET requires an identified formulation, chemical composition, molar ratio, biological model/species/setting, payload identity and applicable encoded product or molecular target, dose/unit, assay, and at least one coherent evidence-backed outcome. A field marked not applicable by evidence is not treated as missing.

- [ ] **Step 1: Write failing semantics tests**

```python
def test_automatic_evidence_is_general_usable_without_human_review(database) -> None:
    result = evaluate_readiness(database, automatic_arm(database))
    assert result.general_usable is True
    assert "human review" not in result.queue_label

def test_almost_comet_ready_means_one_to_three_blockers(database) -> None:
    result = evaluate_readiness(database, arm_missing(database, "dose", "dose_unit"))
    assert result.comet_ready is False
    assert result.queue_label == "almost_comet_ready"
    assert result.comet_blockers == ("dose", "dose_unit")

def test_missing_formulation_ratio_is_visible_comet_blocker(database) -> None:
    result = evaluate_readiness(database, arm_missing(database, "lnp_molar_ratio"))
    assert "lnp_molar_ratio" in result.comet_blockers
```

- [ ] **Step 2: Run and confirm RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_database_status.py tests/test_readiness.py
```

- [ ] **Step 3: Implement live status and remove manifest-copy semantics**

Keep `paper.import_status` as provenance/routing metadata. Do not use it as the user-facing review state. General use requires an evidence-backed non-invalid arm. Read the exact nearest-neighbor and COMET requirements from `readiness_profiles_v3.json`; do not duplicate field lists in the UI or report. Only COMET adds its final verification blocker.

- [ ] **Step 4: Recalculate after every import and correction**

Make `run_current_corpus_import._recalculate_paper` persist the latest status and eligibility for every arm. Ensure no UI query reads stale manifest text as readiness.

- [ ] **Step 5: Run tests and commit**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_database_status.py tests/test_readiness.py tests/test_current_corpus_import.py
git add src/database/status.py src/database/readiness.py src/database/run_current_corpus_import.py config/database/readiness_profiles_v3.json tests/test_database_status.py tests/test_readiness.py
git commit -m "fix: calculate live arm readiness"
```

---

### Task 5: Rebuild, audit gaps, and rerun only what remains necessary

**Estimated time:** 45–90 minutes locally, plus 30–120 minutes only if approved model calls are still necessary

**Files:**
- Modify: `src/database/audit_current_database.py`
- Modify: `src/database/report_current_database.py`
- Modify: `src/extraction/prepare_current_corpus_reruns.py`
- Modify: `tests/test_prepare_current_corpus_reruns.py`
- Create during execution: `reports/database/post_projection_gap_audit.json`
- Create during execution only if gaps remain: `data/staging/extraction/current_corpus_reruns/requests/`

**Interfaces:**
- Produces: gap kinds `source_not_reported`, `source_asset_missing`, `extraction_missed`, `projection_missed`, and `scientific_conflict`.
- Produces rerun requests only for `extraction_missed` and recoverable `source_asset_missing` gaps.

- [ ] **Step 1: Add failing rerun-routing tests**

```python
def test_projection_gap_never_creates_paid_rerun() -> None:
    assert build_requests([gap("projection_missed")]) == ()

def test_source_not_reported_is_reported_but_not_rerun() -> None:
    assert build_requests([gap("source_not_reported")]) == ()
```

- [ ] **Step 2: Run and confirm RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_prepare_current_corpus_reruns.py tests/test_audit_current_database.py
```

- [ ] **Step 3: Build a fresh temporary database from the manifest**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m src.database.run_current_corpus_import --root . --manifest config/database/current_corpus_v1.json --output data/staging/database/current_corpus_rebuild/repaired.db
```

Import all local JSON and recovered assets, then deduplicate canonical science while retaining all source occurrences and provenance.

- [ ] **Step 4: Run losslessness, relationship, and gap audits**

Require SQLite integrity, foreign keys, source-fact equality, evidence-ID accounting, no orphans, no unexplained graph experiments, and repeatable counts. Generate `post_projection_gap_audit.json` from the rebuilt database.

- [ ] **Step 5: Prepare the exact rerun list**

Each remaining request names paper, arm, missing fields, evidence packet, model, expected output schema, token/cost estimate, and SHA-256. Existing pilot results are merged; PILOT-001 through PILOT-003 are not rerun merely because they were pilots.

- [ ] **Step 6: Stop at the paid-call approval gate if requests remain**

Do not dispatch a request until the user approves its exact hash. If no request remains, skip the paid runner. After approved results return, register them as contributing artifacts and repeat Steps 3–4.

- [ ] **Step 7: Run tests and commit deterministic code/report changes**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_prepare_current_corpus_reruns.py tests/test_current_corpus_import.py tests/test_source_fact_audit.py tests/test_arm_projection_audit.py
git add src/database/audit_current_database.py src/database/report_current_database.py src/extraction/prepare_current_corpus_reruns.py tests/test_prepare_current_corpus_reruns.py reports/database/post_projection_gap_audit.json
git commit -m "fix: rebuild and route remaining evidence gaps"
```

---

### Task 6: Build the approved one-row-per-arm combined main table

**Estimated time:** 60–90 minutes

**Files:**
- Modify: `src/ui/evidence_browser_service.py`
- Modify: `src/ui/evidence_browser_app.py`
- Modify: `tests/test_evidence_browser_service.py`
- Modify: `tests/test_evidence_browser_app.py`

**Interfaces:**
- Produces: immutable `BrowserArmRow` with paper, formulation, arm, outcomes, readiness, and blocker fields.
- Produces: `list_combined_arm_rows(filters: BrowserFilters | None = None) -> tuple[BrowserArmRow, ...]`.
- Outcomes remain `tuple[BrowserOutcome, ...]` in the service and become newline-separated display text only in the app.

- [ ] **Step 1: Write failing row-grain and field-order tests**

```python
def test_combined_table_has_one_row_per_arm_and_stacked_outcomes(database) -> None:
    rows = list_combined_arm_rows()
    assert len(rows) == database.execute("SELECT count(*) FROM experiment").fetchone()[0]
    arm = next(row for row in rows if len(row.outcomes) == 2)
    assert arm.outcomes[0].outcome_id != arm.outcomes[1].outcome_id
    assert "Outcome A" in arm.outcomes_display
    assert "Outcome B" in arm.outcomes_display
```

Assert the visible formulation columns remain in this order: `lnp_name`, `chemical_formulation_total`, `lnp_molar_ratio`, `ionizable_lipid`, `helper_lipid`, `cholesterol`, `peg_lipid`, `others`.

- [ ] **Step 2: Run and confirm RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_evidence_browser_service.py tests/test_evidence_browser_app.py
```

- [ ] **Step 3: Implement one read-only query/service boundary**

Load all evidence-backed arms. Apply active append-only corrections when present. Keep distinct SQLite outcome IDs and evidence links. Build `outcomes_display` from endpoint, value/unit or qualitative result, normalization basis, and timepoint without changing stored outcomes.

- [ ] **Step 4: Make the combined table the main page**

Show paper/title/links, arm ID, approved formulation columns, model/cell/species, payload, dose/route/timepoint/assay/comparator, stacked outcomes, three readiness columns, missing fields, and automatic-resolution blockers. Add filters for paper, cell type, general/NN/COMET readiness, and blocker. Default to all evidence-backed arms.

- [ ] **Step 5: Prove incomplete rows stay visible**

The AppTest fixture must show a row whose ratio is `NA` and whose COMET status names `lnp_molar_ratio` as a blocker. It must not disappear from the general table.

- [ ] **Step 6: Run tests and commit**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_evidence_browser_service.py tests/test_evidence_browser_app.py
git add src/ui/evidence_browser_service.py src/ui/evidence_browser_app.py tests/test_evidence_browser_service.py tests/test_evidence_browser_app.py
git commit -m "feat: show combined experimental arm table"
```

---

### Task 7: Add the compact almost-COMET correction form

**Estimated time:** 45–75 minutes

**Files:**
- Modify: `src/ui/evidence_browser_app.py`
- Modify: `src/ui/review_service.py`
- Create: `tests/test_comet_gap_interface.py`
- Modify: `tests/test_review_service.py`

**Interfaces:**
- Reuses: `ReviewDecision` and `apply_review_decision(request) -> ReviewResult`.
- Produces: `list_comet_gap_arms() -> tuple[ReviewArm, ...]`, sorted by conflict/quarantine state and blocker count.
- An accepted value requires `corrected_value`, `evidence_excerpt`, and `evidence_location`.

- [ ] **Step 1: Write failing compact-form tests**

```python
def test_comet_gap_page_puts_entry_form_before_evidence_history(app) -> None:
    assert app.selectbox["Missing field"]
    assert app.text_input["Updated value"]
    assert app.text_area["Evidence excerpt"]
    assert app.text_input["Evidence location"]
    assert app.button["Save correction"]

def test_saved_correction_recalculates_comet_in_same_transaction(database) -> None:
    result = apply_review_decision(valid_missing_dose_decision(database))
    assert result.review_revision_id is not None
    assert result.comet.rules_version
```

- [ ] **Step 2: Run and confirm RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_comet_gap_interface.py tests/test_review_service.py
```

- [ ] **Step 3: Reuse the safe append-only writer**

Do not build a second correction storage system. Use the existing backup, state-token, ownership, evidence, revision, missing-field resolution, and eligibility recalculation checks in `review_service.py`. Add only the query that sorts COMET gaps and the smaller form adapter.

- [ ] **Step 4: Put paper access and missing fields above the form**

Show DOI, PubMed, PMC, or source link first. Show only the selected arm’s current values and COMET blockers. Place detailed evidence/history in a collapsed section below the save form.

- [ ] **Step 5: Keep manual work bounded to COMET**

The general table must not say every arm requires review. The COMET tab may show final verification or missing-value tasks because that is the user-approved manual quality-control boundary.

- [ ] **Step 6: Run tests and commit**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_comet_gap_interface.py tests/test_review_service.py tests/test_database_status.py
git add src/ui/evidence_browser_app.py src/ui/review_service.py tests/test_comet_gap_interface.py tests/test_review_service.py
git commit -m "feat: add compact COMET gap correction"
```

---

### Task 8: Promote the database and publish the honest final report

**Estimated time:** 45–60 minutes

**Files:**
- Modify: `src/database/report_current_database.py`
- Modify: `src/database/database_lifecycle.py`
- Modify: `tests/test_report_current_database.py`
- Create during execution: `reports/database/final_current_corpus_report.json`
- Create during execution: `reports/database/final_current_corpus_report.md`

**Interfaces:**
- Produces: `build_honest_report(connection, manifest_path) -> dict[str, object]`.
- The report contains separately named counts required by the design and their SQL definitions.

- [ ] **Step 1: Write failing count-definition tests**

```python
def test_honest_report_never_equates_papers_formulations_facts_and_arms(database) -> None:
    report = build_honest_report(database, FIXTURE_MANIFEST)
    assert set(report["counts"]) >= {
        "papers", "named_formulations", "unique_chemical_formulations",
        "complete_formulations", "incomplete_formulations", "components",
        "source_fact_occurrences", "canonical_facts", "experimental_arms",
        "outcomes", "source_evidence_occurrences", "evidence_records",
        "nearest_neighbor_ready_arms", "comet_ready_arms",
        "almost_comet_ready_arms", "unresolved_automatic_items",
        "human_adjudication_items",
    }
```

- [ ] **Step 2: Run and confirm RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_report_current_database.py
```

- [ ] **Step 3: Verify the candidate database twice**

Run integrity and foreign-key checks; artifact hash checks; source-fact and evidence equality; orphan and duplicate checks; graph-arm accounting; material-field evidence checks; eligibility recalculation; and two rebuilds with identical scientific hashes/counts.

- [ ] **Step 4: Back up and promote atomically**

Hash and back up the existing authoritative database. Promote `repaired.db` only after all gates pass. Reopen the promoted database read-only and rerun the audit.

- [ ] **Step 5: Generate the reports from the promoted database**

Include database hash, schema/rules versions, manifest hash, contributing artifact hashes, completed reruns, remaining reruns, unresolved items, and per-paper counts. Do not reuse the old 14/24/37/29/403 numbers unless the new SQL independently produces them.

- [ ] **Step 6: Run full offline verification and launch Streamlit**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q
.venv/bin/streamlit run src/ui/evidence_browser_app.py --server.port 8506 --server.headless true
```

Verify the health endpoint, main combined table, COMET gap tab, and unchanged database hash after read-only browsing.

- [ ] **Step 7: Commit**

```bash
git add src/database/report_current_database.py src/database/database_lifecycle.py tests/test_report_current_database.py reports/database/final_current_corpus_report.json reports/database/final_current_corpus_report.md
git commit -m "feat: publish verified evidence database report"
```

---

### Task 9: Prove readiness for new papers, then start the first real batch

**Estimated time:** 45–60 minutes for the smoke test; 2–4 hours for a real first batch

**Files:**
- Create: `src/extraction/new_paper_handoff.py`
- Create: `tests/test_new_paper_handoff.py`
- Create: `tests/fixtures/new_paper_handoff/`
- Create during execution: `reports/extraction/new_paper_handoff_smoke.json`
- Existing runtime inputs/outputs: `src/search/run_discovery.py`, `src/search/build_candidate_index.py`, `src/screening/`, `src/rag/run_pipeline.py`, and the existing extraction/import adapters.

**Interfaces:**
- Produces: `run_new_paper_handoff(candidate: ScreenedCandidate, workspace: Path) -> HandoffResult`.
- `HandoffResult` records metadata, screening disposition, source assets, supplement assets, extraction artifact, source-fact accounting, imported arm IDs, readiness, and UI visibility.

- [ ] **Step 1: Write a failing paper-ID-agnostic smoke test**

```python
def test_new_paper_reaches_combined_table_without_special_case(tmp_path: Path) -> None:
    result = run_new_paper_handoff(fixture_candidate("NEW-TEST-001"), tmp_path)
    assert result.screening_disposition == "include"
    assert result.source_fact_accounting_balanced is True
    assert result.imported_arm_ids
    assert result.visible_in_combined_table is True
    assert result.discovered_assets == ("supplement.pdf",)
```

- [ ] **Step 2: Run and confirm RED**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q tests/test_new_paper_handoff.py
```

- [ ] **Step 3: Implement the thin orchestrator**

Call existing discovery metadata normalization, screening decision, full-text retrieval, selective asset resolution, RAG ingestion, extraction adapter, lossless import, arm audit, readiness calculation, and combined-table query. Do not put scientific extraction logic in the orchestrator and do not add special handling for `NEW-TEST-001`.

- [ ] **Step 4: Run the smoke test and full offline suite**

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q tests/test_new_paper_handoff.py
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q
```

- [ ] **Step 5: Declare the screening gate open only if the smoke report passes**

`new_paper_handoff_smoke.json` must show no paper-specific adapter, balanced source facts, at least one imported evidence-backed arm, asset provenance, status calculation, and combined-table visibility.

- [ ] **Step 6: Start the real new-paper batch**

Run the existing versioned discovery queries, deduplicate the candidate index against the final database, screen candidates, retrieve full text and declared supplements for included papers, and begin extraction. Record separately: discovered candidates, deduplicated candidates, screened papers, included papers, source-accessible papers, papers with at least one evidence-backed arm, and extracted/imported arms. Any provider call still requires its exact approved request hash.

- [ ] **Step 7: Commit the reusable handoff and smoke artifact**

```bash
git add src/extraction/new_paper_handoff.py tests/test_new_paper_handoff.py tests/fixtures/new_paper_handoff reports/extraction/new_paper_handoff_smoke.json
git commit -m "feat: verify new paper extraction handoff"
```

---

## Execution schedule and hard gates

| Order | Work | Expected elapsed time | Hard output |
|---|---|---:|---|
| 1 | Tasks 1–2: arm accounting and projection repair | 1.5–2.25 h | Every JSON experiment explained |
| 2 | Tasks 3–4: selective assets and live readiness | 1.25–2 h | Supplements generalized; blanket review removed |
| 3 | Task 5: rebuild, audit, bounded reruns | 0.75–1.5 h local | Clean candidate DB and exact rerun queue |
| 4 | Tasks 6–7: combined table and COMET form | 1.75–2.75 h | Working Streamlit interface |
| 5 | Task 8: promotion and honest report | 0.75–1 h | Final verified SQLite and counts |
| 6 | Task 9 smoke gate | 0.75–1 h | Pipeline proven ready for new papers |
| 7 | First real new-paper batch | 2–4 h | Screening and extraction started |

**Honest estimate:** approximately **6–9 hours** to finish repair, interface, verification, and the new-paper smoke gate; then **2–4 hours** for a first real screening/extraction batch. Some tasks can overlap safely, but publisher access, explicit paid-call approvals, or scientific conflicts can extend the day. The database may not be promoted merely to meet the clock.

## Definition of done

This plan is complete only when:

- the final SQLite database passes integrity, provenance, losslessness, deduplication, relationship, and reproducibility gates;
- every approved JSON experiment/fact/evidence item is represented or explicitly classified;
- the main Streamlit page shows every evidence-backed arm as one row with stacked outcomes;
- readiness and missing-field flags visibly distinguish general, nearest-neighbor, and COMET needs;
- the compact correction form safely updates only evidence-backed COMET gaps and recalculates readiness;
- the final report publishes all requested counts separately from the promoted database;
- the rerun list contains only real post-repair extraction gaps and completed results are reimported;
- the new-paper smoke test succeeds without paper-specific code; and
- the first real new-paper discovery/screening/extraction batch has started, subject only to explicit provider-call approval.
