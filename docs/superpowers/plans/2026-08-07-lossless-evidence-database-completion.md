# Lossless Evidence Database Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert every approved fact and evidence item in the existing 14-paper JSON corpus into a verified SQLite database, merge only necessary selective reruns, and publish honest, separately defined usability counts.

**Architecture:** Extend the existing current-corpus manifest into a complete contributor registry. Import all three JSON schema families into an immutable source-fact ledger, then project and deduplicate them into the existing normalized scientific tables. Rebuild in a temporary database, close local and supplementary evidence gaps before preparing bounded reruns, and promote the database only after source-to-SQLite coverage, provenance, deduplication, eligibility, and reproducibility gates pass.

**Tech Stack:** Python 3.14, dataclasses, JSON, SQLite, pytest, existing PyMuPDF/Docling/vision ingestion, SHA-256 manifests, existing extraction runners.

## Global Constraints

- Scope is GP-001–GP-009, NP-001–NP-002, and PILOT-001–PILOT-003 only.
- GP-001, GP-003, and GP-009 remain screening-only.
- Do not discover, screen, or extract new papers in this plan.
- Use `config/database/current_corpus_v1.json`; do not create a competing corpus manifest.
- Keep original JSON files local; store their immutable paths and hashes plus fact-level raw values and JSON paths in SQLite.
- Import all approved facts before canonical deduplication.
- Silent source-fact or evidence omission is a build failure.
- Keep formulation name, chemical composition, and payload separate.
- Never equate paper, named formulation, unique composition, fact, arm, outcome, or evidence counts.
- Paid calls require exact immutable request hashes and explicit human approval; never retry silently.
- Do not use the CodeRabbit CLI or CodeRabbit review workflow. Review through repository tests, deterministic audits, and direct human inspection only.
- Expose `lnp_formulation_wide` with exactly this ordered column contract: `lnp_name`, `chemical_formulation_total`, `lnp_molar_ratio`, `ionizable_lipid`, `helper_lipid`, `cholesterol`, `peg_lipid`, `others`.
- Build and validate a temporary SQLite database before replacing `data/curated/lnp_evidence.db`.
- Do not overwrite human review history or an existing supported value without retaining provenance.

---

### Task 1: Establish one implementation baseline and protect the current database

**Files:**
- Read: `src/database/`
- Read: `tests/test_current_corpus_import.py`
- Create during execution: `reports/database/pre_rebuild_snapshot.json`
- Create during execution: timestamped backup beside `data/curated/lnp_evidence.db`

**Interfaces:**
- Consumes: branch `codex/day1-current-corpus` at or after commit `ccf2261`.
- Produces: one isolated `codex/lossless-evidence-db` worktree, `snapshot_database(path: Path) -> dict[str, object]`, and an immutable pre-rebuild audit.

- [ ] **Step 1: Create the isolated implementation worktree using `superpowers:using-git-worktrees`**

Use `codex/day1-current-corpus` as the baseline because it already contains the integrated database, importer, audit, and review code. Do not start from `main`, which does not contain those files.

- [ ] **Step 2: Write a failing snapshot test**

Add to `tests/test_database_lifecycle.py`:

```python
def test_snapshot_records_hash_schema_and_counts(tmp_path: Path) -> None:
    database = build_fixture_database(tmp_path / "source.db")
    report = snapshot_database(database)
    assert report["sha256"] == sha256(database)
    assert report["integrity"] == "ok"
    assert report["counts"]["paper"] == 1
    assert report["migration_versions"]
```

- [ ] **Step 3: Run the focused test and confirm it fails**

Run: `.venv/bin/python -m pytest -q tests/test_database_lifecycle.py::test_snapshot_records_hash_schema_and_counts`

Expected: FAIL because `snapshot_database` does not exist.

- [ ] **Step 4: Implement the snapshot helper and create the backup**

Add the helper to `src/database/database_lifecycle.py`. It must run `PRAGMA integrity_check`, enumerate migration versions and scientific-table counts, and hash the database bytes. Copy the current database through the existing lifecycle backup function; do not use a destructive shell command.

- [ ] **Step 5: Verify snapshot and existing lifecycle tests**

Run: `.venv/bin/python -m pytest -q tests/test_database_lifecycle.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/database/database_lifecycle.py tests/test_database_lifecycle.py reports/database/pre_rebuild_snapshot.json
git commit -m "chore: snapshot evidence database before rebuild"
```

---

### Task 2: Extend the existing manifest into a complete contributor registry

**Files:**
- Modify: `config/database/current_corpus_v1.json`
- Modify: `src/database/corpus_manifest.py`
- Modify: `src/database/build_current_corpus.py`
- Modify: `tests/test_corpus_manifest.py`
- Modify: `tests/test_build_current_corpus.py`

**Interfaces:**
- Consumes: existing `CorpusEntry` and `ArtifactCandidate` definitions.
- Produces: `ContributingArtifact`, `CorpusEntry.contributing_artifacts`, and `validate_artifact_coverage(entries, root) -> None`.

