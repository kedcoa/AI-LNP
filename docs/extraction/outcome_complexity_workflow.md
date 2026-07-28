# Complexity-aware compact outcome validation

Complexity is assessed locally from the compact API packet before the first
LLM call. The assessment never changes or enlarges the first-call prompt.

## Ordinary path

Simple packet -> first LLM call -> compact schema/evidence validation -> field
repair only for deterministic invalid fields -> merge -> final validation.

## Complex path

Complex packet -> build and save local outcome candidates -> unchanged first
LLM call -> ordinary compact validation -> compare the saved candidate groups
with extracted outcomes -> review unmatched groups.

Candidate confidence is calibrated in two tiers:

- high-confidence, non-duplicate unmatched groups block merging and enter the
  exception-review queue;
- medium-confidence and overlapping duplicate groups remain visible in
  `review_candidates`, but cannot block merging or trigger a paid call.

An actionable unmatched group is still not automatically a paid task. It must
first be closed as already covered, background, methods-only, or out of scope,
or confirmed as one of:

- text-supported missing outcome -> narrow text recovery;
- figure/table-supported missing outcome -> selective vision;
- ambiguous or visually estimated outcome -> human review.

Validated exception results are merged with the first result and the complete
paper is validated again before `final_result.json` is written.

The complexity screen is deliberately cheap: it counts outcome-tagged
passages, endpoint families, intervention context, quantitative result
signals, and visual locations. It does not invoke
`build_outcome_candidates.py`. The detailed builder runs only for packets
classified as complex, and its saved candidates are reused after the first
LLM call.

The calibrated rules prefer a false-complex classification over a
false-simple classification. False-complex adds only local work;
false-simple can allow a silent omission. No coverage category automatically
makes a paid API request.
