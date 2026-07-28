# Day 5 afternoon - compact route cost gate

**Gate G1: HOLD**

| Metric | Prior full-text route | Compact route | Change |
|---|---:|---:|---:|
| Input tokens | 341,203 | 180,780* | 47.0% lower |
| Output tokens | 163,998 | 26,108* | 84.1% lower |
| Calls | 20 | 10 | 50.0% lower |
| Vision pages | 0 | 1 | +1 targeted page |
| Cost | $4.6248 | >=$0.7828* | >=83.1% lower |
| Cost/paper | $0.5139 | >=$0.0870* | - |
| Accepted outcome proxy | 46 | 25 | Schema differs |
| Cost/accepted outcome | $0.1005 | >=$0.0313* | - |
| Mean latency | Not recorded | 19.8s main call | Not comparable |

*Compact token, cost, and latency totals exclude one GP-006 crop pilot whose manifest was not preserved; the call and page are counted.

## Frozen-gold regression inspection

- Prior route: 6/15 (40.0%).
- Compact after local adjudication: 7/15 (46.7%).
- Regressions: GO-015, GO-016.
- Gains: GO-004, GO-011, GO-013.

The two regressions were traced to evidence-budget ranking and are retained in API packet v1.1. They still require one small repair and merge.

## G1 criteria

- **HOLD** - Evidence quality must not materially regress: Frozen-gold outcome recall improved from 6/15 (40.0%) to 7/15 (46.7%), but two baseline-recovered GP-008 outcomes regressed and semantic critical-field precision, experiment mixing, and unsupported claims remain pending.
- **PASS** - All nine papers complete or explicitly unresolved: Eight papers have final merged results; GP-002 has an explicit legacy-contract unresolved disposition and a saved extraction result.
- **PASS** - Routine text papers use one main plus <=1 small repair: Every paper used one main call. GP-006 used one selective-vision crop call; no paper exceeded one exception call.
- **PASS_WITH_METERING_CAVEAT** - Cost materially lower than current route: Measured main-call cost fell from $4.6248 to $0.7828, an 83.1% reduction. The unmetered pilot would need to cost more than $3.8420 to erase the savings.

Overall: **HOLD**. Cost, completion disposition, and call discipline pass, but the quality criterion is not yet fully established and two known GP-008 regressions require one targeted repair.