- [ ] **Step 1: Write failing manifest-contract tests**

```python
def test_manifest_accepts_multiple_contributing_artifacts() -> None:
    entry = entry_from_dict({
        **BASE_ENTRY,
        "primary_artifact": "graph.json",
        "contributing_artifacts": [
            artifact("graph.json", role="primary_extraction", contributes_facts=True),
            artifact("packet.json", role="evidence_inventory", contributes_evidence=True),
            artifact("supp.pdf", role="supplement", contributes_evidence=True),
        ],
    })
    assert len(entry.contributing_artifacts) == 3


def test_manifest_rejects_unlisted_primary_artifact() -> None:
    with pytest.raises(ValueError, match="primary artifact must be a contributor"):
        entry_from_dict({**BASE_ENTRY, "primary_artifact": "missing.json", "contributing_artifacts": []})


def test_manifest_rejects_hashless_available_contributor() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        entry_from_dict({
            **BASE_ENTRY,
            "contributing_artifacts": [artifact("result.json", sha256=None)],
        })
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_corpus_manifest.py tests/test_build_current_corpus.py`

Expected: FAIL because the contributor contract is absent.

- [ ] **Step 3: Implement contributor roles and validation**

Support exactly these roles:

```python
ArtifactRole = Literal[
    "primary_extraction", "contributing_extraction", "repair", "reconciliation",
    "vision", "annotation", "validation", "evidence_inventory", "source_document",
    "supplement",
]
```

Each available artifact must have a real path and SHA-256. Each primary artifact must also appear in `contributing_artifacts`. Screening-only entries may have source/validation artifacts but no fact-producing extraction artifact.

- [ ] **Step 4: Populate all 14 entries**

For each paper, enumerate every approved fact- or evidence-contributing artifact. At minimum include:

- GP accepted graphs, compact packets, source clauses, gold annotations, local XML/PDF/supplements, and accepted repair/vision results;
- NP-001 validated result, packet, source assets, and accepted Docling/vision artifacts;
- all three NP-002 cell-scoped result files, reconciliation/merge artifacts, packet, and source assets;
- PILOT consolidated result, recovered inventory/source assets, validation report, and reference bindings as debugging-only validation—not human gold.

- [ ] **Step 5: Add an artifact-coverage report**

`build_current_corpus.py` must report per paper: contributor count, missing files, hash mismatches, fact-producing artifacts, evidence-producing artifacts, and primary artifact.

- [ ] **Step 6: Verify the complete manifest**

Run: `.venv/bin/python -m pytest -q tests/test_corpus_manifest.py tests/test_build_current_corpus.py`

Expected: PASS with exactly 14 paper entries and zero unaccounted selected artifacts.

- [ ] **Step 7: Commit**

```bash
git add config/database/current_corpus_v1.json src/database/corpus_manifest.py src/database/build_current_corpus.py tests/test_corpus_manifest.py tests/test_build_current_corpus.py
git commit -m "feat: register all current-corpus contributors"
```

---

### Task 3: Add the lossless fact-ledger migration

**Files:**
- Modify: `src/database/migrations.py`
- Modify: `src/schema.sql`
- Modify: `tests/test_database_migrations.py`
- Modify: `tests/test_schema.py`

**Interfaces:**
- Consumes: existing migration version 5 and existing normalized scientific tables.
- Produces: migration version 6 with `source_artifact`, `source_fact`, `source_fact_evidence`, `fact_projection`, general component amount/order fields, and the exact eight-column `lnp_formulation_wide` SQLite interface.

- [ ] **Step 1: Write failing migration tests**

```python
def test_lossless_fact_tables_exist_after_migration(connection: sqlite3.Connection) -> None:
    migrate_database(connection)
    tables = sqlite_tables(connection)
    assert {"source_artifact", "source_fact", "source_fact_evidence", "fact_projection"} <= tables


def test_source_fact_requires_visible_disposition(connection: sqlite3.Connection) -> None:
    migrate_database(connection)
    with pytest.raises(sqlite3.IntegrityError):
        insert_source_fact(connection, import_disposition="")


def test_fact_projection_references_same_paper(connection: sqlite3.Connection) -> None:
    migrate_database(connection)
    with pytest.raises(sqlite3.IntegrityError):
        insert_cross_paper_projection(connection)


def test_wide_formulation_column_order_is_exact(connection: sqlite3.Connection) -> None:
    migrate_database(connection)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(lnp_formulation_wide)")]
    assert columns == [
        "lnp_name",
        "chemical_formulation_total",
        "lnp_molar_ratio",
        "ionizable_lipid",
        "helper_lipid",
        "cholesterol",
        "peg_lipid",
        "others",
    ]
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_database_migrations.py tests/test_schema.py`

Expected: FAIL because migration version 6 and the tables are absent.

- [ ] **Step 3: Implement the additive schema**

Create tables with these required identities:

