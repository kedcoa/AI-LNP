# Working Liver-LNP Evidence Application Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and release a refreshable liver-cell LNP evidence application that loads all current evidence, extracts an expanded paper cohort economically, supports exact/partial/nearest-neighbor retrieval, conditionally integrates COMET, and exposes provenance through a tested Streamlit UI.

**Architecture:** SQLite is the authoritative scientific store. Focused modules import versioned extraction artifacts, compute deterministic arm status and model eligibility, orchestrate discovery/extraction preflights, build exact/partial/similarity services, and expose them through Streamlit. COMET is behind a registry gate; a disabled model state is a valid completed release.

**Tech Stack:** Python 3, SQLite, Pydantic, pytest, Streamlit, pandas/openpyxl, scikit-learn, RDKit when verified molecular structures exist, existing AI-LNP extraction modules, and optional COMET dependencies in an isolated environment.

## Global Constraints

- Do not display a paper-level extraction denominator unless the reference was independently human-verified.
- Keep complete, incomplete, conflicting, and quarantined arms; represent unsupported values as `NA` in presentation and `NULL` plus status metadata in SQLite.
- Preserve target cell and delivery-recipient cell separately.
- Every material literature value must link to accepted evidence.
- Keep measured evidence, similarity results, model predictions, experimental candidates, and measured lab results distinct.
- Use one Gate A call and normally two or three coherent Gate B calls per new paper; selective vision is conditional.
- Show request hashes, call counts, and token estimates before every paid batch. Never retry a paid call silently.
- Do not add Codex auditing to the ordinary extraction path.
- Do not store institutional credentials or commit licensed PDFs.
- No unit test may call a paid provider.
- Freeze COMET as disabled if data or model gates fail; this must not block the evidence application.

## Delivery Schedule

| Week | Working result |
|---|---|
| 1 | Existing evidence database populated; selective reruns and four-cell discovery staged |
| 2 | First 16-22 new papers extracted, subject to eligibility and access |
| 3 | Up to approximately 40 new eligible papers processed; Evidence Dataset v1 frozen |
| 4 | Exact, partial, and nearest-neighbor search frozen |
| 5 | COMET, simpler baseline, or disabled model state registered |
| 6 | Streamlit UI, exports, refresh workflow, end-to-end tests, and release complete |

---

### Task 1: Add provenance, arm-status, review-history, and screening-history storage

**Files:**
- Modify: `src/schema.sql`
- Modify: `src/init_db.py`
- Create: `src/database/__init__.py`
- Create: `src/database/status.py`
- Test: `tests/test_database_status.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: existing `paper`, `formulation`, `chemical_component`, `experiment`, `outcome`, and `evidence` tables.
- Produces: `ArmAssessment`, `assess_arm(connection, experiment_id, profile)`, provenance tables, review-history tables, and additive migrations.

- [ ] **Step 1: Write failing schema tests**

```python
def test_database_has_provenance_and_review_tables(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"record_source", "arm_assessment", "review_revision", "screening_event"} <= names
```

- [ ] **Step 2: Run the schema tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_schema.py tests/test_database_status.py`

Expected: FAIL because the new tables and `src.database.status` do not exist.

- [ ] **Step 3: Add the schema and additive migration**

Add tables with foreign keys and checks for:

```sql
CREATE TABLE IF NOT EXISTS arm_assessment (
    experiment_id INTEGER PRIMARY KEY,
    completeness_status TEXT NOT NULL
        CHECK (completeness_status IN ('complete','incomplete','conflict','quarantined')),
    missing_fields_json TEXT NOT NULL DEFAULT '[]',
    verification_status TEXT NOT NULL
        CHECK (verification_status IN ('unreviewed','automatically_validated','manually_verified','ambiguous','conflict','rejected')),
    nearest_neighbor_eligible INTEGER NOT NULL DEFAULT 0 CHECK (nearest_neighbor_eligible IN (0,1)),
    comet_eligible INTEGER NOT NULL DEFAULT 0 CHECK (comet_eligible IN (0,1)),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiment(experiment_id) ON DELETE CASCADE
);
```

Add `record_source`, `review_revision`, and `screening_event` with explicit paper/entity links, artifact path/hash, pipeline/version, prior/corrected values, evidence excerpt/location, reviewer, and timestamps. Extend `initialize_database()` with column/table-safe migrations for existing databases.

- [ ] **Step 4: Implement deterministic status profiles**

