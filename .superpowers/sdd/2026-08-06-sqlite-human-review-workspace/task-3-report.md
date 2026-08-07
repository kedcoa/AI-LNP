# Task 3 report

## Delivered

- Added `src/ui/review_app.py`, a Streamlit workspace that imports only review-service DTOs and functions; it contains no direct SQLite calls.
- Added static UI-contract coverage in `tests/test_review_app.py` for dashboard counts, paper inventory row counts, queue filters, paper links, arm fields, evidence selection, six decisions, reviewer/note fields, history, disabled submissions, and post-save eligibility.
- Kept write preparation opt-in. The app starts read-only and enables submission only after a verified backup readiness result plus reviewer/note and decision-specific evidence/value requirements.

## TDD evidence

- RED: `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_app.py` failed because `src/ui/review_app.py` did not exist (3 failures).
- GREEN: focused test now passes.

## Verification

- `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_service.py tests/test_review_app.py` — 26 passed.
- Streamlit `AppTest` rendered `src/ui/review_app.py` with 0 exceptions against the authoritative read-only path; no write control was clicked.

## Concern

- The worktree has no `.venv`; verification used the parent checkout interpreter above. The requested relative command cannot run from this worktree without an environment link.

## External review fix round 1

- Review backup preparation now obtains an absolute, external destination from `review_backup_directory()` in the service (configured by `AI_LNP_REVIEW_BACKUP_DIR`), never a repository-relative UI path.
- The queue now filters target cell, species, payload, and either nearest-neighbor or COMET proximity; the arm DTO includes both profile blocker sets.
- `ArmWorkspace` now includes deterministic outcome rows, and the UI renders them beside the selected arm.
- The eligibility result displays blockers for both profiles after a save; selected-field history is collapsed in an expander.
- `paper_access_links()` supplies persisted metadata links plus configured local full text and institutional-library links when present, without UI discovery or network access.
- A fixture-backed Streamlit `AppTest` verifies that external backup readiness succeeds and that submit remains disabled before required reviewer input/evidence.

Verification: `/Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q tests/test_review_app.py tests/test_review_service.py` — 28 passed.