```sql
CREATE TABLE source_artifact (
    source_artifact_id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES paper(paper_id),
    logical_path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    role TEXT NOT NULL,
    schema_family TEXT NOT NULL,
    pipeline_name TEXT,
    pipeline_version TEXT,
    validation_status TEXT NOT NULL,
    contributes_facts INTEGER NOT NULL CHECK(contributes_facts IN (0,1)),
    contributes_evidence INTEGER NOT NULL CHECK(contributes_evidence IN (0,1)),
    UNIQUE(paper_id, sha256, role)
);

CREATE TABLE source_fact (
    source_fact_id INTEGER PRIMARY KEY,
    source_artifact_id INTEGER NOT NULL REFERENCES source_artifact(source_artifact_id),
    paper_id INTEGER NOT NULL REFERENCES paper(paper_id),
    json_path TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    record_kind TEXT NOT NULL,
    source_context_key TEXT,
    subject_type TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    field_name TEXT NOT NULL,
    raw_value_json TEXT NOT NULL CHECK(json_valid(raw_value_json)),
    canonical_value_json TEXT CHECK(canonical_value_json IS NULL OR json_valid(canonical_value_json)),
    fact_identity_sha256 TEXT NOT NULL CHECK(length(fact_identity_sha256) = 64),
    import_disposition TEXT NOT NULL CHECK(import_disposition IN ('projected','unresolved','quarantined','rejected')),
    disposition_reason TEXT,
    UNIQUE(source_artifact_id, json_path, source_record_key, field_name)
);
```

`source_fact_evidence` stores original evidence identifiers and optional resolved canonical `evidence_id`. `fact_projection` stores canonical entity type, entity ID, field, canonical fact hash, and projection status. Add triggers that reject cross-paper projections and projected facts without a projection row.

Add general component fields `amount_value`, `amount_unit`, `amount_raw`, and `composition_position`. Retain `molar_percentage` for backwards compatibility, but populate it only for actual mol%. Permit explicit roles `targeting_ligand`, `targeting_anchor`, `adjuvant`, and `small_molecule_additive` in addition to the four core composition roles.

Create `lnp_formulation_wide` with exactly the approved eight columns. It must aggregate detailed component rows into one named-formulation row, preserve explicit composition order, join multiple values in the same role with `; `, and place non-core components plus their reported details in `others`.

Add a fixture-backed behavior test for the approved GP-008 row:

```python
def test_wide_formulation_renders_gp008_as_one_row(connection: sqlite3.Connection) -> None:
    seed_gp008_formulation(connection)
    row = connection.execute("SELECT * FROM lnp_formulation_wide").fetchone()
    assert tuple(row) == (
        "alpha-CD163/LNP-FAPCAR",
        "ionizable lipid-DSPC-cholesterol-PEG-lipid",
        "45:30:23.5:1.5",
        "heptadecan-9-yl... amino lipid",
        "DSPC",
        "cholesterol",
        "PEG-lipid",
        "DSPE-PEG-maleimide; anti-CD163 antibody; antibody:LNP 1:20",
    )
```

- [ ] **Step 4: Preserve migration idempotence and legacy data**

Run the migration twice on a fixture database containing legacy paper, formulation, experiment, outcome, and evidence rows. Assert identical rows after the second run.

- [ ] **Step 5: Verify migration and schema tests**

Run: `.venv/bin/python -m pytest -q tests/test_database_migrations.py tests/test_schema.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/database/migrations.py src/schema.sql tests/test_database_migrations.py tests/test_schema.py
git commit -m "feat: add lossless source fact ledger"
```

---

### Task 4: Implement stable fact, evidence, and composition identities

**Files:**
- Create: `src/database/scientific_identity.py`
- Create: `tests/test_scientific_identity.py`

**Interfaces:**
- Produces:
  - `fact_identity(paper_id, subject_type, context_key, field_name, normalized_value) -> str`
  - `evidence_identity(paper_id, artifact_sha256, locator, excerpt, structured_evidence) -> str`
  - `composition_fingerprint(components: Sequence[CompositionPart]) -> str | None`

- [ ] **Step 1: Write failing identity tests**

```python
def test_fact_identity_deduplicates_formatting_not_context() -> None:
    first = fact_identity("P1", "arm", "A1", "dose", "0.30 mg/kg")
    same = fact_identity("P1", "arm", "A1", "dose", "0.3 mg/kg")
    other_arm = fact_identity("P1", "arm", "A2", "dose", "0.3 mg/kg")
    assert first == same
    assert first != other_arm


def test_evidence_identity_preserves_distinct_locations() -> None:
    a = evidence_identity("P1", HASH, {"page": 4}, "ratio 50:10:38.5:1.5", None)
    b = evidence_identity("P1", HASH, {"page": 8}, "ratio 50:10:38.5:1.5", None)
    assert a != b


def test_composition_fingerprint_ignores_component_order() -> None:
    assert composition_fingerprint(PARTS) == composition_fingerprint(reversed(PARTS))
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_scientific_identity.py`

- [ ] **Step 3: Implement canonical normalization**