```python
@dataclass(frozen=True)
class ArmAssessment:
    completeness_status: Literal["complete", "incomplete", "conflict", "quarantined"]
    missing_fields: tuple[str, ...]
    verification_status: str
    nearest_neighbor_eligible: bool
    comet_eligible: bool


def assess_arm(
    connection: sqlite3.Connection,
    experiment_id: int,
    profile: Literal["evidence", "nearest_neighbor", "comet"],
) -> ArmAssessment:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM experiment WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown experiment_id: {experiment_id}")
    required = {
        "evidence": ("formulation_id", "cell_type", "payload_type"),
        "nearest_neighbor": ("formulation_id", "cell_type", "payload_type", "species", "in_vitro_in_vivo"),
        "comet": ("formulation_id", "cell_type", "payload_type", "species", "in_vitro_in_vivo", "dose", "dose_unit", "assay"),
    }[profile]
    missing = tuple(field for field in required if row[field] is None)
    relation_state = connection.execute(
        "SELECT verification_status FROM arm_assessment WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchone()
    verification = relation_state[0] if relation_state else "unreviewed"
    status = "conflict" if verification == "conflict" else "incomplete" if missing else "complete"
    return ArmAssessment(
        completeness_status=status,
        missing_fields=missing,
        verification_status=verification,
        nearest_neighbor_eligible=profile == "nearest_neighbor" and not missing and status == "complete",
        comet_eligible=profile == "comet" and not missing and verification == "manually_verified",
    )
```

The implementation must use fixed field lists per profile and evidence/relation state; it must never call an LLM or compare with a paper answer key.

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_schema.py tests/test_database_status.py`

Expected: PASS, including complete-to-incomplete, conflict, quarantine, nearest-neighbor, and COMET cases.

- [ ] **Step 6: Commit**

```bash
git add src/schema.sql src/init_db.py src/database tests/test_schema.py tests/test_database_status.py
git commit -m "feat: add evidence record status and provenance"
```

---

### Task 2: Build the current-corpus manifest and idempotent evidence importer

**Files:**
- Create: `config/database/current_corpus_v1.yaml`
- Create: `src/database/current_corpus.py`
- Create: `src/database/import_artifacts.py`
- Create: `tests/fixtures/database/current_corpus/`
- Test: `tests/test_import_artifacts.py`

**Interfaces:**
- Consumes: GP-001 through GP-009, NP-001, NP-002, PILOT-001 through PILOT-003 extraction artifacts and `current_corpus_v1.yaml`.
- Produces: `CorpusEntry`, `build_current_corpus_manifest(root)`, and `import_artifact(connection, entry)`.

- [ ] **Step 1: Write fixture-driven importer tests**

```python
def test_import_is_idempotent(database_path: Path, current_corpus_fixture: Path) -> None:
    first = import_manifest(database_path, current_corpus_fixture)
    second = import_manifest(database_path, current_corpus_fixture)
    assert first.inserted_entities > 0
    assert second.inserted_entities == 0
    assert second.unchanged_entities == first.inserted_entities


def test_excluded_paper_does_not_create_scientific_rows(
    database_path: Path,
    excluded_fixture: Path,
) -> None:
    result = import_manifest(database_path, excluded_fixture)
    assert result.screening_events == 1
    assert result.experiments == 0
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_import_artifacts.py`

Expected: FAIL because importer modules do not exist.

- [ ] **Step 3: Define the explicit current-corpus configuration**

The YAML must contain each paper ID, inclusion/exclusion disposition, source artifacts in priority order, source pipeline/version, and rerun policy. It must encode:

- GP-001, GP-003, GP-009: screening ledger only;
- GP-002, GP-005, GP-006: load verified evidence, no immediate rerun;
- GP-004, GP-007: load partial evidence, conditional rerun;
- GP-008: human biological-role review;
- NP-001: selective liver-relevant rerun;
- NP-002: high-priority selective rerun;
- PILOT-001 through PILOT-003: load merged evidence, no 62-item recall display.

- [ ] **Step 4: Implement artifact adapters and evidence-preserving union**

```python
@dataclass(frozen=True)
class ImportResult:
    inserted_entities: int
    unchanged_entities: int
    conflicts: int
    screening_events: int
    experiments: int


def import_manifest(database_path: Path, manifest_path: Path) -> ImportResult:
    entries = load_corpus_entries(manifest_path)
    with sqlite3.connect(database_path) as connection:
        results = [import_artifact(connection, entry) for entry in entries]
    return combine_import_results(results)
