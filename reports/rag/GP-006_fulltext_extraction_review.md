# GP-006 full-text extraction review

Automated status: **accepted with zero deterministic audit findings**.

This does not establish scientific correctness. For each row, verify that the subject–relation–object statement is supported by the quote and belongs to the stated experiment.

## Unresolved ambiguities

- The supplied text does not expand the name or sequence of NSGHAsgRNA; its normalized name remains unresolved.
- The source text contains page-column interleaving around some clauses. Only exact, semantically intact quotations were retained where possible.
- The 52.7% total-liver editing result and the cell-fraction editing values are reported in the same LNP-treatment results sequence, but the provided excerpts do not state the exact temporal relationship between every molecular endpoint measurement.

## Extracted claims

| Experiment | Claim | Extracted relation | Exact evidence | Source | Human decision |
|---|---|---|---|---|---|
| SHARED: Shared | C001 | MC3 LNP (lnp_formulation) —has_component→ MC3 (lnp_component) | “D-Lin-MC3-DMA (MC3)-based LNPs” | Introduction; main.nxml; p0025 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C008 | MC3 LNP (lnp_formulation) —carries_payload→ Cas9 mRNA (payload) | “The NSGHAsgRNA was encapsulated with Cas9 Evaluation of in vivo gene editing of mutant F8 in HemA NSG mRNA into MC3 LNP and intravenously injected into NSG HemA mouse model mice at a dosage of 4 mg/kg of Cas9/sgRNA LNP.” | Supplement page 5; mmc2.pdf; 5 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C009 | MC3 LNP (lnp_formulation) —carries_payload→ NSGHAsgRNA (payload) | “The NSGHAsgRNA was encapsulated with Cas9 Evaluation of in vivo gene editing of mutant F8 in HemA NSG mRNA into MC3 LNP and intravenously injected into NSG HemA mouse model mice at a dosage of 4 mg/kg of Cas9/sgRNA LNP.” | Supplement page 5; mmc2.pdf; 5 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C016 | NSG HemA mice (biological_model) —has_species→ mice (species) | “The NSGHAsgRNA was encapsulated with Cas9 Evaluation of in vivo gene editing of mutant F8 in HemA NSG mRNA into MC3 LNP and intravenously injected into NSG HemA mouse model mice at a dosage of 4 mg/kg of Cas9/sgRNA LNP.” | Supplement page 5; mmc2.pdf; 5 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C022 | FVIII activity (endpoint) —has_outcome_value→ 3.30% ± 0.68% of FVIII activity (outcome_value) | “Post-treatment, It was previously demonstrated in our lab that following hydrody- FVIII activity was measured by aPTT, and our results indicated namic injection of plasmid DNA, transfection occurred predomi- that the treated mice generated an average of 3.30% ± 0.68% of nantly in hepatocytes; however, lower transgene expression was FVIII activity over a span of 26 weeks (Figure 5A).” | Supplement page 5; mmc2.pdf; 5 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C023 | FVIII activity (endpoint) —has_timepoint→ over a span of 26 weeks (timepoint) | “over a span of 26 weeks” | Supplement page 5; mmc2.pdf; 5 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C033 | gene editing rate in total liver cells (endpoint) —has_outcome_value→ 52.7% in total liver cells (outcome_value) | “Following injection, Cas9/NSGHAsgRNA LNP resulted in a gene editing rate of about we euthanized the treated mice and extracted genomic DNA 52.7% in total liver cells.” | Supplement page 5; mmc2.pdf; 5 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C036 | gene editing rate in LSECs (endpoint) —has_outcome_value→ 16.50% ± 2.96% (outcome_value) | “LSECs showed gene editing rates of approximately 16.50% ± 2.96%” | Results > Sustained expression of mouse FVIII following Cas9/sgRNA LNP injection; candidate_00168_PMC11617921.xml; p0060 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C039 | gene editing rate in hepatocytes (endpoint) —has_outcome_value→ 60.54% ± 11.65% (outcome_value) | “60.54% ± 11.65%” | Results > Sustained expression of mouse FVIII following Cas9/sgRNA LNP injection; candidate_00168_PMC11617921.xml; p0060 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C041 | NGS analysis (assay) —measures_endpoint→ indel variants at five top predicted potential off-target sites (endpoint) | “using next generation sequencing (NGS) analysis” | Results > Sustained expression of mouse FVIII following Cas9/sgRNA LNP injection; candidate_00168_PMC11617921.xml; p0060 |  |
| GP-006-E01: In vivo CRISPR-Cas9 mRNA LNP gene editing of mutant F8 in NSG HemA mice | C042 | indel variants at five top predicted potential off-target sites (endpoint) —has_outcome_value→ No indel variants were found at five top predicted potential off-target sites (outcome_value) | “No indel variants were found at five top predicted potential off-target sites” | Results > Sustained expression of mouse FVIII following Cas9/sgRNA LNP injection; candidate_00168_PMC11617921.xml; p0060 |  |

## Approval rule

Do not approve GP-002 unless every retained claim is correct, belongs to the right experiment, and is supported by its quoted source. Mark unsupported, mis-scoped, incomplete, or scientifically misleading rows as incorrect and record the reason in the CSV.
