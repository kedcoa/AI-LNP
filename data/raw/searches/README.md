# Raw literature-search responses

This directory contains immutable responses returned by PubMed and Europe PMC.

Rules:

1. Never manually edit a raw response.
2. Never overwrite an earlier search run.
3. Each run must contain a snapshot of the query manifest.
4. Each response must have provenance metadata and a SHA-256 checksum.
5. Parsing and normalization must write to `data/staging`, not `data/raw`.
6. PubMed and Europe PMC are discovery sources.
7. PMC/open full text is a later retrieval mechanism, not a third discovery
   source.
8. API keys must never appear in raw files, metadata, logs, or saved URLs.