Normalize Unicode, whitespace, numeric formatting, unit aliases, and component roles. Never infer missing units, percentages, identities, or ratios. Include targeting anchors and surface ligands in the composition fingerprint when they define the prepared particle.

- [ ] **Step 4: Test conflict preservation**

Add cases proving that `45 mol%` and `50 mol%` do not deduplicate, unknown compositions return no fingerprint, and identical text from two source files remains two evidence records.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest -q tests/test_scientific_identity.py`

```bash
git add src/database/scientific_identity.py tests/test_scientific_identity.py
git commit -m "feat: define scientific deduplication identities"
```

---

### Task 5: Build a shared source-fact importer and coverage gate

**Files:**
- Create: `src/database/source_fact_import.py`
- Create: `src/database/source_fact_audit.py`
- Create: `tests/test_source_fact_import.py`
- Create: `tests/test_source_fact_audit.py`

**Interfaces:**
- Produces:
  - `SourceFactRecord`
  - `import_source_facts(connection, artifact, facts) -> SourceFactImportResult`
  - `audit_source_fact_coverage(connection, artifact_id) -> SourceFactCoverage`

- [ ] **Step 1: Write failing import and audit tests**

```python
def test_every_source_fact_gets_one_visible_disposition(connection: sqlite3.Connection) -> None:
    facts = [projected_fact(), unresolved_fact(), quarantined_fact(), rejected_fact()]
    result = import_source_facts(connection, ARTIFACT, facts)
    assert result.source_count == 4
    assert result.accounted_count == 4
    assert audit_source_fact_coverage(connection, result.artifact_id).silent_omissions == ()


def test_audit_fails_silent_omission(connection: sqlite3.Connection) -> None:
    seed_source_fact_without_projection_or_reason(connection)
    with pytest.raises(ValueError, match="silent source-fact omission"):
        audit_source_fact_coverage(connection, ARTIFACT_ID)
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_source_fact_import.py tests/test_source_fact_audit.py`

- [ ] **Step 3: Implement transaction-safe import**

Use savepoints per artifact. Insert source occurrences first. Projected facts must link to a normalized entity/field; unresolved, quarantined, and rejected facts must include a reason. Reimporting identical bytes is idempotent.

- [ ] **Step 4: Implement exact coverage equality**

Calculate and assert:

```python
source_count == projected_count + unresolved_count + quarantined_count + rejected_count
```

Separately assert that every declared source evidence ID is resolved or explicitly rejected.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest -q tests/test_source_fact_import.py tests/test_source_fact_audit.py`

```bash
git add src/database/source_fact_import.py src/database/source_fact_audit.py tests/test_source_fact_import.py tests/test_source_fact_audit.py
git commit -m "feat: enforce source fact import coverage"
```

---

### Task 6: Replace the GP adapter with complete claim accounting

**Files:**
- Modify: `src/database/adapters/accepted_graph.py`
- Create: `tests/test_accepted_graph_lossless_adapter.py`
- Use fixture: `data/staging/extraction/g1_fulltext_rag/GP-008/accepted_graph.json`
- Use evidence: `data/staging/rag/compact_api_packets_v1/GP-008.json`

**Interfaces:**
- Consumes: `fact_identity`, `SourceFactRecord`, existing `ImportBundle` records.
- Produces: `adapt_accepted_graph_losslessly(...) -> ImportBundleWithFacts`.

- [ ] **Step 1: Write failing GP accounting tests**

```python
def test_gp_adapter_accounts_for_every_entity_claim_and_experiment() -> None:
    result = adapt_accepted_graph_losslessly(FIXTURE)
    assert result.coverage.source_entities == len(FIXTURE_JSON["entities"])
    assert result.coverage.source_claims == len(FIXTURE_JSON["claims"])
    assert result.coverage.source_experiments == len(FIXTURE_JSON["experiments"])
    assert result.coverage.silent_omissions == 0


def test_unknown_predicate_is_preserved_not_dropped() -> None:
    result = adapt_accepted_graph_losslessly(graph_with_predicate("novel_relation"))
    fact = only(result.source_facts)
    assert fact.field_name == "novel_relation"
    assert fact.import_disposition in {"unresolved", "quarantined"}
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_accepted_graph_lossless_adapter.py`

- [ ] **Step 3: Enumerate every GP source record before projection**

Remove the behavior where unsupported predicates or unlinked experiments disappear. Preserve claim membership and evidence before applying the known-predicate mapping.

- [ ] **Step 4: Restore composition evidence from approved contributors**

Join accepted-graph formulation identities to evidence-packet/gold-annotation facts without inventing cross-formulation ownership. Tests must assert:

```python
assert composition("GP-002") == "SM-102:DSPC:cholesterol:DMG-PEG2000 = 50:10:38.5:1.5"
assert component_percentages("GP-008") == [45.0, 30.0, 23.5, 1.5]
assert targeting_ratio("GP-008") == "1:20"
```

- [ ] **Step 5: Verify all GP adapters**

