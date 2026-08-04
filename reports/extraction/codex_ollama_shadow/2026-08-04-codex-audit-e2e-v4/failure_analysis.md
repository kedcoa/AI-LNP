# Failure analysis: three-paper Codex auditor

The benchmark does not support generalizing the Codex auditor. Although deterministic packet-local validation accepted 55 evidence-grounded proposals, none recovered a hidden automated requirement or improved the evidence-level 57 full / 3 partial / 2 absent inventory. Coverage remained 40/62 and complete arms remained 2/7.

The dominant rejected class was unsupported exact numbers (23 reasons), followed by quote mismatch (5), cross-experiment evidence (5), and wrong-arm linkage (5). This shows that deterministic validation is necessary, but the accepted remainder was largely duplicate, representational, or outside the scorer's missing requirement set. One of 28 packets also violated response semantics by declaring proposals with an empty proposal list.

Retain the existing OpenAI v5.2 route. Do not implement automatic invocation, future-paper manifests, database projection, or deployment controls from this result. If the experiment is revisited, first freeze a scorer that reproduces the authoritative 40/62 baseline, then redesign packets around the known missing requirement classes without exposing their gold answers, and validate on held-out papers.

An independent concern is scorer drift: the current evaluator returns 18/62 for the untouched cached extraction, clean replay, and audited copies, while the saved authoritative result is 40/62. The zero audited-minus-replay delta is reliable, but absolute re-scoring is not reproducible until that drift is resolved.
