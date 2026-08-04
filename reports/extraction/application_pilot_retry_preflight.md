# Application pilot five-call retry preflight

## Why this package exists

The first Gate-B execution produced 12 valid context responses. The three
selective-vision requests failed before inference with provider HTTP 400
because the strict schema's `experiment_id` property had `const` but no
`type`. Two additional context responses (original REQ-15 and REQ-16) returned
provider status `incomplete` with reason `max_output_tokens`; their truncated
`output_text` is not valid JSON. Those five outputs are unusable.

The other 12 context calls are not included and must not be rerun. Their saved
responses remain unchanged. The runner now records any non-`completed`
provider response as failed while preserving its raw response artifact.
The original Gate-B manifest cannot be rerun: it contains all 17 requests,
including the 12 valid context calls and the five now-isolated unusable calls.

## Approval boundary

No provider call was made while preparing this package. It contains exactly
five one-shot calls on `gpt-5.6-terra`, with zero automatic retries and zero
repair calls.

Approval hash:

`a4af835baff13e904700a829bb17893cd5c2015931efda31c7fab4e68d66012c`

| Retry ID | Paper | Kind | Replaces | Input estimate | Output cap | Request SHA-256 |
|---|---|---|---|---:|---:|---|
| REQ-1 | PILOT-001 | selective vision | old REQ-6 | 59,344 | 2,000 | `a96b9accd970d3d912492d523159ca2a9a3155f3599e9e3276089d4a897514cc` |
| REQ-2 | PILOT-002 | selective vision | old REQ-12 | 27,166 | 2,000 | `606506373f5fcb0c301b35602ac9dd6f89fe520e524c0e34f3ec6ccb864f21fb` |
| REQ-3 | PILOT-003 | context | old REQ-15 / CTX-3 | 8,214 | 8,000 | `ce3333ebeebf742bd423dc59614ba11b229bf1b02aaf684ce471f9822a03c622` |
| REQ-4 | PILOT-003 | context | old REQ-16 / CTX-4 | 8,472 | 8,000 | `648fc9db968b228512703de02cdef888302340f0f980b9413ca64b81867ac332` |
| REQ-5 | PILOT-003 | selective vision | old REQ-17 | 44,429 | 2,000 | `cd83c5708f29d0ae05d71eafcdda88b53490f0f36dadaf5299ab46bc7cfefe22` |
| **Total** |  | **3 vision + 2 context** |  | **147,625** | **22,000** |  |

Maximum estimated total: **169,625 tokens**. Vision estimates conservatively
count encoded image request bytes. The 8,000-token context cap is the smallest
bounded retry cap selected: both prior calls consumed the full 5,000-token cap
and ended mid-JSON, while 8,000 provides headroom without restoring the former
12,000 cap. Each context request is byte-equivalent to its original request
after removing only `max_output_tokens` (5,000 → 8,000).

## Corrected safeguards

- Experiment-bound vision schema properties now contain both
  `type: "string"` and their exact issued-ID `const`.
- The complete schema passes Draft 2020-12 validation.
- JPEG assets retain verified JPEG data URLs and original task/crop hashes.
- The retry manifest remains bound to the same validated maps, inventories,
  vision tasks, and image assets.
- The runner preserves raw incomplete responses but classifies them as failed,
  preventing truncated output from being merged or scored.
- Provider calls during retry preparation: **0**.
