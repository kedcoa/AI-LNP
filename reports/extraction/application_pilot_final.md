# Three-paper application extraction pilot — final local replay

## Outcome

The saved responses now merge end to end without another provider call. The
replay used exactly **14 context responses** (12 usable original Gate-B
contexts plus the two completed context retries) and **3 corrected selective-
vision responses**. All 17 selected provider outputs pass their exact frozen
JSON schemas. All three vision responses preserve the locally issued
experiment and candidate IDs and cite only evidence inside their visual task
envelopes.

The strict frozen evaluator reports **28/62 = 45.2% recall**. That is the
mechanical string-and-arm score, not a scientifically fair summary of the
extraction. It treats supported wording variants such as “intravenous
administration” versus “intravenous” as different, and it counts hundreds of
valid extra extracted facts against a deliberately small 62-fact answer key.
Its low key-match “precision,” eight wrong-arm flags, and 0/7 complete-arm
score are therefore diagnostic of the evaluator's normalization/partial-key
limits, not evidence that 94% of the extracted science was false.

A second deterministic, evidence-grounded mode raises recall to **40/62 =
64.5%**. It permits a one-to-one text match only when paper, experiment, field
category and evidence IDs agree and the values share a distinctive endpoint
or entity token. Exact numeric values, doses and component identities remain
strict. This is a safer application-oriented score, but it still fails the
frozen acceptance thresholds:

| Deterministic acceptance check | Result |
|---|---:|
| Overall required-information recall ≥80% | **Fail — 64.5%** |
| Qualitative outcome recall ≥80% | **Fail — 60.0%** |
| Exact-numeric recall ≥80% | **Fail — 75.0%** |
| Invented IDs = 0 | **Pass — 0** |
| Unsupported exact numerics = 0 | **Pass — 0** |

The evidence-grounded complete-arm score is **2/7 = 28.6%**. Its 11
wrong-arm diagnostics remain conservative evaluator flags; none were confirmed
as scientific reassignments by the evidence audit after
quarantine. The deterministic gate therefore **does not pass**.

An independent evidence-level audit gives a complementary application view:

| Paper | Fully recovered | Partial | Absent | Usable including partial |
|---|---:|---:|---:|---:|
| PILOT-001 | 17/19 (89.5%) | 1 | 1 | 18/19 (94.7%) |
| PILOT-002 | 18/21 (85.7%) | 2 | 1 | 20/21 (95.2%) |
| PILOT-003 | 22/22 (100%) | 0 | 0 | 22/22 (100%) |
| **Overall** | **57/62 (91.9%)** | **3** | **2** | **60/62 (96.8%)** |

The science-audited complete-arm result is **5/7 (71.4%)**. This score is
explicitly a human audit, not an acceptance metric. Every one of the 62 audit
rows is recorded in `application_pilot_final.json` with its disposition,
bound experiment/candidate, exact merged fact path, extracted value, and
actual evidence IDs. The two incomplete arms are PILOT-001's efficacy arm
(dose equivalence detail) and PILOT-002's mannose-mCre arm (route specificity
and missing flow-cytometry assay detail).

## What was extracted

### PILOT-001

- AA-T3A-C12 LNP composition with DSPC, cholesterol and C14-PEG2000; molar
  ratio 50:10:38.5:1.5 and ionizable-lipid:RNA mass ratio 10:1.
- HSP47 siRNA, intravenous administration, 5 µg siRNA per mouse, BALB/c
  CCl4-induced fibrosis model, activated hepatic stellate-cell targeting.
- Western-blot and Picrosirius-red assays; exact 65% HSP47 knockdown.
- Qualitative comparison that AA-T3A-C12/siHSP47 produced stronger knockdown
  and collagen reduction than MC3/siHSP47. Selective vision independently
  recovered the collagen comparison and retained the issued PEC-5 experiment.

### PILOT-002

- DOPE, cholesterol, PEG-lipid, C16-PEG2000-ceramide evidence, the
  26.5:20:52:1.5 molar formulation, and mannose-PEG targeting evidence.
- Cre mRNA, intravenous 0.5 mg/kg delivery, the LSL-tdTomato reporter model,
  and liver sinusoidal endothelial-cell targeting.
- Exact 70% LSEC and 15% hepatocyte results, plus the qualitative LSEC-over-
  hepatocyte selectivity comparison recovered by selective vision.