```

Use stable natural keys and content hashes. Prefer accepted, directly supported evidence over pipeline recency. Store conflicting supported values without choosing one silently.

- [ ] **Step 5: Generate and inspect the real manifest without importing**

Run: `.venv/bin/python -m src.database.current_corpus --check-only`

Expected: report 14 unique paper IDs, 11 included papers, and 3 screening-only exclusions; every included paper has at least one resolvable source artifact or an explicit unresolved reason.

- [ ] **Step 6: Run importer tests**

Run: `.venv/bin/python -m pytest -q tests/test_import_artifacts.py tests/test_database_status.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add config/database src/database/current_corpus.py src/database/import_artifacts.py tests/fixtures/database tests/test_import_artifacts.py
git commit -m "feat: import current extraction evidence"
```

---

### Task 3: Add grouped Excel export and evidence-backed human correction import

**Files:**
- Create: `src/database/export_workbook.py`
- Create: `src/database/import_review_workbook.py`
- Test: `tests/test_review_workbook.py`

**Interfaces:**
- Consumes: SQLite database and validated reviewer workbook.
- Produces: `export_evidence_workbook(database_path, output_path)` and `import_review_workbook(database_path, workbook_path, reviewer)`.

- [ ] **Step 1: Write round-trip and rejection tests**

```python
def test_workbook_groups_arms_by_paper_and_hides_run_id(
    database_path: Path,
    workbook_path: Path,
) -> None:
    export_evidence_workbook(database_path, workbook_path)
    workbook = openpyxl.load_workbook(workbook_path)
    headers = [cell.value for cell in workbook["Experimental Arms"][1]]
    assert "Extraction Run ID" not in headers
    assert {"Paper Title", "DOI", "Species", "Target Cell", "Delivery Cell", "Missing Fields"} <= set(headers)


def test_review_import_requires_value_excerpt_and_location(
    database_path: Path,
    invalid_workbook: Path,
) -> None:
    with pytest.raises(ReviewWorkbookError, match="evidence excerpt and location"):
        import_review_workbook(database_path, invalid_workbook, "reviewer@example.org")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_review_workbook.py`

Expected: FAIL because workbook modules do not exist.

- [ ] **Step 3: Implement workbook export**

Export tabs:

- `Experimental Arms`: grouped/sorted by paper title and DOI;
- `Evidence`: field, excerpt, section/page/table/figure/supplement, modality, verification;
- `Human Review Queue`: only arms one or two required fields from COMET eligibility;
- `Screened Papers`: internal screening disposition export;
- `Data Dictionary`: column definitions and accepted values.

- [ ] **Step 4: Implement controlled review import**

Only accept changes from the `Human Review Queue` tab. Require experiment ID, field, value, evidence excerpt, and evidence location. Insert `review_revision` and new manual `evidence`; never update a scientific field without history.

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_review_workbook.py tests/test_database_status.py`

Expected: PASS, including eligibility recalculation after a valid correction.

- [ ] **Step 6: Commit**

```bash
git add src/database/export_workbook.py src/database/import_review_workbook.py tests/test_review_workbook.py
git commit -m "feat: add evidence review workbook"
```

---

### Task 4: Add OpenAlex discovery, cross-source deduplication, and access resolution

**Files:**
- Modify: `src/search/run_discovery.py`
- Modify: `src/search/build_candidate_index.py`
- Create: `src/search/access_resolution.py`
- Modify: `docs/screening/screening_guide.md`
- Test: `tests/test_discovery_openalex.py`
- Test: `tests/test_search_normalization.py`
- Test: `tests/test_access_resolution.py`

**Interfaces:**
- Consumes: versioned four-cell query configuration and cached PubMed/OpenAlex/Europe PMC responses.
- Produces: normalized candidate records, deduplicated candidate manifest, and `AccessOption` records.

- [ ] **Step 1: Write cached-response discovery tests**

```python
def test_openalex_record_normalizes_identifiers(openalex_fixture: Path) -> None:
    record = parse_openalex_work(openalex_fixture)[0]
    assert record["source"] == "openalex"
    assert record["doi"] == "10.1000/example"
    assert record["pmid"] == "12345678"


def test_cross_source_duplicates_merge_cell_matches(
    pubmed_record: dict,
    openalex_record: dict,
    epmc_record: dict,
) -> None:
    merged = deduplicate_candidates([pubmed_record, openalex_record, epmc_record])
    assert len(merged) == 1
    assert merged[0]["matched_cell_types"] == ["hepatocyte", "kupffer_cell"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_discovery_openalex.py tests/test_search_normalization.py tests/test_access_resolution.py`

