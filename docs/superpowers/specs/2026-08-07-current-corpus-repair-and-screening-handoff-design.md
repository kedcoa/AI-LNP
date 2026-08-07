# Current-Corpus Repair and Screening Handoff Design

**Date:** 2026-08-07

**Status:** Approved through the user’s database, review, and table-design decisions

**Goal:** Finish the current evidence database correctly, give the user one practical interface for seeing all evidence-backed experimental arms and filling only near-COMET gaps, and prove that the same pipeline can immediately ingest newly screened papers.

## 1. What is already kept

The existing lossless source-fact ledger, current-corpus manifest, normalized SQLite tables, deduplication logic, evidence browser, and authoritative database are retained. This work does not create another manifest, another database architecture, or another incompatible import path.

The original JSON files remain the immutable inputs. SQLite stores their paths, hashes, fact occurrences, evidence, projections, and rejection or quarantine reasons. A rebuild fails if a source fact or evidence identifier silently disappears.

## 2. Repair the JSON-to-SQLite arm projection

The GP graph adapter must create one canonical experimental arm for every explicit graph experiment that has an evidence-supported formulation relationship. It must carry linked formulation, biological model, cell or tissue, payload, dose, route, assay, timepoint, comparator, and outcome facts into that arm. A paper-wide fact may be copied to several arms only when the graph or source marks it as study-wide.

An unclear relationship is not a reason to drop the experiment. The record stays in the source ledger and is classified as one of:

- automatically resolved by an explicit graph edge or unique evidence-supported candidate;
- incomplete because the source did not report a required field;
- quarantined because two or more relationships remain scientifically plausible;
- rejected because the source record is invalid or outside scope.

Tests compare the explicit graph experiment identities with the SQLite arm identities paper by paper. The comparison explains every difference instead of relying only on total counts.

## 3. Recover missing source material selectively

The supplement pipeline is corpus-wide and is also used for new papers. It works local-first:

1. search registered local source and supplement paths;
2. parse JATS/XML and downloaded HTML for `supplementary-material`, related-object, data, protocol, and patent citations;
3. classify only scientifically relevant links by element type, label, filename, citation context, and safe file type;
4. download only those declared assets when they are not already local;
5. hash, register, and parse each asset;
6. send extracted blocks through the same evidence and fact pipeline.

The system does not download every web link. JavaScript browser fallback is used only when the static source declares a relevant item but hides its final lawful URL. Patent evidence is marked as indirect evidence and never silently treated as proof that a paper used every formulation described by that patent.

## 4. Status and review meaning

`paper.import_status` is not shown as a blanket human-review instruction. Application status is recalculated from current SQLite relationships and evidence.

Three independent answers are shown for each arm:

- **General use:** the arm contains at least one evidence-backed scientific fact and is not invalid.
- **Nearest-neighbor ready:** the current deterministic nearest-neighbor rules pass.
- **COMET ready:** the stricter COMET rules pass, including its final evidence-verification requirement.

`experiment_link_unclear` and similar labels mean the automatic mapper could not prove which formulation, model, or outcome belongs to which experiment. The user does not need to resolve these for general browsing. They block only the downstream use that needs the uncertain relationship.

Every non-COMET arm is listed in the COMET gap view, sorted by number of blockers. An arm with one to three blockers, no conflict or quarantine, and at least one supported outcome is labeled **almost COMET ready**. This is a queue label, not a scientific claim.

## 5. Approved combined main table

The main page uses **Option A**: show every evidence-backed arm, including incomplete arms. It has one row per experimental arm. Multiple normalized outcomes remain separate in SQLite but are stacked into one display cell.

The visible order begins with:

1. paper ID and title;
2. DOI, PubMed, and PMC links;
3. arm ID;
4. `lnp_name`;
5. `chemical_formulation_total`;
6. `lnp_molar_ratio`;
7. `ionizable_lipid`;
8. `helper_lipid`;
9. `cholesterol`;
10. `peg_lipid`;
11. `others`;
12. cell or tissue, species, biological model, experimental setting;
13. payload type, payload name, encoded product, and molecular target;
14. dose, route, timepoint, assay, and comparator;
15. stacked outcomes;
16. general, nearest-neighbor, and COMET readiness;
17. missing fields and automatic-resolution blockers.

Missing values display as `NA`; `NA` is never written as a scientific value. Filters select paper, cell type, readiness profile, and blocker type without hiding incomplete-but-useful rows by default.

## 6. Compact COMET correction interface

The correction page shows the arms closest to COMET readiness first. For each arm it shows paper links, current values, missing field names, and existing evidence. The edit form is at the top and contains only:

- missing field;
- updated value;
- evidence excerpt;
- evidence location such as section, page, table, or figure;
- optional note;
- save.

A saved correction is append-only. It records the previous value, corrected value, excerpt, location, reviewer, timestamp, and superseded revision when applicable. The same transaction updates evidence links, resolves the matching missing-field record, recalculates arm status and both eligibility profiles, and performs consistency checks. A correction without an excerpt and location cannot be accepted.

This manual interface is a bounded COMET quality-control tool. It is not required for ordinary general-use records and does not replace automatic extraction for new papers.

## 7. Rebuild, reruns, and final database

The database is rebuilt from the manifest and all registered local artifacts before any rerun decision. Deduplication occurs only after all source occurrences are imported. The post-rebuild audit produces the actual missing-source, missing-extraction, mapping, conflict, and not-reported categories.

Only papers with a remaining extraction or source gap enter the rerun queue. Each request is bounded to named fields and source locations. Existing pilot responses are merged without rerunning them. Paid requests require exact hashes and separate explicit approval; there are no silent retries.

The authoritative database is replaced only after integrity, foreign-key, losslessness, orphan, duplicate, provenance, eligibility, and reproducibility checks pass. The old database is backed up and hashed first.

## 8. Honest final report

The final report gives separate definitions and counts for:

- papers;
- named formulations;
- unique chemical formulations;
- complete and incomplete formulations;
- components;
- source fact occurrences;
- deduplicated canonical facts;
- experimental arms;
- outcomes;
- source evidence occurrences;
- deduplicated evidence records;
- nearest-neighbor-ready arms;
- COMET-ready arms;
- almost-COMET-ready arms;
- unresolved automatic-resolution items;
- remaining true human-adjudication items;
- rerun papers and completed reruns.

Counts are generated from the final database, not copied from an old report or manifest status.

## 9. New-paper screening handoff

The current-corpus work is not complete until a clean new-paper fixture can travel through discovery metadata, screening, full-text retrieval, selective supplement discovery, extraction, lossless import, arm projection, eligibility evaluation, and appearance in the combined table without special paper-ID code.

After that smoke test passes, the real screening workflow may begin. New papers use the same manifest entry shape, asset resolver, adapters, ledger, normalized tables, and UI. The first real new-paper batch is a follow-on run, not another database redesign.

## 10. Safety and scope

- Do not use CodeRabbit CLI or the CodeRabbit review workflow.
- Do not download every hyperlink on a publisher page.
- Do not fabricate proprietary compositions from a cited patent.
- Do not require human verification for general application use.
- Do not drop unclear facts or experiments.
- Do not overwrite original JSON or prior review history.
- Do not perform paid calls without explicit approval.

## 11. Time expectation

Because the ledger, rebuild, browser, and much of the supplement support already exist, the remaining repair and interface work is estimated at **4–6 hours** if local tests pass and source access is normal. A first real new-paper screening/extraction batch needs another **2–4 hours**, depending on paper access and approved model calls. Starting new-paper screening by EOD is realistic only if the repair gates finish in the lower half of the estimate and external access or paid-call approval does not stall.
