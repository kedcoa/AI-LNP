# Application pilot Gate-B preflight

## Approval boundary

No downstream provider call has been made. The frozen Gate-B manifest contains
17 one-shot requests using `gpt-5.6-terra`: 14 context calls and 3 selective-
vision calls. Automatic retries and unapproved repairs remain forbidden.

Approval hash:

`7c5203847b9066bc1cd01ad9e0d2f5bac4bd70d78e614da052f4e216489d99a4`

Conservative manifest estimate: 238,152 input tokens, 76,000 maximum output
tokens, 314,152 maximum total tokens. The vision input estimates count the
base64 image bytes as text and therefore are intentionally conservative; the
manifest nevertheless freezes and hashes those exact request bytes.

| Paper | Context | Vision | Estimated input | Output cap | Total cap |
|---|---:|---:|---:|---:|---:|
| PILOT-001 | 5 | 1 | 101,646 | 27,000 | 128,646 |
| PILOT-002 | 5 | 1 | 61,649 | 27,000 | 88,649 |
| PILOT-003 | 4 | 1 | 74,857 | 22,000 | 96,857 |
| **Total** | **14** | **3** | **238,152** | **76,000** | **314,152** |

## Gate-A validation and scientific audit

All three responses validated as strict `PaperMapResponse` objects against
their byte-bound inventories. All 136 locally issued anchors were accounted
for with known evidence IDs. Gate A used 70,587 input tokens and 24,425 output
tokens (95,012 total) across three successful calls, with zero retries.

The maps proposed 15 contexts. Fourteen were retained. PILOT-003 `CTX-5` was
quarantined because its source describes a Lipofectamine screen of 12 siRNA
sequences, while the map incorrectly bound it to the KL-52 LNP formulation and
the selected set-3 payload. Its anchor links were removed or changed to
`not_supported`; the paid raw response was preserved unchanged.

PILOT-001 `PEC-3` and some PILOT-002 contexts are group-level assays rather
than fully separated formulation-by-recipient arms. Their dose, route, model,
and payload evidence is direct, so they remain eligible, while the downstream
atomic-outcome contract must keep cell-specific comparisons separate. No
unsupported dose, formulation, route, or disease-model binding was otherwise
accepted.

## Minimal selective vision

Only one required biological-outcome figure is sent per paper. Tasks carry a
locally issued experiment ID and candidate ID; the response schema requires
the model to echo both unchanged, and Gate-B preparation rejects an unissued
pair. The tasks ask only for explicit qualitative comparisons and prohibit
exact numbers inferred from graph geometry.

| Paper | Figure | Issued experiment | Candidate | Reason |
|---|---|---|---|---|
| PILOT-001 | Figure 6 | `EXP-93e0b4253c54573c62f4` | `PEC-5` | Anti-fibrotic therapeutic outcome |
| PILOT-002 | Figure 7 | `EXP-a8e8cc49767357ec88c1` | `CTX::MANNOSE_MCRE_LSEC` | Cell-type-selective mCre/LSEC outcome |
| PILOT-003 | Figure 5 | `EXP-08f3a95e39cbce8ef2fb` | `CTX-4` | Advanced liver-disease/tumor outcome |

The public PMC asset manifest is SHA-256
`d729456535444e45ca576f4bfc95b30cb79b3057af53137991502bc0b3eaf0a0`.
All selected assets passed JPEG magic, dimension, and SHA checks. PILOT-002's
Figure 7 is natively only 440 pixels wide, so fine printed details may be
unresolved; the model must abstain rather than invent them.

## Exact requests

| ID | Paper | Kind | Input | Output cap | Request SHA-256 |
|---|---|---|---:|---:|---|
| REQ-1 | PILOT-001 | context | 8,700 | 5,000 | `198b2c35120446dfd0dc349d6362927f9277a7fea885f95d116fce474e2e9619` |
| REQ-2 | PILOT-001 | context | 8,360 | 5,000 | `d17de7a321129f79aa3b2b5049c5a3470d335ce89948004840f476c53abedcf4` |
| REQ-3 | PILOT-001 | context | 7,712 | 5,000 | `202806e5c5031534ade415d0b681777d0f9e093fed366fdf789047c725e43293` |
| REQ-4 | PILOT-001 | context | 8,157 | 5,000 | `38a9b3f3baad52c8aef7b8c01bf29ad7e78bc735498c0965f29391d5fd44d2a6` |
| REQ-5 | PILOT-001 | context | 9,381 | 5,000 | `b3340e98162095ded22788c5e3602dd7e5b82c3b80485c0accaf4374a1f239b9` |
| REQ-6 | PILOT-001 | selective vision | 59,336 | 2,000 | `4fd59a5d917fb7ec25af5d7003aadb9b7f1b957ca4ccf11470de47acd9b2e0f0` |
| REQ-7 | PILOT-002 | context | 6,859 | 5,000 | `177adf4ce62e411c395d59df0a34403efecd1420c7d061b613b816926b344c38` |
| REQ-8 | PILOT-002 | context | 6,614 | 5,000 | `a655ab96ba1b56308ab204084a27bcf39a4a0099edfe73729497dc9e7ea91a08` |
| REQ-9 | PILOT-002 | context | 6,049 | 5,000 | `231a458093bb4a9eac0e57eb629f920c591edda71109413910f68665029100ca` |
| REQ-10 | PILOT-002 | context | 7,892 | 5,000 | `76e6f8342d3c64b20998fe29c24c594ff734bcfac7af51e5712e6b8f02a147b6` |
| REQ-11 | PILOT-002 | context | 7,078 | 5,000 | `f95a183b2eb31949b19861eeb15a5a51627f9a1745dacc1da4a0a070e9c8d0e7` |
| REQ-12 | PILOT-002 | selective vision | 27,157 | 2,000 | `10737b2a9ce77755701026c35b1fb434161152db336bd0174321f8482a0dfe2a` |
| REQ-13 | PILOT-003 | context | 6,709 | 5,000 | `3c29b19bd801c095b0077b0319d519fe9e1220554a08e72d05787df1152f2f28` |
| REQ-14 | PILOT-003 | context | 7,041 | 5,000 | `441cb5bfca8125d4d8e76d99a7aef15ce76bf53a11abff57edad584f01b9795c` |
| REQ-15 | PILOT-003 | context | 8,214 | 5,000 | `f644bb5f2876e7e90ffde6bcb8a9388bc757d8d9d9f0968a8d66a19a7cbdfcbd` |
| REQ-16 | PILOT-003 | context | 8,472 | 5,000 | `61e7ba16e6e663a5dcc6f56c5c9c065deab35cba04f6f006c32f8de2d007080c` |
| REQ-17 | PILOT-003 | selective vision | 44,421 | 2,000 | `cdbef9045813449e0520b8bc0ef4b175e0f92deb6133145b25bd9cab18b87fe0` |

## Verification

- Manifest and all 17 request/source hashes reloaded successfully with no
  provider client construction.
- Focused offline suites: 94 passed, 5 pre-existing SWIG deprecation warnings.
- Provider calls during validation/preparation: 0.

