# Application pilot Gate A preflight

Status: prepared locally; explicit human approval required before execution.

This package freezes exactly three paper-map requests. Preparation performed no
provider calls and did not load credentials.

| Request | Paper | Model | Request SHA-256 | Estimated input tokens | Maximum output tokens | Maximum estimated tokens |
|---|---|---|---|---:|---:|---:|
| REQ-1 | PILOT-001 | `gpt-5.6-terra` | `cb6785db11d51c303df18a5fe10fc94d65dc8011bc9f76a24497bde896b8dd3b` | 21,774 | 12,000 | 33,774 |
| REQ-2 | PILOT-002 | `gpt-5.6-terra` | `634ce959babb85c176d3b9bf4a28605cd4657c21acceaf01ed12e77d8c328010` | 21,070 | 12,000 | 33,070 |
| REQ-3 | PILOT-003 | `gpt-5.6-terra` | `8aae537495e7a0660e348fa930487d99623be93c89e2d339c05e4b22eea1c092` | 20,368 | 12,000 | 32,368 |

Totals:

- Calls: **3**
- Estimated input tokens: **63,212**
- Maximum output tokens: **36,000**
- Maximum estimated tokens: **99,212**
- Provider calls during preparation: **0**
- Retries authorized: **0**
- Approval hash: `9dbfbcb83e6f8f07c9ce7701eb09adde0db8a352229a77ed1c11358bf75812ea`

## Immutable source bindings

| Paper | Inventory SHA-256 |
|---|---|
| PILOT-001 | `766a73a0b3a3826e90440d489b577cdac3f29020965bc50548a8d16ec1da1690` |
| PILOT-002 | `37f67b111abfb978b9291fc67fad430f613f94995cfaad3f95de77794c270e5d` |
| PILOT-003 | `a32678f5b3c5cb7cef2bcb35541de70013962e74c8e6c857863cc16bb06f2e77` |

The request-byte hashes and inventory bindings were re-read and verified after
serialization. A current price for the configured internal model was not
available in the local configuration, so no monetary estimate is asserted.

No Gate-A request may run unless the human explicitly approves the approval
hash above. Any change to a request or bound inventory invalidates that
approval.