Run: `.venv/bin/python -m pytest -q tests/test_accepted_graph_adapter.py tests/test_accepted_graph_lossless_adapter.py`

Expected: all GP-002, GP-004, GP-005, GP-006, GP-007, and GP-008 source records accounted for.

- [ ] **Step 6: Commit**

```bash
git add src/database/adapters/accepted_graph.py tests/test_accepted_graph_lossless_adapter.py
git commit -m "fix: preserve every accepted graph fact"
```

---

### Task 7: Replace the NP adapter and reconcile NP-002 before reruns

**Files:**
- Modify: `src/database/adapters/np_results.py`
- Modify: `src/database/reconcile_np002.py`
- Create: `tests/test_np_lossless_adapter.py`
- Create: `tests/test_reconcile_np002.py`

**Interfaces:**
- Consumes: all NP result paths registered in the manifest.
- Produces: one source fact per reported field, review fact per unresolved item, and deduplicated normalized formulation/components/arms/outcomes.

- [ ] **Step 1: Write failing NP source-field tests**

```python
def test_np_adapter_accounts_for_every_reported_field() -> None:
    result = build_np_bundle_with_facts(result_paths=[NP001], packet_path=PACKET, paper_metadata=META)
    assert result.coverage.silent_omissions == 0
    assert result.source_fact_count == count_reported_fields(NP001_JSON) + len(NP001_JSON["unresolved_items"])


def test_np002_components_are_not_repeated_across_cell_slices() -> None:
    result = build_np_bundle_with_facts(result_paths=NP002_CELL_RESULTS, packet_path=NP002_PACKET, paper_metadata=META)
    assert component_keys(result, "MC3 LNP") == {
        ("MC3", 50.0), ("cholesterol", 38.5), ("C14 PEG 2000", 1.5), ("DSPC", 10.0)
    }
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_np_lossless_adapter.py tests/test_reconcile_np002.py`

- [ ] **Step 3: Import every reported field before normalization**

Create source facts for formulation, component, experiment, and outcome fields even when the normalized schema cannot yet accept the value. Preserve `unresolved_items` as review facts with source slice and evidence links.

- [ ] **Step 4: Reconcile NP-002 by scientific identity**

Merge shared formulation/components once. Retain all 13 cell-scoped arms and their slice-specific evidence. Do not merge arms across recipient cell, payload, dose, route, timepoint, comparator, or endpoint context.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest -q tests/test_np_lossless_adapter.py tests/test_reconcile_np002.py tests/test_np_database_adapter.py`

```bash
git add src/database/adapters/np_results.py src/database/reconcile_np002.py tests/test_np_lossless_adapter.py tests/test_reconcile_np002.py
git commit -m "fix: preserve and reconcile NP extraction facts"
```

---

### Task 8: Import PILOT facts without treating failed acceptance as zero science

**Files:**
- Modify: `src/database/adapters/pilot_results.py`
- Modify: `src/database/recover_pilot_artifacts.py`
- Create: `tests/test_pilot_lossless_adapter.py`
- Modify: `tests/test_pilot_database_recovery.py`

**Interfaces:**
- Consumes: consolidated `extraction.papers[].shared_facts`, `experiments[].facts`, validation findings, and recovered source inventory.
- Produces: quarantined source facts and safely linked normalized entities where provenance is validated.

- [ ] **Step 1: Write failing PILOT preservation tests**

```python
@pytest.mark.parametrize("paper_id,experiments,experiment_facts,shared_facts", [
    ("PILOT-001", 5, 145, 16),
    ("PILOT-002", 5, 182, 31),
    ("PILOT-003", 4, 144, 9),
])
def test_pilot_source_facts_survive_failed_acceptance(paper_id, experiments, experiment_facts, shared_facts) -> None:
    result = build_pilot_bundle_with_facts(CONSOLIDATED, paper_id, recovery_for(paper_id))
    assert result.source_experiment_count == experiments
    assert result.experiment_fact_count == experiment_facts
    assert result.shared_fact_count == shared_facts
    assert result.coverage.silent_omissions == 0
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_pilot_lossless_adapter.py`

- [ ] **Step 3: Parse shared and dotted outcome facts**

Parse fields such as `outcome.OUT-1.endpoint`, retain `experiment_id` and `candidate_id`, and link every evidence ID. Failed validation creates a quarantine reason; it must not result in empty fact/experiment collections.

- [ ] **Step 4: Promote only source-validated relationships**

When recovered source bytes and evidence locators validate, project facts into normalized rows. Otherwise leave them visible in the fact ledger and review queue. Never use the Codex-authored reference as human gold.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest -q tests/test_pilot_lossless_adapter.py tests/test_pilot_database_recovery.py`

```bash
git add src/database/adapters/pilot_results.py src/database/recover_pilot_artifacts.py tests/test_pilot_lossless_adapter.py
git commit -m "fix: retain PILOT experimental facts"
```

---

### Task 9: Generalize supplement closure for the current corpus

