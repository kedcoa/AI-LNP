# Repository Guidelines

## Project Structure & Module Organization

- `src/rag/`: PDF/XML ingestion, retrieval, compact evidence packets, and provenance.
- `src/extraction/`: structured LLM contracts, validation, repair routing, deterministic merging, and evaluation.
- `src/screening/` and `src/search/`: literature discovery, metadata, and screening.
- `tests/`: pytest tests named `test_*.py`; reusable benchmark inputs live under `tests/fixtures/`.
- `config/`: versioned workflow configuration.
- `docs/`: architecture, schemas, screening rules, and workflow specifications.
- `data/` and `reports/`: evidence artifacts and evaluation outputs. Large or licensed source files may be intentionally ignored.

## Build, Test, and Development Commands

Create the RAG environment and install dependencies:

```bash
python3 -m venv .venv-rag
.venv-rag/bin/pip install -r requirements-rag.txt
```

Run the complete test suite:

```bash
.venv/bin/python -m pytest -q
```

Run a focused test while developing:

```bash
.venv/bin/python -m pytest -q tests/test_compact_contracts.py
```

Run ingestion and the local RAG pipeline with:

```bash
.venv-rag/bin/python -m src.rag.ingestion
.venv-rag/bin/python -m src.rag.run_pipeline
```

## Coding Style & Naming Conventions

Use four-space indentation, type hints, `snake_case` for functions and modules, and `PascalCase` for Pydantic models. Keep functions focused and preserve explicit paper, experiment, evidence-ID, and provenance links. Follow existing formatting; no repository-wide formatter is currently configured.

## Testing Guidelines

Use pytest and add regression tests before changing extraction, validation, or merge behavior. Name tests by expected behavior, for example `test_validator_rejects_unknown_evidence_id`. Test both successful extraction and abstention/failure paths. Paid API calls are not unit tests; use fixtures or fake clients unless a separately approved benchmark call is required.

## Commit & Pull Request Guidelines

Prefer short imperative Conventional Commit-style subjects, such as `fix: validate outcome links` or `docs: clarify compact workflow`. Keep commits scoped. Pull requests should explain the scientific/workflow impact, list verification commands, identify changed schemas or artifacts, and link the relevant issue or design document. Include screenshots only for visual review or UI changes.

## Security & Configuration

Never commit `.env`, API keys, credentials, licensed PDFs, or unredacted provider responses. Paid calls require explicit human approval and must not retry silently.

Worktrees do not contain their own `.env`. Before an approved API call, load the main repository file explicitly:

```bash
source /Users/renemilywei/Desktop/AI-LNP/.env
```

Verify the required credential is available before writing an invocation marker or creating the API client. A credential failure before provider dispatch consumes no paid-call authorization; retry the identical approved request from a fresh run directory.