Expected: FAIL because OpenAlex/access adapters do not exist.

- [ ] **Step 3: Implement OpenAlex pagination and caching**

Follow the existing PubMed/Europe PMC cache and resume conventions. Preserve URL, request parameters, cursor/page, retrieval timestamp, and raw response path. Do not make network calls in tests.

- [ ] **Step 4: Implement access resolution**

```python
@dataclass(frozen=True)
class AccessOption:
    kind: Literal["europe_pmc_xml", "open_html", "open_pdf", "institution_link", "local_upload", "unavailable"]
    url_or_path: str | None
    license_status: str
    credential_storage_allowed: bool = False
```

Prioritize Europe PMC structured full text, open publisher sources, institutional link, local licensed upload, then unavailable. Reject credential-bearing URLs and ensure licensed local paths fall under ignored data directories.

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_discovery_openalex.py tests/test_search_normalization.py tests/test_access_resolution.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/search docs/screening/screening_guide.md tests/test_discovery_openalex.py tests/test_search_normalization.py tests/test_access_resolution.py
git commit -m "feat: expand discovery and full-text access"
```

---

### Task 5: Build manifest-driven expansion extraction with paid-call preflight

**Files:**
- Create: `src/extraction/expansion_manifest.py`
- Create: `src/extraction/prepare_expansion_batch.py`
- Create: `src/extraction/run_expansion_batch.py`
- Create: `config/extraction/expansion_route_v1.yaml`
- Test: `tests/test_expansion_manifest.py`
- Test: `tests/test_expansion_preflight.py`
- Test: `tests/test_expansion_runner.py`

**Interfaces:**
- Consumes: eligible full-text evidence inventories and `expansion_route_v1.yaml`.
- Produces: one Gate A request and normally two or three coherent Gate B requests per paper, a frozen preflight report, and validated import artifacts.

- [ ] **Step 1: Write manifest and call-count tests**

```python
def test_text_rich_paper_uses_one_gate_a_and_two_gate_b_calls(
    paper_fixture: PaperEvidence,
    route_config: ExpansionRoute,
) -> None:
    batch = prepare_expansion_batch([paper_fixture], route_config)
    assert [request.gate for request in batch.requests] == ["A", "B", "B"]


def test_runner_never_dispatches_unapproved_hash(
    batch: ExpansionBatch,
    fake_client: FakeExtractionClient,
) -> None:
    with pytest.raises(UnapprovedRequestError):
        run_expansion_batch(batch, approved_hashes=set(), client=fake_client)
    assert fake_client.calls == []
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_expansion_manifest.py tests/test_expansion_preflight.py tests/test_expansion_runner.py`

Expected: FAIL because expansion modules do not exist.

- [ ] **Step 3: Implement coherent experiment grouping**

Gate A consumes one paper map packet. Gate B groups complete related experiments with formulation, candidate/arm mapping, comparator, outcome, and relevant evidence. Do not split arbitrary evidence chunks. Papers needing more than three Gate B groups must be marked `complex` and shown separately in preflight.

- [ ] **Step 4: Implement exact preflight output**

```python
@dataclass(frozen=True)
class FrozenRequest:
    request_id: str
    paper_id: str
    gate: Literal["A", "B", "vision"]
    sha256: str
    estimated_input_tokens: int
    maximum_output_tokens: int
```

The report must show per-paper and batch totals and must not write an invocation marker before credential validation and approval.

- [ ] **Step 5: Implement resumable, no-silent-retry execution**

Dispatch each approved hash once. Record success, provider failure, validation failure, and skipped dependencies. A failed request advances the batch and requires a new explicit action for retry.

- [ ] **Step 6: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_expansion_manifest.py tests/test_expansion_preflight.py tests/test_expansion_runner.py`

Expected: PASS with fake clients only.

- [ ] **Step 7: Commit**

```bash
git add src/extraction/expansion_manifest.py src/extraction/prepare_expansion_batch.py src/extraction/run_expansion_batch.py config/extraction/expansion_route_v1.yaml tests/test_expansion_manifest.py tests/test_expansion_preflight.py tests/test_expansion_runner.py
git commit -m "feat: add expansion extraction batches"
```

---

### Task 6: Implement exact and controlled partial query services

**Files:**
- Create: `src/application/__init__.py`
- Create: `src/application/query_models.py`
- Create: `src/application/evidence_query.py`
- Test: `tests/test_evidence_query.py`