**Files:**
- Create: `src/rag/current_corpus_assets.py`
- Modify: `src/rag/ingestion.py`
- Modify: `src/screening/retrieve_gold_oa_packages.py`
- Create: `tests/test_current_corpus_assets.py`

**Interfaces:**
- Produces:
  - `inventory_local_assets(entry, root) -> AssetInventory`
  - `resolve_declared_supplements(entry, *, allow_network: bool) -> AssetResolution`
  - `ingest_current_corpus_assets(entry, assets) -> list[DocumentBlock]`

- [ ] **Step 1: Write failing local-first tests**

```python
def test_gp008_uses_existing_supplement_without_network(monkeypatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    assets = resolve_declared_supplements(GP008_ENTRY, allow_network=False)
    assert any(path.name == "pnas.2534673123.sapp.pdf" for path in assets.local_files)


def test_asset_classifier_ignores_navigation_links() -> None:
    assert classify_link("About this journal", "/about") is None
    assert classify_link("Supplementary Table S1", "mmc1.xlsx") == "supplement"
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv-rag/bin/python -m pytest -q tests/test_current_corpus_assets.py`

- [ ] **Step 3: Implement local inventory and declared-link classification**

Search registered directories and package manifests first. Parse JATS/HTML links for scientific supplement candidates, including opaque filenames declared as supplementary material. Do not fetch arbitrary hyperlinks.

- [ ] **Step 4: Add controlled fallbacks**

Use PMC/Europe PMC package endpoints before publisher pages. Browser-assisted publisher download is a manual/access fallback and must add the acquired asset path/hash to the manifest before ingestion. Network failure records an explicit access blocker.

- [ ] **Step 5: Route file types**

Text PDF → PyMuPDF; complex table PDF → Docling; image-only figure/table → existing selective-vision preparation; XLSX/CSV → spreadsheet table extraction; ZIP → safe extraction then type routing.

- [ ] **Step 6: Verify GP-008 provenance**

Assert the local supplement produces evidence for page 4, ratio `45:30:23.5:1.5`, and the registered supplement hash.

- [ ] **Step 7: Commit**

```bash
git add src/rag/current_corpus_assets.py src/rag/ingestion.py src/screening/retrieve_gold_oa_packages.py tests/test_current_corpus_assets.py
git commit -m "feat: close current-corpus supplement evidence"
```

---

### Task 10: Rebuild locally, deduplicate, and generate the true rerun queue

**Files:**
- Modify: `src/database/run_current_corpus_import.py`
- Create: `src/database/deduplicate_science.py`
- Create: `src/database/build_rerun_queue.py`
- Modify: `tests/test_current_corpus_import.py`
- Create: `tests/test_deduplicate_science.py`
- Create: `tests/test_build_rerun_queue.py`
- Create during execution: `reports/database/pre_rerun_local_closure.json`

**Interfaces:**
- Consumes: complete manifest, lossless adapters, identity functions, supplement inventory.
- Produces: temporary rebuilt database, deduplication report, and bounded post-local-closure rerun queue.

- [ ] **Step 1: Write failing rebuild and deduplication tests**

```python
def test_rebuild_is_source_complete_and_idempotent(tmp_path: Path) -> None:
    first = rebuild_database(tmp_path / "one.db", MANIFEST)
    second = rebuild_database(tmp_path / "two.db", MANIFEST)
    assert first.scientific_content_sha256 == second.scientific_content_sha256
    assert first.silent_fact_omissions == 0
    assert first.silent_evidence_omissions == 0


def test_deduplication_keeps_provenance_links(connection: sqlite3.Connection) -> None:
    seed_three_np002_component_occurrences(connection)
    result = deduplicate_science(connection)
    assert result.canonical_component_count == 1
    assert result.source_occurrence_count == 3
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_current_corpus_import.py tests/test_deduplicate_science.py tests/test_build_rerun_queue.py`

- [ ] **Step 3: Rebuild rather than append to the old scientific state**

Create a fresh temporary database, migrate it, import the 14 manifest dispositions, import every contributing artifact, then deduplicate normalized science. Preserve the old database only as the Task 1 backup.

- [ ] **Step 4: Calculate named and chemical formulation identities after import**

Create a stable report mapping every named formulation to its component rows, composition completeness, composition fingerprint, payload-bearing arms, and evidence. Do not calculate final formulation counts before this step.

- [ ] **Step 5: Build the rerun queue from remaining evidence-backed gaps**

The queue may include only the bounded paper scopes from the design. A missing database field does not justify a rerun when an unprojected local source fact already supplies it.

- [ ] **Step 6: Verify zero paid calls and write local-closure report**

The report must include per paper: source facts, canonical facts, evidence occurrences, canonical evidence, named formulations, unique composition fingerprints, arms, outcomes, unresolved items, and remaining rerun fields.

- [ ] **Step 7: Commit**

```bash
git add src/database/run_current_corpus_import.py src/database/deduplicate_science.py src/database/build_rerun_queue.py tests/test_current_corpus_import.py tests/test_deduplicate_science.py tests/test_build_rerun_queue.py reports/database/pre_rerun_local_closure.json
git commit -m "feat: rebuild and deduplicate current evidence"
```

