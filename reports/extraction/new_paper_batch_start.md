# New-paper batch start — 2026-08-07

The first real post-repair batch has started. Discovery, database deduplication, abstract screening, full-text retrieval, selective supplement recovery, source parsing, and immutable extraction preflight have all run. No model request has been dispatched.

## Honest counts

| Stage | Count |
|---|---:|
| Search-source records | 433 |
| Unique discovered papers | 222 |
| Papers already represented in SQLite | 11 |
| Novel papers | 211 |
| Novel papers abstract-screened | 211 |
| Abstract-level includes | 89 |
| Abstract-level exclusions | 19 |
| Abstract-level manual review | 103 |
| Papers queued for the first full-text batch | 12 |
| Full texts successfully retrieved and parsed | 9 |
| Main-article source blocks | 440 |
| Supplements explicitly declared by article XML | 4 |
| Declared supplements downloaded | 2 |
| Supplement source blocks | 28 |
| Immutable extraction requests prepared | 9 |
| Provider calls made | 0 |
| Papers currently proven to contain an evidence-backed arm | 0 |
| New arms extracted and imported | 0 |

The 89 includes are screening decisions from title/abstract evidence. They are not claims that 89 papers already contain complete usable database rows. That number becomes knowable only after full-text extraction and validation.

Two declared supplements were downloaded and parsed. Two files declared by `candidate_00006` remain unavailable because the provider's supplementary archive endpoint returned HTTP 404; the article XML and this failure are retained in the retrieval manifest.

Nine exact `gpt-5.6-terra` requests are frozen in `data/staging/new_papers/2026-08-07/extraction/requests/`. Their combined estimated input is 173,156 tokens and their combined maximum output allowance is 108,000 tokens. Every hash must be explicitly approved before any paid call is made; the hashes are recorded in `new_paper_batch_start.json` and the extraction preflight report.
