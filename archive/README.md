# Archive

This directory contains superseded plans, reports, code generations, tests, and
reproducibility artifacts that are not part of the current compact workflow.

Archived files are preserved rather than deleted so historical decisions and
benchmarks remain inspectable through Git.

## Active workflow

Use these files instead of archived instructions:

```text
README.md
docs/extraction/corrected_compact_workflow.md
docs/extraction/outcome_complexity_workflow.md
```

## Day 8 compatibility exception

The legacy files below remain in their original source locations because the
existing Day 8 vision system imports them:

```text
src/extraction/contracts.py
src/extraction/run_abstract_first.py
```

They must not be removed or moved until Day 8 shared constants and types are
decoupled. The Day 8 vision system itself was not archived or modified.