**Interfaces:**
- Consumes: SQLite evidence database and `EvidenceQuery`.
- Produces: `EvidenceResult` values classified as exact, partial, unknown, or incompatible.

- [ ] **Step 1: Write scientific boundary tests**

```python
def test_whole_liver_is_not_exact_hepatocyte_match(query_database: Path) -> None:
    results = search_evidence(query_database, EvidenceQuery(cell_type="hepatocyte"))
    assert results[0].match_class == "partial"
    assert "whole-liver" in results[0].differences["cell_type"]


def test_missing_dose_is_unknown_not_incompatible(query_database: Path) -> None:
    result = search_evidence(query_database, EvidenceQuery(dose=1.0))[0]
    assert result.field_matches["dose"] == "unknown"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_evidence_query.py`

Expected: FAIL because query services do not exist.

- [ ] **Step 3: Implement typed query and result models**

```python
class EvidenceQuery(BaseModel):
    cell_type: str | None = None
    payload_type: str | None = None
    species: str | None = None
    delivery_model: str | None = None
    organ: str | None = None
    route: str | None = None
    endpoint_family: str | None = None
    disease_model: str | None = None
```

Implement deterministic field comparison. Exact requires supported equality for every selected filter. Missing database values are unknown. Explicitly different values are incompatible or partial according to controlled field rules.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_evidence_query.py`

Expected: PASS for hepatocyte/liver, target/recipient, mRNA/siRNA, in-vitro/in-vivo, endpoint, and missing-field cases.

- [ ] **Step 5: Commit**

```bash
git add src/application tests/test_evidence_query.py
git commit -m "feat: add exact and partial evidence search"
```

---

### Task 7: Build and evaluate the nearest-reported-formulation index

**Files:**
- Create: `src/similarity/__init__.py`
- Create: `src/similarity/features.py`
- Create: `src/similarity/index.py`
- Create: `src/similarity/evaluate.py`
- Create: `config/similarity/feature_profile_v1.yaml`
- Create: `tests/fixtures/similarity/representative_queries.json`
- Test: `tests/test_similarity_features.py`
- Test: `tests/test_similarity_index.py`

**Interfaces:**
- Consumes: nearest-neighbor-eligible arms and versioned feature profile.
- Produces: `FeatureMatrixArtifact`, `build_similarity_index(database_path, profile, output_dir)`, and `query_neighbors(index, query, k)`.

- [ ] **Step 1: Write feature and leakage-boundary tests**

```python
def test_outcome_labels_are_not_similarity_features(feature_profile: FeatureProfile) -> None:
    assert "outcome_value" not in feature_profile.feature_names


def test_neighbor_result_separates_chemistry_and_context_scores(index_fixture) -> None:
    neighbor = query_neighbors(index_fixture, query_fixture, k=1)[0]
    assert 0.0 <= neighbor.chemistry_similarity <= 1.0
    assert 0.0 <= neighbor.context_similarity <= 1.0
    assert neighbor.result_type == "similarity_match"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_similarity_features.py tests/test_similarity_index.py`

Expected: FAIL because similarity modules do not exist.

- [ ] **Step 3: Implement feature construction**

Use verified component identities/roles and reported ratios. Use RDKit fingerprints only for verified structures. Encode payload, cell, species, delivery model, route, and endpoint separately. Exclude quarantined records and define missing indicators rather than mean-imputing unreported scientific facts.

- [ ] **Step 4: Implement index and explanations**

Fit scikit-learn `NearestNeighbors`. Persist the dataset checksum, profile version, row-to-formulation mapping, scaler/encoder artifacts, and index. Return component matches, ratio differences, context differences, and source paper IDs.

- [ ] **Step 5: Implement fixture-driven evaluation**

Run representative exact, sparse, conflicting, and no-result queries. Write a JSON review artifact containing neighbors and explanations for bounded human inspection; do not use outcome labels to tune weights.

- [ ] **Step 6: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_similarity_features.py tests/test_similarity_index.py`

Expected: PASS with deterministic index rebuilding.

- [ ] **Step 7: Commit**

```bash
git add src/similarity config/similarity tests/fixtures/similarity tests/test_similarity_features.py tests/test_similarity_index.py
git commit -m "feat: add reported formulation similarity"
```

---

### Task 8: Implement COMET readiness, leakage-safe manifests, and model registry

