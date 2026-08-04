# Mentor Morning Extraction Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, bilingual, mentor-facing HTML brief that explains the morning extraction trial, the `1/36` result, Strategy 2, and the new core-record strategy.

**Architecture:** Create one standalone HTML document with semantic sections, embedded responsive CSS, and a small embedded JavaScript language switcher. Keep all historical content separate from an editable “Today’s progress” section so the page can be updated without restructuring it.

**Tech Stack:** HTML5, CSS3, vanilla JavaScript

## Global Constraints

- The artifact must remain local and must not be deployed.
- Use no frameworks, build tools, analytics, network calls, or deployment configuration.
- English is the default language; the English/中文 toggle must update all visible explanatory text without reloading.
- Describe the output as one useful but incomplete record.
- Do not describe the remaining 35 candidates as 35 verified missing database rows.
- Display `Draft — not deployed` prominently but unobtrusively.

---

### Task 1: Build and verify the bilingual mentor brief

**Files:**
- Create: `reports/extraction/mentor_morning_extraction_brief.html`
- Reference: `docs/superpowers/specs/2026-07-30-mentor-morning-extraction-brief-design.md`

**Interfaces:**
- Consumes: The approved narrative and accuracy rules in the design specification.
- Produces: A standalone HTML page whose language buttons call `setLanguage(language)` with either `"en"` or `"zh"`.

- [ ] **Step 1: Establish the static-content acceptance check**

Before creating the file, confirm that it does not exist:

```bash
test ! -e reports/extraction/mentor_morning_extraction_brief.html
```

Expected: exit status `0`.

- [ ] **Step 2: Create the complete standalone page**

Create `reports/extraction/mentor_morning_extraction_brief.html` containing:

- a draft label, title, subtitle, and English/中文 buttons;
- a hero summary with carefully qualified `1`, `36`, and `6/10` metrics;
- the eight-section story-first timeline from the approved design;
- a five-stage flow diagram;
- a human-readable card listing every field extracted from the LLM call;
- a distinction between candidate signals, verified outcomes, experiments, and database rows;
- the three-part core-record qualification rule;
- core, secondary, and optional information tiers;
- a clearly isolated “Today’s progress” section with status, change, result, remaining issue, and next-decision fields;
- embedded English and Simplified Chinese translations;
- `setLanguage(language)` to update all elements bearing `data-i18n`, set the document language, update button states, and persist the selection in `localStorage`;
- responsive styling for desktop and mobile, with reduced-motion support.

- [ ] **Step 3: Run structural checks**

Run:

```bash
rg -n 'setLanguage|data-i18n|Draft|1/36|36/36|LNP\\(DSPC\\)/DX25|HepG2|500 ng|95%|Today.s progress|not 35' reports/extraction/mentor_morning_extraction_brief.html
```

Expected: every required concept appears and the command exits successfully.

Run:

```bash
python3 -c 'from html.parser import HTMLParser; p=HTMLParser(); p.feed(open("reports/extraction/mentor_morning_extraction_brief.html", encoding="utf-8").read()); print("HTML parse: PASS")'
```

Expected: `HTML parse: PASS`.

- [ ] **Step 4: Verify bilingual coverage programmatically**

Run a read-only JavaScript check that extracts translation keys used by `data-i18n` and confirms both languages define the same keys:

```bash
node -e 'const fs=require("fs"); const s=fs.readFileSync("reports/extraction/mentor_morning_extraction_brief.html","utf8"); const used=[...s.matchAll(/data-i18n="([^"]+)"/g)].map(m=>m[1]); const en=s.match(/en:\\s*\\{([\\s\\S]*?)\\n\\s*\\},\\n\\s*zh:/); const zh=s.match(/zh:\\s*\\{([\\s\\S]*?)\\n\\s*\\}\\n\\s*\\};/); if(!en||!zh) throw Error("translation objects missing"); const keys=x=>[...x[1].matchAll(/^\\s*([A-Za-z0-9_]+):/gm)].map(m=>m[1]); const E=new Set(keys(en)), Z=new Set(keys(zh)); const missing=used.filter(k=>!E.has(k)||!Z.has(k)); if(missing.length) throw Error("missing translations: "+missing.join(",")); console.log("Bilingual keys: PASS ("+new Set(used).size+")");'
```

Expected: `Bilingual keys: PASS` with a nonzero key count.

- [ ] **Step 5: Perform visual QA**

Open the local HTML in a browser, inspect both desktop and narrow mobile widths, switch to Chinese, and confirm:

- no text overlaps or horizontal overflow;
- the flow diagram remains readable;
- language switching changes every narrative section;
- the current language button has an active state;
- the draft label remains visible;
- the “Today’s progress” section is visually distinct and easy to edit later.

- [ ] **Step 6: Leave the artifact local**

Confirm no deployment configuration or hosted version was created. Do not stage or commit the HTML unless the user explicitly requests a git operation.
