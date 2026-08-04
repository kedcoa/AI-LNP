# Codex auditor benchmark decision

Run: `2026-08-04-codex-audit-e2e-v4`

Decision: **does_not_work**. Retain the existing OpenAI v5.2 extraction route and do not generalize automatic Codex auditing from this benchmark.

The gold-blind run issued all 28 sealed packets with concurrency two. All packets reached terminal accounting: 27 schema-valid responses and one schema failure, with no retries or unattempted packets. Deterministic validation accepted 55 of 88 proposals and rejected 33. Rejection reasons were unsupported exact number (23), quote mismatch (5), cross-experiment evidence (5), and wrong arm link (5); reasons can overlap on a rejected proposal.

The authoritative baseline remained 40/62 automated full requirements and 57 full / 3 partial / 2 absent evidence-level requirements. The audited copies remained 40/62 and 57 / 3 / 2, with 0 recovered partial-or-absent requirements, 0 recovered absences, 0 deterministic undercounts recovered, and 2/7 complete arms before and after. The current scorer independently produced 18/62 for both clean replay and audited copies, a zero delta; it also produces 18/62 for the untouched cached extraction despite the authoritative saved score of 40/62. The decision therefore applies the measured zero delta to the canonical baseline and records scorer drift as a concern.

Safety findings were zero for gold leakage, accepted unsupported/invented facts, accepted wrong relationships, consecutive systemic failures, paid extraction API requests, production writes, and Ollama calls. One unused-evidence packet failed local response semantics because it returned proposal disposition without proposals.

Measured hosted usage was 559,386 input tokens, 23,444 output tokens, and 60,160 cached input tokens across 28 attempts. Aggregate packet latency was 702.690 seconds (25.096-second mean). Codex JSONL did not report the resolved model; the runner selection was `hosted-default`, so the actual model is unmeasured rather than guessed.

Provider-disabled verification:

```text
OPENAI_API_KEY= SENSENOVA_API_KEY= PYTHONPATH=/Users/renemilywei/Desktop/AI-LNP/.venv-rag/lib/python3.14/site-packages /Users/renemilywei/Desktop/AI-LNP/.venv/bin/python -m pytest -q
821 passed, 5 warnings in 7.15s
```

Artifacts: `audit_summary.json`, `evaluation.json`, `audited_copies/`, `audit-codex/audit_packets/gold_isolation.json`, and `failure_analysis.md` in this run directory. Raw JSONL, final messages, stderr, and provider results remain append-only under `audit-codex/` and are intentionally excluded from version control.
