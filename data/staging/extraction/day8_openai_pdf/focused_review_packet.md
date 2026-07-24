# Day 8 focused PDF/OpenAI review

This report separates deterministic page-selection misses from OpenAI semantic misses.

## GO-006 — GP-006

- Expected: Table S2 reports total insertion frequency in LSECs of 1.01 ± 0.38% after Cas9/sgRNA LNP treatment.
- Source: `mmc1.pdf`, page 2, Table S2
- Page sent before fix: **True**
- Page sent after fix: **True**
- Whole-PDF OpenAI: **missed**
- Targeted-page OpenAI: **matched**

Closest targeted records:

- `GP-006-R027`: Isolated LSECs from treated NSG hemophilia A mice | Total F8 insertion frequency | 1.01 ± 0.38 % | mmc1.pdf p.2 Table S2 LSEC × total insertion frequency
  - Evidence: “LSEC — total insertion frequency: 1.01 ± 0.38 %”
- `GP-006-R022`: Isolated LSECs from treated NSG hemophilia A mice | F8 +1-bp insertion frequency | 0.78 ± 0.27 % | mmc1.pdf p.2 Table S2 LSEC × +1
  - Evidence: “LSEC — +1: 0.78 ± 0.27 %”
- `GP-006-R023`: Isolated LSECs from treated NSG hemophilia A mice | F8 +2-bp insertion frequency | 0.21 ± 0.10 % | mmc1.pdf p.2 Table S2 LSEC × +2
  - Evidence: “LSEC — +2: 0.21 ± 0.10 %”
- `GP-006-R024`: Isolated LSECs from treated NSG hemophilia A mice | F8 +3-bp insertion frequency | 0.01 ± 0.01 % | mmc1.pdf p.2 Table S2 LSEC × +3
  - Evidence: “LSEC — +3: 0.01 ± 0.01 %”
- `GP-006-R025`: Isolated LSECs from treated NSG hemophilia A mice | F8 +4-bp insertion frequency | 0.00 % | mmc1.pdf p.2 Table S2 LSEC × +4
  - Evidence: “LSEC — +4: 0.00”

Human check: Does the closest extracted record directly support the expected fact at the cited original source location, without adding an inference?

## GO-017 — GP-008

- Expected: FAPCAR-expressing macrophages recognized and eliminated FAP-positive activated HSC models; the LNP cargo was expressed in macrophages, not HSCs.
- Source: `data/raw/fulltext/gold_v1/xml/candidate_00132_PMC13229182.xml`, page None, Figures 2 and 6
- Page sent before fix: **None**
- Page sent after fix: **None**
- Whole-PDF OpenAI: **matched**
- Targeted-page OpenAI: **matched**

Closest targeted records:

- `GP-008-R010`: Mouse JS-1 hepatic stellate cells | FAP-positive cells | 79.4 % | pnas.2534673123.sapp.pdf p.11 Figure S1 A, TGF-β1 FAP+ gate
  - Evidence: “JS-1 cells induced with TGF-β1; FAP+ 79.4.”
- `GP-008-R011`: Untreated mouse JS-1 hepatic stellate cells | FAP-positive cells | 0.37 % | pnas.2534673123.sapp.pdf p.11 Figure S1 A, NC FAP+ gate
  - Evidence: “JS-1 cells; NC; FAP+ 0.37.”
- `GP-008-R012`: BMDMs cocultured with FAP-positive JS-1 cells | Phagocytic rate relative to untreated WT BMDMs | >10 fold | pnas.202534673.pdf p.2 Figure 2 A–D
  - Evidence: “the αCD163/LNP-FAPCAR treatment induced a phagocytic rate more than ten times that of the WT group”
- `GP-008-R013`: BMDMs cocultured with FAP-positive JS-1 cells | Phagocytic rate relative to LNP-FAPCAR | approximately 3 fold | pnas.202534673.pdf p.2 Figure 2 A–D
  - Evidence: “the αCD163/LNP-FAPCAR treatment induced a phagocytic rate ... approximately three times that of the LNP-FAPCAR group.”
- `GP-008-R014`: BMDMs cocultured with FAP-positive JS-1 cells | Increase in phagocytic efficiency versus WT | No increase  | pnas.202534673.pdf p.2 Figure 2 A–D
  - Evidence: “the αCD163/LNP-Luc group did not exhibit increased phagocytic efficiency”

Human check: Does the closest extracted record directly support the expected fact at the cited original source location, without adding an inference?

## GO-018 — GP-008

- Expected: Supplementary Figure 5 maps reporter expression to CD163/F4/80-positive macrophages and compares ALB, Desmin, F4/80, and SOX9 cell markers.
- Source: `pnas.2534673123.sapp.pdf`, page 19, Appendix Figure 5G-L
- Page sent before fix: **False**
- Page sent after fix: **True**
- Whole-PDF OpenAI: **missed**
- Targeted-page OpenAI: **matched**

Closest targeted records:

- `GP-008-GO-018-L-06`: F4/80+ liver macrophages | F4/80+/ZsGreen+ positive cells | approximately 55 % | pnas.2534673123.sapp.pdf p.18 Appendix Figure 5 K-L, F4/80+/ZsGreen+
  - Evidence: “The caption identifies macrophages as F4/80+, and panel L plots the green αCD163/LNP-ZsGreen F4/80+/ZsGreen+ bar at approximately 55%.”
- `GP-008-GO-018-H-01`: Screened liver macrophages, CD163+ and ZsGreen+ quadrant (Q2) | CD163 and ZsGreen double-positive cells | 9.92 % | pnas.2534673123.sapp.pdf p.18 Appendix Figure 5 H, LNP-ZsGreen Q2
  - Evidence: “Flow-cytometry panel H labels the vertical axis CD163 and horizontal axis ZsGreen; LNP-ZsGreen Q2 is printed as 9.92.”
- `GP-008-GO-018-H-02`: Screened liver macrophages, CD163− and ZsGreen+ quadrant (Q3) | ZsGreen-positive, CD163-negative cells | 0.71 % | pnas.2534673123.sapp.pdf p.18 Appendix Figure 5 H, LNP-ZsGreen Q3
  - Evidence: “Flow-cytometry panel H labels the vertical axis CD163 and horizontal axis ZsGreen; LNP-ZsGreen Q3 is printed as 0.71.”
- `GP-008-GO-018-H-03`: Screened liver macrophages, CD163+ and ZsGreen+ quadrant (Q2) | CD163 and ZsGreen double-positive cells | 10.4 % | pnas.2534673123.sapp.pdf p.18 Appendix Figure 5 H, αCD163/LNP-ZsGreen Q2
  - Evidence: “Flow-cytometry panel H labels the vertical axis CD163 and horizontal axis ZsGreen; αCD163/LNP-ZsGreen Q2 is printed as 10.4.”
- `GP-008-GO-018-H-04`: Screened liver macrophages, CD163− and ZsGreen+ quadrant (Q3) | ZsGreen-positive, CD163-negative cells | 15.0 % | pnas.2534673123.sapp.pdf p.18 Appendix Figure 5 H, αCD163/LNP-ZsGreen Q3
  - Evidence: “Flow-cytometry panel H labels the vertical axis CD163 and horizontal axis ZsGreen; αCD163/LNP-ZsGreen Q3 is printed as 15.0.”

Human check: Does the closest extracted record directly support the expected fact at the cited original source location, without adding an inference?

