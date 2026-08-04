# Codex auditor benchmark decision

Run: `2026-08-04-codex-audit-e2e-v4`

Decision: **promising_but_inconclusive**. The retained audit shows 1 supported automated recovery, but it does not meet the approved success threshold; the production OpenAI v5.2 route remains unchanged.

The canonical bound scorer reproduces 40/62 for both the untouched cached extraction and clean replay, then scores the strictly validated audited copy at 41/62. Complete arms are 2/7 before and 2/7 after. Evidence-level inventory moves from 57 full / 3 partial / 2 absent to 58 / 2 / 2.

Strict validation accepted 46 of 88 proposals and rejected 42. Exact rejection-reason counts are recorded in `audit_summary.json` and proposal-level decisions in `proposal_ledger.json`. The 9 proposals rejected solely for literal raw-value mismatch are conservatively classified as `posthoc_raw_value_mismatch`; literal mismatch is not counted as a hard safety failure or proof of unsupported science.

All 28 issued packets were terminal before hidden gold was loaded. Model telemetry is unavailable: selector `hosted-default`, CLI `codex-cli-0.146.0-alpha.3.1`; Codex JSONL did not report the resolved model. Retained usage was 559,386 input, 23,444 output, and 60,160 cached-input tokens across 28 attempts, with 702.690 aggregate seconds. No new provider or model calls were made by this finalizer.