**Files:**
- Create: `src/modeling/__init__.py`
- Create: `src/modeling/readiness.py`
- Create: `src/modeling/splits.py`
- Create: `src/modeling/baselines.py`
- Create: `src/modeling/registry.py`
- Create: `config/modeling/comet_gate_v1.yaml`
- Test: `tests/test_model_readiness.py`
- Test: `tests/test_model_splits.py`
- Test: `tests/test_model_registry.py`

**Interfaces:**
- Consumes: COMET-eligible arms and task configuration.
- Produces: `ReadinessDecision`, leakage-safe manifests, baseline reports, and enabled/disabled `ModelRegistration`.

- [ ] **Step 1: Write readiness and disabled-state tests**

```python
def test_comet_no_go_below_compatible_arm_threshold() -> None:
    decision = assess_comet_readiness(records=compatible_records(99), minimum_arms=100)
    assert decision.status == "no_go"


def test_disabled_registry_refuses_prediction() -> None:
    registry = ModelRegistry.disabled(reason="insufficient compatible arms")
    with pytest.raises(ModelDisabledError, match="insufficient compatible arms"):
        registry.predict({})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_model_readiness.py tests/test_model_splits.py tests/test_model_registry.py`

Expected: FAIL because modeling modules do not exist.

- [ ] **Step 3: Implement readiness and task freezing**

Group by cell, payload, delivery model, endpoint, unit, and normalization. Count arms, papers, libraries, scaffolds, and laboratories when known. Require at least 100 compatible arms for `go`; support `integration_only` and `no_go` with explicit reasons.

- [ ] **Step 4: Implement grouped splits**

Keep each paper and related formulation sweep in one split. Prefer scaffold/library groups. Persist record IDs and checksums. Tests must prove no group crosses train/validation/test.

- [ ] **Step 5: Implement baselines and registry contract**

Provide mean/median, k-nearest-neighbor, random-forest, and gradient-boosting baselines when label type permits. Registry entries store dataset checksum, metrics, uncertainty method, domain rules, artifact path, and enabled status. COMET adapters must use the same contract and live in an isolated environment.

- [ ] **Step 6: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_model_readiness.py tests/test_model_splits.py tests/test_model_registry.py`

Expected: PASS for go, integration-only, no-go, leakage, and disabled UI behavior.

- [ ] **Step 7: Commit**

```bash
git add src/modeling config/modeling tests/test_model_readiness.py tests/test_model_splits.py tests/test_model_registry.py
git commit -m "feat: gate predictive model integration"
```

---

### Task 9: Build the Streamlit evidence application and review workflow

**Files:**
- Create: `src/application/app.py`
- Create: `src/application/pages/evidence_browser.py`
- Create: `src/application/pages/paper_detail.py`
- Create: `src/application/pages/review_queue.py`
- Create: `src/application/pages/model_status.py`
- Create: `src/application/presentation.py`
- Test: `tests/test_application_presentation.py`
- Test: `tests/test_application_queries.py`

**Interfaces:**
- Consumes: evidence query service, similarity index, model registry, workbook services, and SQLite.
- Produces: Streamlit pages and presentation-only row models.

- [ ] **Step 1: Write presentation tests**

```python
def test_presented_arm_repeats_same_target_and_delivery_cell() -> None:
    row = present_arm(arm_fixture(target_cell="hepatocyte", delivery_cell="hepatocyte"))
    assert row.target_cell == "hepatocyte"
    assert row.delivery_cell == "hepatocyte"