- The factor-VIII siRNA confirmation context and improved inhibition with
  mannose incorporation were retained.

### PILOT-003

- KL-52/DSPC/cholesterol/PEG-c-DOMG, molar ratio 50:10:38.5:1.5 and total
  lipid:siRNA mass ratio 7:1.
- Jnk2 siRNA set 3, intravenous 0.2 mg/kg delivery, hepatocytes, and the
  hepatocyte-specific NEMO-deficient chronic-liver-disease/HCC model.
- qRT-PCR, immunoblot and Sirius-red evidence.
- Hepatocyte-specific Jnk2 knockdown; early-stage apoptosis and proliferation;
  late-stage reductions in HCC/premalignant nodules, collagen and serum ALT.
  The collagen and ALT facts survive through qualified atomic candidate-
  outcome paths rather than conflicting with one another.
- Selective vision retained the issued CTX-4 experiment and independently
  recovered reduced tumor burden/liver injury and improved parenchymal
  architecture.

## True misses and partial fields

- **Absent:** PILOT-001's exact 60.32% primary-HSC table value. The retained
  experiment inventory never issued the corresponding arm, so this is an
  upstream inventory miss rather than a merge failure.
- **Absent:** PILOT-002's flow-cytometry assay detail for tdTomato-positive
  liver cells.
- **Partial:** PILOT-001 extracted 5 µg siRNA per mouse but not the equivalent
  0.2 mg/kg expression in the same dose record.
- **Partial:** PILOT-002 retained 246C10 inside a structured 241C10-to-246C10
  series rather than as its own component identity.
- **Partial:** PILOT-002's arm-level route says only “Injected”; intravenous
  administration exists at paper level but is not explicit in that arm field.

## Validation and quarantine findings

- The generic shared-formulation adapter now emits `mass_ratio = 10:1` when a
  ratio-basis field literally contains “weight ratio 10:1,” retaining the same
  source evidence. This is direct parsing, not scientific inference.
- PILOT-003's NEMO/HCC model requirement was corrected from CTX-1 to CTX-4
  before the final score because its frozen benchmark scope is the advanced
  therapeutic HCC experiment, not the earlier tissue-specificity experiment.
- Selective-vision responses must now echo the finding ID, requested field,
  experiment ID and candidate ID issued in the visual task. A response with an
  invented finding ID is quarantined before its fragment can enter the merge.
- Three context outputs were exact-schema valid but had fragment-level local
  findings. PILOT-001 REQ-4 expanded “activated HSCs” to its full name;
  PILOT-002 REQ-9 cited evidence on two fields correctly marked missing; and
  PILOT-003 REQ-14 did the same on six missing fields. Only those malformed or
  mismatched fragments were excluded; the reported supported facts remained.
- Two AA-T3A-C12 head/tail substructures were quarantined instead of being
  treated as independently admixed formulation components.
- `encoded_product = GFP` was removed because siGFP targets GFP but does not
  encode it. `molecular_target = sigma receptor` was removed because the sigma
  receptor mediates uptake rather than being the siRNA target.
- PILOT-002's baseline 80/40/10 mCre result retained its supported outcomes,
  but its overly generic PEG-tuned formulation link was quarantined.
- MC3 shared-formulation facts whose citations were outside the issued paper
  envelope were quarantined. No evidence ID was fabricated to retain them.
- Scientific audit penalties after quarantine: **0 invented IDs, 0 unsupported
  exact numeric values, and 0 confirmed cross-arm reassignments**. One
  formulation linkage remains explicitly ambiguous rather than silently fixed.

## Token usage and decision

| Stage | Actual tokens |
|---|---:|
| Gate A | 95,012 |
| Initial Gate B | 163,087 |
| Five-call retry | 35,432 |
| **Cumulative** | **293,531** |

The three original schema-rejected vision requests failed before inference and
have no inference-token usage. No API call, credential load or network request
was made during this validation, merge and scoring replay.

The deterministic acceptance gate did not pass, so this pilot should not be
reported as a validated ≥80% autonomous extractor. Nevertheless, the core
records are useful for database/UI work: all three papers contain
application-relevant formulation, model and outcome data, while the itemized
human audit finds 57 full, 3 partial and 2 absent requirements. Following the
project's stop rule, database loading and UI work can proceed with explicit
quarantine and confidence flags instead of starting another extraction
architecture cycle.
