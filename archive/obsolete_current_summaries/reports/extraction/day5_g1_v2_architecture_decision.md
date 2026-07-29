# G1 v2 architecture decision

**Status: abandoned before final scoring.**

Human review identified systemic cross-experiment context mixing. Correct facts
were repeatedly attached to the wrong experiment, disease model, recipient
cell, therapeutic target, or outcome. The four independent entity passes made
post-hoc linkage unreliable, so continuing field-level review would not yield a
defensible G1 metric.

V3 freezes sentence-level experiment boundaries using two independent readers
before extracting any formulation, cell, payload, context, or outcome fields.