def test_presented_arm_uses_na_and_hides_run_id() -> None:
    row = present_arm(arm_fixture(dose=None))
    assert row.dose == "NA"
    assert not hasattr(row, "extraction_run_id")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_application_presentation.py tests/test_application_queries.py`

Expected: FAIL because application pages and presentation models do not exist.

- [ ] **Step 3: Implement presentation models and evidence browser**

Group experimental-arm rows beneath paper title and DOI. Add filters for liver cell, payload, species, delivery model, outcome, organ, route, and disease context. Display formulation ratio, target cell, delivery cell, arm status, missing fields, verification, nearest-neighbor eligibility, and COMET eligibility.

- [ ] **Step 4: Implement detail and evidence inspector**

Paper/detail navigation must show formulations, components, experiments, outcomes, evidence excerpt, section/page/table/figure/supplement, modality, review status, DOI, lawful full-text link, and institutional link.

- [ ] **Step 5: Implement review, similarity, and model states**

Review page accepts only evidence-backed corrections. Similarity page shows chemistry and context differences and the disclaimer that similarity is not efficacy. Model page shows predictions only for enabled tasks; otherwise it shows the registry reason.

- [ ] **Step 6: Run focused tests and Streamlit smoke check**

Run: `.venv/bin/python -m pytest -q tests/test_application_presentation.py tests/test_application_queries.py`

Run: `.venv/bin/streamlit run src/application/app.py --server.headless true --server.port 8506`

Expected: tests PASS and Streamlit health endpoint returns `ok`.

- [ ] **Step 7: Commit**

```bash
git add src/application tests/test_application_presentation.py tests/test_application_queries.py
git commit -m "feat: add liver LNP evidence application"
```

---

### Task 10: Add separate exports, corpus status, and refresh orchestration

**Files:**
- Create: `src/application/exports.py`
- Create: `src/application/corpus_status.py`
- Create: `src/application/refresh.py`
- Test: `tests/test_application_exports.py`
- Test: `tests/test_corpus_status.py`
- Test: `tests/test_refresh_workflow.py`

**Interfaces:**
- Consumes: database, discovery services, expansion preflight, import services, and model registry.
- Produces: evidence export, prediction export, status summary, and resumable refresh state machine.

- [ ] **Step 1: Write separation and refresh tests**

```python
def test_reported_export_contains_no_predictions(
    database_path: Path,
    output_path: Path,
) -> None:
    export_reported_evidence(database_path, output_path)
    assert "predicted_score" not in read_headers(output_path)


def test_refresh_stops_at_paid_preflight(
    database_path: Path,
    fake_discovery: FakeDiscoveryClient,
    fake_provider: FakeExtractionClient,
) -> None:
    state = run_refresh(database_path, fake_discovery, approved_hashes=set())
    assert state.phase == "awaiting_paid_call_approval"
    assert fake_provider.calls == []
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_application_exports.py tests/test_corpus_status.py tests/test_refresh_workflow.py`

Expected: FAIL because export/status/refresh modules do not exist.

- [ ] **Step 3: Implement evidence and prediction exports**

Reported export includes paper IDs, arm fields, outcome, evidence excerpt/location, verification, and missing fields. Prediction export includes task/model/dataset versions, predicted score, uncertainty, domain status, and `untested` label. No row may appear in both exports under the same result type.

- [ ] **Step 4: Implement status and refresh state machine**

Refresh phases are discovery, deduplication, screening, access resolution, local ingestion, paid preflight, extraction, validation, import, assessment, and completion. Persist phase, paper-level result, request hashes, and failure reason. Resume only from durable state.

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/test_application_exports.py tests/test_corpus_status.py tests/test_refresh_workflow.py`

Expected: PASS, including a failed-paper continuation case.

- [ ] **Step 6: Commit**

```bash
git add src/application/exports.py src/application/corpus_status.py src/application/refresh.py tests/test_application_exports.py tests/test_corpus_status.py tests/test_refresh_workflow.py
git commit -m "feat: add refresh and transparent exports"
```

---

### Task 11: Populate the real database and freeze Evidence Dataset v1

**Files:**
- Create through execution: `data/curated/lnp_evidence.db`
- Create through execution: `data/curated/manifests/evidence_dataset_v1.json`
- Create through execution: `reports/database/current_corpus_import.md`
- Create through execution: `reports/database/expansion_checkpoint_a.md`
- Create through execution: `reports/database/evidence_dataset_v1.md`
- Test: `tests/test_evidence_dataset_release.py`

**Interfaces:**
- Consumes: approved current-corpus manifest and approved paid expansion batches.
- Produces: frozen Evidence Dataset v1, release manifest, and readiness report.

- [ ] **Step 1: Import current artifacts offline**

Run: `.venv/bin/python -m src.database.import_artifacts --manifest config/database/current_corpus_v1.yaml --database data/curated/lnp_evidence.db`

Expected: 14 paper dispositions, 3 screening-only exclusions, and supported arms from 11 included papers.

- [ ] **Step 2: Export and inspect the current-corpus workbook**

Run: `.venv/bin/python -m src.database.export_workbook --database data/curated/lnp_evidence.db --output reports/database/current_corpus.xlsx`

Expected: grouped papers, one row per arm, explicit `NA`, evidence links, and no paper-level extraction denominator.

- [ ] **Step 3: Prepare selective rerun and expansion preflights**

Run the preflight command only. Present exact calls, hashes, and tokens to the user. Do not dispatch until separately approved.