---

### Task 11: Prepare and execute only approved selective reruns

**Files:**
- Create: `src/extraction/prepare_current_corpus_reruns.py`
- Create: `src/extraction/run_current_corpus_reruns.py`
- Create: `tests/test_prepare_current_corpus_reruns.py`
- Create during execution: `reports/database/current_corpus_rerun_preflight.json`
- Create during execution: versioned request/result directories under `data/staging/extraction/`

**Interfaces:**
- Consumes: post-local-closure rerun queue and existing extraction runners/contracts.
- Produces: immutable request bytes/hashes and, only after approval, validated contributing result artifacts.

- [ ] **Step 1: Write failing preflight-safety tests**

```python
def test_preflight_contains_only_post_local_closure_gaps() -> None:
    preflight = prepare_current_corpus_reruns(DATABASE, MANIFEST)
    assert "GP-008:composition" not in preflight.requested_fields
    assert set(preflight.paper_ids) <= {"GP-002", "GP-004", "GP-005", "GP-006", "GP-008", "NP-001", "NP-002", "PILOT-001", "PILOT-002", "PILOT-003"}


def test_runner_refuses_unapproved_request_hash() -> None:
    with pytest.raises(PermissionError, match="approved request hash"):
        run_current_corpus_reruns(PREFLIGHT, approved_hashes=set())
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_prepare_current_corpus_reruns.py`

- [ ] **Step 3: Generate zero-call preflight**

For each requested paper/field, record source scope, permitted candidate IDs, evidence envelope, exact request path/hash, model, token estimate, cost estimate, and expected merge target. Mark publisher/source blockers separately from paid requests.

- [ ] **Step 4: Stop for explicit human approval**

Present the preflight. Do not create invocation markers or clients before approval. Approval must identify the exact request hashes.

- [ ] **Step 5: Execute approved requests once**

Load `/Users/renemilywei/Desktop/AI-LNP/.env` only for the approved invocation. Verify the required credential before writing the invocation marker. A credential failure before provider dispatch consumes no authorization. Do not retry provider-dispatched requests silently.

- [ ] **Step 6: Validate every returned result**

Require schema validation, exact candidate accounting, evidence-envelope validation, source-artifact hashes, and zero unknown evidence IDs. Failed results remain artifacts with rejected status and do not overwrite accepted science.

- [ ] **Step 7: Add successful results to the existing manifest**

Append each validated rerun result under that paper's `contributing_artifacts` with its path, hash, role `repair` or `vision`, validation status, and import count.

- [ ] **Step 8: Verify and commit generated metadata/code**

Run: `.venv/bin/python -m pytest -q tests/test_prepare_current_corpus_reruns.py`

Commit source, tests, preflight, and safe validated artifacts according to repository data policy. Never commit credentials or unredacted provider material.

---

### Task 12: Merge reruns, adjudicate conflicts, and recalculate eligibility

**Files:**
- Create: `src/database/merge_current_corpus_reruns.py`
- Modify: `src/database/status.py`
- Modify: `src/ui/review_service.py`
- Create: `tests/test_merge_current_corpus_reruns.py`
- Modify: `tests/test_database_status.py`
- Modify: `tests/test_review_service.py`

**Interfaces:**
- Consumes: validated rerun contributors and the rebuilt local-closure database.
- Produces: merged source facts, explicit conflicts, updated normalized rows, review queue, and recalculated eligibility.

- [ ] **Step 1: Write failing safe-merge tests**

```python
def test_rerun_adds_supported_fact_without_erasing_prior_provenance() -> None:
    merge_current_corpus_reruns(connection, [SUPPORTED_REPAIR])
    assert canonical_value(connection, TARGET) == EXPECTED
    assert source_artifact_count(connection, TARGET) == 2


def test_conflicting_rerun_creates_review_item() -> None:
    merge_current_corpus_reruns(connection, [CONFLICTING_REPAIR])
    assert completeness(connection, ARM) == "conflict"
    assert review_reason(connection, ARM) == "content_conflict"
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_merge_current_corpus_reruns.py tests/test_database_status.py tests/test_review_service.py`

- [ ] **Step 3: Implement additive rerun merge**

Import rerun facts through the same source ledger. Deduplicate identical canonical science, retain all provenance, and create conflicts when supported values disagree. Never prefer a result only because it is newer.

- [ ] **Step 4: Review near-ready arms**

Prioritize arms blocked by one or two fields. Accept a correction only with value, evidence excerpt/structured evidence, source location, reviewer, and immutable revision history.

- [ ] **Step 5: Recalculate fixed-schema status and eligibility**

Run `evaluate_arm_status` and both eligibility profiles for every arm. Record the rules version and exact blocking reasons.

- [ ] **Step 6: Verify and commit**

Run: `.venv/bin/python -m pytest -q tests/test_merge_current_corpus_reruns.py tests/test_database_status.py tests/test_review_service.py`

