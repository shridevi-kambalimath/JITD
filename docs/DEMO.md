# MEDUSA-X demo guide

Synthetic patient SYN-0001, seven fictional documents in `data/demo/SYN-0001`. Every number on screen is
computed by the backend from these files; nothing is hardcoded. The ground truth is `data/demo/expected.json`.

## Before the demo (2 minutes)

1. Start the app. On stage, prefer the single-process demo: **Terminal, Run Task, Demo: single process** (it builds the
   UI, then one server serves UI and API on http://127.0.0.1:8000; stop any other backend first). For development,
   **Ctrl+Shift+B** runs backend and Vite separately. Either way the sidebar footer must show the same version for UI
   and API.
2. Check the ground truth: **Terminal, Run Task, Evaluate: ground truth** (or `cd backend` then
   `python -m medusa.evaluate`). It loads the bundle into a temporary database, analyses it and must end with
   `All expected states matched, every planted issue found, 0 false conflicts.`
3. In the app: **Documents, Reset demo data**, then **Overview, Run analysis**. This clears earlier uploads, findings
   and review statuses, so every demo starts from the same state.
4. Optional, after a rehearsal: `python -m medusa.evaluate --current` scores what is in the app's database right now.
   After step 7 below (uploading the endoscopy report) it reports differences on purpose: the bundle has changed,
   the endoscopy item is now supported and a gastric ulcer finding exists. Reset to score the bundle again.

## Demo-day checklist

- [ ] Laptop on mains power, sleep and notifications off, browser zoom 100%, one browser tab.
- [ ] **QA: everything** task passes (tests, build, `37 of 37` ground truth).
- [ ] **Demo: single process** running; http://127.0.0.1:8000 shows **Backend online** and matching versions.
- [ ] Documents, **Reset demo data**; Overview, **Run analysis**: 7 documents, 51 claims, 7 discrepancies.
- [ ] `data\samples\endoscopy_report.pdf` easy to reach in the file picker (step 7).
- [ ] Rehearsed the 3-minute path twice in a row, with a reset in between, no fixes needed.
- [ ] Pitch deck open on its own screen or tab; `docs/LIMITATIONS.md` read so questions get straight answers.
- [ ] Fallback ready: if the network or the laptop fails, the deck's demo slide narrates the same path.

## The nine scenarios and where to show them

| # | Scenario | Where | What to point at |
|---|---|---|---|
| 1 | Chronology across documents | Clinical Timeline | Entries from `2015` (year only) to `2026-03-29` (follow-up), solid border for stated dates, dashed for document-date placement |
| 2 | Event date differs from document date | Clinical Timeline, Lab result | Haemoglobin "Collected 2026-03-11 · report dated 2026-03-12" |
| 3 | Medication change over time | Reconciliation, Pantoprazole and Warfarin | Pantoprazole IV, oral, then reduced: two documented changes, not flagged; warfarin listed, held, listed again, restarted on 2026-03-29 |
| 4 | Discrepancy across two sources | Reconciliation, Chronic kidney disease | Absent (progress note) vs present (discharge), A and B side by side, Conflicting evidence |
| 5 | Missing referenced document | Reconciliation, Endoscopy report and Histopathology report | Referred to but not in the bundle, Insufficient evidence |
| 6 | Ambiguous date | Review Queue, Uncertain dates | "Dizziness since last week": written, but no anchor, so **not resolved**; on the timeline it says why it sits at the document date |
| 7 | Source-supported claim | Reconciliation, Atorvastatin; Evidence inspector | Brand "Atorva" normalised; three lists agree; Inspect shows 6 of 6 hard checks |
| 8 | Claim requiring review | Reconciliation or Review Queue, Warfarin | Held for a bleed, listed active two days later, missing at discharge; anticoagulant, so Review required (GATE-03); retrieval check found no restart in between |
| 9 | Insufficient evidence | Review Queue, Amlodipine | On admission, absent at discharge, no stop documented |

## A 3-minute path

1. **Landing**: one sentence on the problem, then **Open synthetic demo workspace**.
2. **Overview**: run the analysis; all six stages and the evidence-state bar fill in from the backend.
3. **Reconciliation, Warfarin**: both source sentences side by side, "no restart documented", the retrieval check,
   Review required because it is an anticoagulant. Then **Drug allergies** (penicillin vs no known allergies).
4. **Examined and not flagged**: expand **Evidence-supported (10)** at the bottom of the list, then open
   **Pneumonia** (possible, then ruled out), **Pantoprazole** (changes documented) and **Breast cancer** (the
   mother's, family history). Each shows an "Examined and not flagged" note explaining why it is not a discrepancy.
5. **Clinical Timeline**: approximate onset `~2026-03-07`, lab collection vs report date, the unresolved
   "since last week".
6. **Inspect** any claim: highlighted passage, offsets, both dates, every check.
7. **Upload** `data\samples\endoscopy_report.pdf` on Documents, re-run: the endoscopy item becomes evidence-supported
   and the report's own finding (gastric ulcer) appears.
8. **Summary**: every line cited, disclaimer on top, Download Markdown.

## What to say when asked

* "Does verified mean correct?" No. Verified means the claim is anchored exactly to its source text. Whether the
  record is clinically right is for the clinician; the system never picks a side.
* "Why keyword search, not embeddings?" Every hit is exactly traceable and it works offline. The search sits behind an
  interface a semantic retriever can implement later.
* "What if the LLM is down?" Rules always run; the run completes and says the LLM was not used.