- [ ] **Step 4: Execute only approved batches and import validated results**

Use the Week 1-3 cadence in `LNP_Liver_Tool_v8_Completion_Timeline.pdf`. After each batch, run validators, import accepted records, and write paper-level failures without silent retries.

- [ ] **Step 5: Apply dataset readiness gates**

Verify:

- at least 30 representation-compatible arms per cell group where literature permits;
- COMET `go` only with at least 100 compatible arms in one coherent family;
- if fewer than 30% of extracted arms are fully verified/eligible, publish the bottleneck before further scale-up.

- [ ] **Step 6: Freeze the release manifest**

The manifest must include schema version, source/artifact hashes, imported paper/arm/outcome/evidence counts, review states, eligibility counts, discovery query versions, extraction request hashes, calls, tokens, model-readiness status, and timestamp.

- [ ] **Step 7: Run release-data tests**

Run: `.venv/bin/python -m pytest -q tests/test_evidence_dataset_release.py`

Expected: PASS for referential integrity, evidence coverage, provenance, no prediction contamination, and stable manifest checksums.

- [ ] **Step 8: Commit code and non-licensed manifests only**

```bash
git add data/curated/manifests reports/database tests/test_evidence_dataset_release.py
git commit -m "data: freeze evidence dataset v1"
```

Do not commit licensed PDFs, credentials, or unredacted provider responses.

---

### Task 12: Complete end-to-end verification and release

**Files:**
- Create: `tests/test_application_end_to_end.py`
- Create: `docs/release/lnp_liver_tool_v1.md`
- Create through execution: `reports/release/lnp_liver_tool_v1_test_report.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Evidence Dataset v1, Similarity Index v1, model registry, and Streamlit app.
- Produces: release documentation, automated end-to-end evidence, and release tag candidate.

- [ ] **Step 1: Write end-to-end workflow tests**

Cover:

- exact hepatocyte query;
- sparse Kupffer, LSEC, and HSC query;
- whole-liver partial match;
- nearest-neighbor retrieval;
- enabled and disabled prediction routes;
- evidence inspection;
- human correction and eligibility recalculation;
- separate evidence/prediction exports;
- refresh stopping at paid preflight;
- institutional link without credential persistence.

- [ ] **Step 2: Run the focused end-to-end test**

Run: `.venv/bin/python -m pytest -q tests/test_application_end_to_end.py`

Expected: PASS with fixtures and fake providers only.

- [ ] **Step 3: Run the complete offline suite**

Run: `OPENAI_API_KEY= SENSENOVA_API_KEY= .venv/bin/python -m pytest -q`

Expected: PASS with no provider dispatch.

- [ ] **Step 4: Run Streamlit health and manual smoke checks**

Verify filters, paper grouping, detail views, evidence excerpts, `NA`, missing fields, eligibility, similarity disclaimers, disabled model state, exports, and refresh preflight.

- [ ] **Step 5: Write release documentation**

Document installation, database initialization, current-corpus import, discovery refresh, institutional access, licensed PDF upload location, paid-call approval, human review, similarity rebuild, model registry, backup, restore, and rollback.

- [ ] **Step 6: Commit the release candidate**

```bash
git add tests/test_application_end_to_end.py docs/release README.md reports/release/lnp_liver_tool_v1_test_report.md
git commit -m "release: complete liver LNP evidence application"
```

- [ ] **Step 7: Tag only after explicit user approval**

Run: `git tag -a lnp-liver-tool-v1 -m "LNP Liver Tool v1"`

Expected: tag created only after the user reviews the test report and release candidate.

---

## Final Acceptance Checklist

- [ ] All current supported papers and arms are loaded; excluded papers remain screening-only.
- [ ] Every displayed literature value links to evidence and provenance.
- [ ] Missing values and missing fields are explicit.
- [ ] No AI-created paper denominator is displayed as human gold.
- [ ] Exact, partial, similarity, prediction, candidate, and measured-result states are distinct.
- [ ] Nearest-neighbor results contain only reported formulations and separate chemistry/context similarity.
- [ ] COMET is enabled only after readiness, leakage, reproducibility, baseline, uncertainty, and domain gates pass.
- [ ] A COMET no-go leaves the evidence and similarity application complete.
- [ ] Paid extraction requires visible preflight and has no silent retries.
- [ ] Institutional credentials and licensed PDFs are not persisted in Git.
- [ ] Evidence and prediction exports remain separate.
- [ ] Complete offline and end-to-end test suites pass.