```bash
git add src/database/merge_current_corpus_reruns.py src/database/status.py src/ui/review_service.py tests/test_merge_current_corpus_reruns.py tests/test_database_status.py tests/test_review_service.py
git commit -m "feat: merge reruns and recalculate eligibility"
```

---

### Task 13: Produce and verify the honest final report

**Files:**
- Modify: `src/database/audit_current_database.py`
- Create: `src/database/report_current_database.py`
- Modify: `tests/test_audit_current_database.py`
- Create: `tests/test_report_current_database.py`
- Create during execution: `reports/database/final_current_evidence_database.json`
- Create during execution: `reports/database/final_current_evidence_database.md`

**Interfaces:**
- Consumes: completed temporary database, complete manifest, source-fact audit, deduplication results, rerun history, eligibility results.
- Produces: machine-readable and human-readable final reports plus a promotion decision.

- [ ] **Step 1: Write failing report-contract tests**

```python
REQUIRED_COUNTS = {
    "papers", "named_formulations", "unique_chemical_formulations",
    "complete_formulations", "incomplete_formulations", "components",
    "source_fact_occurrences", "canonical_facts", "experimental_arms",
    "outcomes", "source_evidence_occurrences", "evidence_records",
    "nearest_neighbor_ready_arms", "comet_ready_arms",
    "unresolved_review_items",
}


def test_final_report_keeps_scientific_counts_separate() -> None:
    report = report_current_database(connection, MANIFEST)
    assert REQUIRED_COUNTS <= report["counts"].keys()
    assert report["definitions"]["named_formulations"] != report["definitions"]["unique_chemical_formulations"]
    assert report["checks"]["silent_fact_omissions"] == 0
    assert report["checks"]["silent_evidence_omissions"] == 0
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/test_audit_current_database.py tests/test_report_current_database.py`

- [ ] **Step 3: Extend the audit to source-to-SQLite coverage**

Require artifact hash matches, exact source-fact disposition equality, evidence-ID accounting, canonical uniqueness, formulation/component integrity, supplement locator resolution, no orphans, screening-only isolation, and eligibility consistency.

- [ ] **Step 4: Generate the separately defined counts**

Report totals and per-paper counts for:

- papers;
- named formulations;
- unique chemical formulations;
- complete and incomplete formulations;
- components;
- source fact occurrences and canonical facts;
- experimental arms;
- outcomes;
- source evidence occurrences and canonical evidence records;
- nearest-neighbor-ready arms;
- COMET-ready arms;
- unresolved review items.

Include definitions beside the counts and split eligibility by paper, cell, verification status, and blocking reason.

- [ ] **Step 5: Prove reproducibility**

Rebuild a second temporary database from the same manifest. Compare canonical table exports and report counts, excluding timestamps and internal integer row IDs. Both rebuilds must produce the same scientific content hash.

- [ ] **Step 6: Run full verification**

Run:

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=.venv-rag/lib/python3.14/site-packages .venv/bin/python -m pytest -q
sqlite3 TEMP_DB "PRAGMA integrity_check; PRAGMA foreign_key_check;"
```

Expected: all tests pass, integrity is `ok`, foreign-key check returns no rows, zero paid calls occur during verification, and both omission counts are zero.

- [ ] **Step 7: Promote the database atomically**

Only after every gate passes, use the database lifecycle helper to move the verified temporary database to `data/curated/lnp_evidence.db`. Record old/new hashes and the backup path. Never replace the authoritative database after a partial or failed run.

- [ ] **Step 8: Commit the audit/report code and final safe reports**

```bash
git add src/database/audit_current_database.py src/database/report_current_database.py tests/test_audit_current_database.py tests/test_report_current_database.py reports/database/final_current_evidence_database.json reports/database/final_current_evidence_database.md
git commit -m "docs: report final current evidence database"
```

---

## Execution estimate and stopping conditions

### Expected elapsed time

- Task 1: 30–45 minutes.
- Task 2: 45–75 minutes.
- Tasks 3–5: 2–3 hours.
- Tasks 6–8: 1.5–2.5 hours.
- Tasks 9–10: 1–1.5 hours.
- Task 11: 1.5–3 hours after immediate approval; longer if providers or publisher access block.
- Tasks 12–13: 1–1.5 hours plus any necessary human adjudication.

Expected total: **7–11 elapsed hours**. Best case: **6–7 hours** when local evidence closes most gaps and few reruns remain. Access blocks, delayed paid-call approval, provider latency, or substantive human conflicts extend the schedule. Beginning afternoon screening on the same day is therefore conditional, not guaranteed.

### Completion gate

This plan is complete only when:

- the final authoritative SQLite file has a recorded hash;
- every approved source fact and evidence ID is accounted for;
- normalized duplicate facts/evidence/components are removed while provenance is retained;
- all approved reruns have been imported or are explicitly reported as blocked/rejected;
- eligibility has been recalculated from versioned rules;
- the honest final report contains every separately defined count requested above;
- new-paper screening has not started as part of this work.
