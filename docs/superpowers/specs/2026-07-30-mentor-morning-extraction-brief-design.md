# Mentor Brief: Morning Extraction Trial

## Purpose

Create a simple, mentor-facing HTML progress brief explaining:

1. the morning extraction goal;
2. the failed first strategy;
3. the switch to Strategy 2;
4. what the `1/36` and desired `36/36` accounting results mean;
5. what useful information the LLM actually extracted;
6. why outcome candidates are not the same as complete database rows; and
7. the current, narrower strategy based on core application records.

The page is a local draft. It must remain easy to update after today's work and must not be deployed.

## Audience and Tone

The primary audience is the user's mentor. The explanation should be mostly visual, nontechnical, and understandable without familiarity with the codebase. Technical terminology should appear only when necessary and should be defined in plain language.

## Page Structure

Use a story-first vertical timeline:

1. **Morning goal**
   - Test whether the cohesive extraction pipeline could recover a complete set of relevant results.

2. **Strategy 1**
   - Explain the original call and why a valid-looking response was not complete.

3. **Switch to Strategy 2**
   - Explain the move from optimizing a gold-set score to testing a new paper through the existing end-to-end workflow.

4. **The `1/36` result**
   - Clarify that the ingestion pipeline produced 36 possible atomic outcome signals.
   - Clarify that the LLM returned one coherent formulation–experiment–outcome record.
   - State that the remaining candidates were unaccounted for, not necessarily 35 complete database rows.

5. **What the LLM successfully extracted**
   - LNP(DSPC)/DX25
   - ALC-0315, DSPC, cholesterol/DX, and ALC-0159
   - 25% cholesterol replacement with DX
   - N/P ratio of 6.0
   - EGFP-encoding mRNA
   - HepG2 human cells
   - in-vitro context
   - 500 ng total mRNA per well
   - 24-hour timepoint
   - approximately 95% EGFP-positive cells
   - supporting evidence references

6. **Why `36/36` accounting matters**
   - The old schema enforced the shape and quality of returned records but not paper-wide completeness.
   - A response containing one valid row could therefore finish successfully.
   - The desired contract requires every candidate to receive a disposition, such as extracted, duplicate, non-core, unsupported, or ambiguous.
   - Accounting for 36 candidates does not mean creating 36 final database rows.

7. **Current core-components strategy**
   - Create a core record when:
     1. an LNP formulation or formulation group exists;
     2. a payload is tested in a biological model; and
     3. a delivery, expression, biodistribution, or therapeutic outcome is reported.
   - Prioritize formulation, component ratios, payload, species/model, disease, delivery/target cell, organ, route/dose, outcome, and exact evidence.
   - Treat cytokines, toxicity, morphology, SAXS, release kinetics, and storage stability as secondary or optional unless they answer the application's central recommendation question.

8. **Today's progress**
   - Provide a visibly editable placeholder section for results added later today.
   - Include fields for status, change made, test result, remaining issue, and next decision.

## Visual Design

- Single responsive HTML file with embedded CSS and JavaScript.
- Clear vertical story flow with numbered sections and restrained card styling.
- A compact flow diagram:

  `Paper → 36 possible outcome signals → one coherent record returned → completeness failure → core-context accounting`

- Use large but carefully qualified metrics:
  - `1 returned outcome record`
  - `36 candidate signals`
  - `6/10 high-level core categories represented`
- Avoid presenting `1/36` as the overall scientific extraction success rate.
- Include a persistent but unobtrusive `Draft — not deployed` label.

## Language Toggle

- Place an English/中文 toggle near the top of the page.
- Keep both translations in the same HTML file using structured language attributes.
- Switching languages must update headings, descriptions, labels, diagram text, and update placeholders without reloading the page.
- English is the default.

## Updateability

- Keep content grouped into clearly labeled HTML sections.
- Store bilingual copy in a simple JavaScript translation object or paired language elements.
- Isolate today's progress content so it can be edited without changing the historical explanation.
- Do not add frameworks, build tools, analytics, network calls, or deployment configuration.

## Accuracy Rules

- Distinguish outcome candidates from verified outcomes and database rows.
- Describe the output as one useful but incomplete record.
- Do not claim that all 35 remaining candidates were valid missing rows.
- Distinguish missing values from values that were not applicable to an in-vitro experiment.
- Label inferred disease context separately from directly reported evidence.

## Acceptance Criteria

- A mentor can understand the morning failure and current strategy in approximately three minutes.
- The page accurately explains `1/36` versus candidate accounting.
- The actual extracted record is visible in human-readable form.
- English and Chinese versions contain equivalent information.
- Today's progress can be added without restructuring the page.
- The artifact remains local and is not deployed.
