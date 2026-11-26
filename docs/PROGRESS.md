# MEDUSA-X Progress Log

Updated at the end of every phase. "Tests executed" lists only runs that actually happened.

## Phase checklist

- [x] Phase 1 Foundation
- [x] Phase 2 Document ingestion
- [x] Phase 3 Structured extraction (rules + optional LLM)
- [x] Phase 4 Timeline
- [x] Phase 5 Reconciliation
- [x] Phase 6 Verification gate + evidence inspector
- [x] Phase 7 Retrieval
- [x] Phase 8 Frontend integration (overview metrics, review queue, summary)
- [x] Phase 9 Demo dataset (follow-up document, ambiguous date, ground truth, reset)
- [x] Phase 10 QA (failure drills, end-to-end test, accessibility; Windows run-through still to be done by the user)
- [x] Phase 11 Final polish (single-process demo, pitch deck, limitations, demo-day checklist)

---

## Phase 11: Final polish (2026-11-25)

Version 0.11.0. No schema change. New setting `MEDUSA_SERVE_FRONTEND` (default false).

### What was added or fixed
* **Single-process demo.** With `MEDUSA_SERVE_FRONTEND=true` the backend serves `frontend/dist`. Deep links get the
  app shell; hashed assets are cached for a year and `index.html` is never cached. The UI is served from the 404 path,
  not a catch-all route, so every `/api` response is unchanged: unknown endpoints stay 404 JSON and a wrong method on a
  real endpoint stays 405. Path traversal is refused. `python -m medusa` refuses to start if the build is missing,
  and prints the one URL. There is a VS Code task **Demo: single process** (build, then serve).
* **Real UI defect found in rehearsal.** For about 300 ms after selecting a finding, the Reconciliation panel showed
  the newly selected finding's heading with the previous finding's evidence state (keepPreviousData). After a re-run,
  it also showed the pre-run state until the refetch landed. Fix:
  * no placeholder data for finding detail;
  * after a run or a demo reset, cached results no screen is showing are removed (`replaceAnalysisResults`);
  * the panel shows a skeleton until list and detail come from the same `results_run_id`.
* **DEMO.md step 4** now says to expand **Evidence-supported (10)** first; the "Examined and not flagged" notes live
  inside findings. The rehearsal stalled there, and a presenter would too.
* **Not-found page** no longer mentions build phases.
* **VS Code tasks:** `activesBegins` typo fixed to `activeBegins` (VS Code ignored the misspelt key).
* **Docs:** `docs/LIMITATIONS.md` (new), a demo-day checklist in `docs/DEMO.md`, single-process steps in `README.md`
  and `docs/QA.md` (A7).
* **Pitch deck** (10 slides, a Slides artifact, outside the zip): problem, what it does, architecture, evidence states,
  trust model, demo path, evaluation (with its caveat), limitations, next steps. Placeholders to fill: `[Team name]`,
  `[Presenter]`, `[contact]`.

### Files created
`backend/medusa/web.py`, `tests/test_web.py`, `frontend/src/api/analysis-cache.test.ts`, `docs/LIMITATIONS.md`.

### Files modified
`backend/medusa/main.py`, `backend/medusa/core/config.py`, `backend/medusa/__init__.py`, `.env.example`,
`frontend/src/api/analysis.ts`, `frontend/src/api/reconciliation.ts`, `frontend/src/api/documents.ts`,
`frontend/src/pages/reconciliation.tsx`, `frontend/src/pages/reconciliation.test.tsx`, `frontend/src/pages/not-found.tsx`,
`frontend/package.json`, `frontend/package-lock.json`, `tests/test_e2e.py`, `.vscode/tasks.json`, `README.md`,
`docs/DEMO.md`, `docs/QA.md`, `docs/PROGRESS.md`.

### Tests executed
* `python -m pytest`: 376 passed. `pyflakes`: clean.
* `npx tsc -b`, `npm run build`: clean. `npx vitest run`: 92 passed.
* `python -m medusa.evaluate`: 37 of 37.
* **Exit criterion (demo runs twice in a row without a manual fix).** A Playwright rehearsal of the DEMO.md 3-minute
  path ran twice on the single-process server with Vite stopped, with a reset in between. Results were identical:
  * 51 claims; Warfarin Review required (GATE-03);
  * endoscopy Insufficient (GATE-06) before the upload, Evidence-supported (GATE-07) after it;
  * gastric ulcer finding present; Markdown export with its disclaimer;
  * no console errors.

  `tests/test_e2e.py` checks the same path twice through the API and compares the full summary text.
* Mutation checks: 9 of 9 killed. Static serving (5): API exclusion, traversal guard, missing-file 404, asset cache,
  GET/HEAD only. Stale-state fix (4): placeholder data back, run-id guard off, removal off, removal of active queries.
* Deck: rendered locally at 1920×1080; all 10 slides fit inside the margins.

### Limitations
See `docs/LIMITATIONS.md`. Specific to this phase:
* The rehearsal was automated on Linux, not performed by a person on Windows. A human rehearsal on the demo laptop is
  in the demo-day checklist.
* The deck preview used fallback fonts (no network here); the Slides viewer uses IBM Plex Sans and JetBrains Mono.

### Next
None planned. Remaining before the event: run `docs/QA.md` Part A on Windows, fill the deck placeholders, and rehearse
on the demo laptop.

---

## Phase 10: QA (2026-11-25)

Version 0.10.0. No schema change. One API addition: `GET /api/health` now includes `max_upload_bytes`.

### What was added or fixed
* **Database deleted or replaced while running.** It was a generic 500 with no way back. Now the server recreates
  an empty schema and returns 503 `database_recreated` with instructions. The UI shows an amber "database not
  ready" banner and refetches everything when it clears.
* **Backend stopped mid-session.** Health polls every 3 s while down (30 s while healthy). When it comes back,
  every non-health query is invalidated, so screens refresh without a browser reload.
* **Port in use.** `python -m medusa` checks the port first. It tells you whether another MEDUSA-X backend
  (with its version) or another program holds it, prints the Windows and macOS/Linux commands to free it, and
  exits with code 1. The check is connect-based, because a bind-based check falsely reported "in use" during
  TIME_WAIT right after a restart.
* **Upload over 5 MB, real bug found live.** Through the Vite proxy the UI randomly showed "backend could not be
  reached" (502) instead of the 413. Cause: the server answered before reading the body and closed the socket
  mid-upload. Fix: bodies up to 64 MB are drained before the 413 is sent, and the UI rejects oversized files
  before sending, using the limit from `/api/health`. After the fix, 10 of 10 raw 6 MB uploads through the proxy
  returned 413.
* **Accessibility.** axe-core went from 2 rule failures to 0 violations on 9 screens. `--color-ink-faint` was
  darkened to #646a76 (contrast 3.41:1, now 4.5:1 or better on every surface), and the evidence-state bar is a
  `group`, not an `img` containing buttons.
* **Mobile.** The Review page overflowed at 390 px (a sentence-length badge with `nowrap`). Fixed; there is no
  overflow on 8 screens at 360 and 390 px.
* `scripts/fake_llm_server.py`: a stdlib-only fake LLM for the "LLM returns garbage" drill on Windows
  (`prose`, `bad-json`, `wrong-quote`).
* `docs/QA.md`: the Windows run-through checklist and six drills with the exact expected messages. There is also
  a VS Code task **QA: everything**.

### Files created
`tests/test_drills.py`, `tests/test_e2e.py`, `frontend/src/components/recovery.test.tsx`,
`scripts/fake_llm_server.py`, `docs/QA.md`.

### Files modified
`backend/medusa/core/errors.py`, `backend/medusa/main.py`, `backend/medusa/api/health.py`,
`backend/medusa/schemas/common.py`, `backend/medusa/__init__.py`, `frontend/src/api/health.ts`,
`frontend/src/components/backend-banner.tsx`, `frontend/src/components/upload-dropzone.tsx`,
`frontend/src/components/evidence-state-bar.tsx`, `frontend/src/pages/review.tsx`, `frontend/src/index.css`,
`frontend/src/pages/documents.test.tsx`, `frontend/src/test/utils.tsx`,
`frontend/src/components/workspace-shell.test.tsx`, `tests/test_app.py`, `.vscode/tasks.json`, `README.md`,
`frontend/package.json`, `frontend/package-lock.json`.

### Tests executed
* `python -m pytest`: 367 passed. `pyflakes`: clean.
* `npx tsc -b`, `npm run build`: clean. `npx vitest run`: 89 passed.
* `python -m medusa.evaluate`: 37 of 37.
* Live drills in Chromium (Playwright, through the Vite proxy): all six show their message and recover.
* `scripts/fake_llm_server.py`, all three modes, against the real pipeline: prose and bad-json give
  `malformed_output` with 51 rule claims; wrong-quote rejects 7 of 7 proposals as `quote_not_in_passage`.
* Mutation checks: 9 of 9 killed. Backend: recreate not called, "no such table" check removed, port check always
  free, body drain removed (killed only after adding a deterministic raw-socket test; the first real-server test
  let it survive). Frontend: recovery invalidation removed, recovery poll removed, degraded banner removed, size
  pre-check removed, off-by-one at the limit.

### Limitations
* **The Windows run-through has not been executed** (no Windows machine in the build environment). Follow
  `docs/QA.md` Part A.
* On Windows, deleting `medusa.db` while the backend runs may be refused by file locking. The documented fallback
  is to stop, delete, then start.
* While the backend is down, screens keep the last loaded numbers under the red banner. This is cached data,
  clearly flagged, but not blanked.
* No real LLM provider was exercised. All LLM drills use fakes.

### Next
Phase 11: final polish (single-process demo, pitch, limitations).

---

## Phase 9: Demo dataset and ground truth (2026-11-25)

Version 0.9.0. No schema change.

### Files created
* `data/demo/SYN-0001/07_followup_clinic_note.txt` (2026-03-29): warfarin restarted with its own date, pantoprazole
  reduced (a further documented change), "Dizziness since last week" (ambiguous date), "No further black stools"
  (negated, not added).
* `backend/medusa/evaluate.py`: `python -m medusa.evaluate` scores a run against the ground truth (fresh run in a
  temporary database by default; `--current`, `--json`, `--expected`). Exit code 0 only if every check passes.
* `docs/DEMO.md`: pre-demo checklist, the nine scenarios and where to show each, a 3-minute path, answers to the
  likely questions. `tests/test_evaluate.py`, `frontend/src/lib/dates.test.ts`.

### Files modified
* `data/demo/expected.json`: 7 documents; warfarin and pantoprazole notes updated; date checks for dizziness
  (unresolved) and the warfarin restart; the nine scenarios.
* `data/samples/endoscopy_report.pdf`: regenerated with `tests/factories.text_pdf`; findings are now a gastric ulcer
  with a visible vessel, clips, biopsy, and an impression "Bleeding gastric ulcer" instead of placeholder text.
* `analysis/dates.py`: vague relative expressions ("since last week", "recently", "a few days ago", ...) are kept as
  written with `value=None`; never resolved. `analysis/lexicon.py`: dizziness; gastric ulcer.
* Frontend: unresolved dates show "not resolved" (not "undated"); the timeline says "Date written as ... cannot be
  resolved; placed by the document date"; source cards omit the "other list" label.
* `.vscode/tasks.json`: **Evaluate: ground truth** task. UI text no longer states the bundle size.
* Tests: demo counts updated for 7 documents (51 claims: medication 14, symptom 4; timeline 19 by event date, 32 by
  document date; 7 uncertain dates). Reconciliation ground truth unchanged: 17 findings, same states.

### The nine scenarios (all pass)
Chronology across documents; event date differs from document date; medication change over time; discrepancy
across two sources; missing referenced document; ambiguous date; source-supported claim; claim requiring review;
insufficient evidence. Definitions and where to show them: `docs/DEMO.md`.

### Tests executed
* `python -m medusa.evaluate`: **37 of 37 checks passed** (3 run checks, 17 findings + no unexpected findings +
  0 false conflicts on 7 decoys, 6 date checks, 9 scenarios). Exit code 0.
* `pytest`: **355 passed** (was 342). New: evaluator exit criterion on a fresh run; JSON report covers every finding,
  date check and scenario; five kinds of wrong expectation each fail with the right line (state, issues, missing
  finding, date, document count); `--current` needs an analysis and scores the live database; vague dates stay
  unresolved; the regenerated endoscopy report yields a supported gastric ulcer and resolves the missing reference.
* `npm test`: **85 passed** (was 83). Typecheck and build clean.
* Mutation checks: 7 planted bugs (vague-date rule removed, issue comparison dropped, unexpected findings ignored,
  date value not compared, unresolved dates not offered for review, "not resolved" shown as "undated", timeline
  placement text ignoring the written date). 7 of 7 caught.
* Live run (real servers + Chromium): Landing, **Open synthetic demo workspace**, Run analysis gives 7 documents, 51
  claims (all verified), 51 timeline entries in 9 date groups ending 2026-03-29, 7 discrepancies, 7 pending; dizziness
  on the timeline with the unresolved-date text and in the Review Queue as "not resolved"; warfarin shows the
  follow-up restart under "Other records for this subject"; uploading the endoscopy report and re-running gives 18
  subjects with Gastric ulcer and Endoscopy report evidence-supported; no console errors.
  `python -m medusa.evaluate --current` on that database then reports 33 of 37 with an explanatory note, as intended
  (the bundle was changed by the upload).

### Known issues / limitations
* The ground truth covers one synthetic patient written alongside the rules. It shows the pipeline does what it was
  designed to do on these records; it is not evidence of accuracy on other phrasing.
* "Since last week" could be bounded (roughly a week before the document date). It is deliberately left unresolved.
* Not verified here: a real LLM call (unchanged).

### Next step
Phase 10: QA. End-to-end run-through on a clean Windows setup, failure drills (backend down mid-demo, port taken,
LLM failing, corrupted upload), accessibility pass, and fixes.

---

## Phase 8: Frontend integration (2026-11-25)

Version 0.8.0. No schema change.

### Files created
* `backend/medusa/analysis/summary.py` (template-built summary + Markdown), `analysis/workspace.py` (overview counts,
  review queue, summary), `schemas/summary.py`, `schemas/workspace.py`, `api/workspace.py`; `tests/test_workspace.py`.
* `frontend/src/api/workspace.ts`, `components/evidence-state-bar.tsx`, `pages/review.tsx`, `pages/summary.tsx`,
  `pages/review.test.tsx`, `pages/summary.test.tsx`.

### Files modified
* `schemas/domain.py`: prototype summary models removed (replaced by `schemas/summary.py` with citations).
* `api/reconciliation.py`: review-queue route moved to `api/workspace.py` with a richer response.
* Frontend: Overview rebuilt on `GET /overview` (one call for all stages) with the evidence-state stacked bar;
  documents card shows a retryable error; sidebar has no disabled items (the phase-gating code is removed); routes
  for Review Queue and Summary; UI text no longer states how many documents the demo has.

### API
`GET /api/patients/{pid}/overview`, `GET /api/patients/{pid}/review-queue` (findings not evidence-supported, claims
that failed verification, uncertain dates, counts), `GET /api/patients/{pid}/summary`, `GET /api/patients/{pid}/summary.md`.

### Design note: the evidence-state bar
Status fills from the dataviz reference status palette (critical, serious, warning, good). The palette validator was
run on both candidate palettes: the app's existing state tokens fail as fills (two near-identical reds, too dark), and
the status palette has a sub-3:1 warning/serious pair that is close in hue. Mitigation as the method requires: 2px
gaps between segments, an icon + label + count + share legend that doubles as the table view, and a tooltip on hover
and keyboard focus. Colour never carries the state alone.

### Tests executed
* `pytest`: **342 passed** (was 330). New: overview before anything; overview counts equal the detailed endpoints;
  failed upload counted; pending review distinct from items needing attention; review queue groups and reasons;
  failed-verification claims listed and kept out of uncertain dates; summary well formed before analysis; **every
  content line cites existing verified claims**; section order and labels; no judging or recommending words; Markdown
  download headers and content; failed claims excluded; stale marker.
* `npm test`: **83 passed** (was 73). New: Overview stages and bar from `/overview` (counts, shares, segment
  widths, tooltip, links), failed verification and stale on stages, overview error with retry; Review Queue loading,
  groups, status change persisted, filter, navigation to reconciliation and to evidence, empty, error with retry,
  nothing-to-review; Summary disclaimer, labelled lines, citations to evidence, empty sections, download link, empty
  before analysis, stale, error; **every sidebar item is an enabled link to a built screen**.
* Exit criterion, literal counts: a grep of non-test frontend sources for numbers in UI text finds none (only an SVG
  path in the logo); three descriptions that said how many demo documents exist were reworded.
* Mutation checks: 12 planted bugs (summary using unverified claims, missing state label, overview pending equal to
  items, approximate dates not listed, failed claims listed as dates, unresolved section including supported items,
  Overview "Needs review" showing items, equal-width bar segments, changed items missing from the pending filter, no
  state badge on summary lines, citations not linking to evidence, status dropdown not saving). 9 caught at first; two
  tests were tightened and caught two more. The remaining one (dropping the "skip evidence-supported" guard in the
  unresolved section) is equivalent: the gate never gives an evidence-supported finding an issue.
* Live run (real servers + Chromium): Review Queue and Summary empty states before analysis; after demo + analysis all
  six stages and the bar (2/2/3/10 of 17, tooltip "Conflicting evidence: 2 of 17 (12%)"); no disabled sidebar items;
  Review Queue counts, flagging warfarin drops pending to 6 (and the Overview to 6 of 7), six uncertain dates; Summary
  with 11 sections, first unresolved item warfarin (Review required); Markdown download `medusa-x-summary-SYN-0001.md`;
  a citation opens the inspector; 390 px mobile without overflow on Overview, Review Queue and Summary; no console errors.

### Known issues / limitations
* The summary restates claims; it does not condense them. Repeated facts appear once per source by design.
* The Review Queue sets status only; notes are edited on the Reconciliation screen.
* Not verified here: a real LLM call (unchanged).

### Next step
Phase 9: demo dataset. Follow-up document, an ambiguous date, fuller ground truth, endoscopy sample with real
synthetic findings, and a scripted reset for demo day.

---

## Phase 7: Evidence search (2026-11-25)

Version 0.7.0. No schema change.

### Files created
* `backend/medusa/analysis/search.py` (one BM25 ranking over stored passages drives four scopes),
  `schemas/search.py`, `api/search.py`; `tests/test_search.py`.
* `frontend/src/api/search.ts`, `pages/search.tsx`, `pages/search.test.tsx`.

### Files modified
* `analysis/retrieval.py`: lab abbreviation expansion ("Hb" finds "Hemoglobin"); section labels indexed with each
  passage ("allergies" finds the lines under ALLERGIES); `Retriever` protocol so a semantic retriever could replace
  BM25 behind the same API; `match_spans` for highlighting.
* Frontend: Evidence Search route and sidebar link enabled.

### API
`GET /api/patients/{pid}/search?q=&scope=all|passages|claims|timeline|reconciliation`. Counts cover every scope;
lists outside the requested scope are empty. Claims, timeline entries and findings take the score of the passage
they come from, so every list ranks the same way.

### Tests executed
* `pytest`: **330 passed** (was 309). New: query expansion (generic/brand both ways, lab abbreviation, stop words);
  whole-token highlighting; expansion is what finds "Glycomet"; exit criterion (metformin: the admission note's
  "Glycomet 500 mg orally twice daily." ranks first, "Glycomet" marked, its claim and CONFLICTING_EVIDENCE item
  attached); consistent ranking and hits pointing at stored evidence; section search; lab abbreviation; scope
  filtering keeps counts; no-match and stop-word notes; 422 cases; empty before analysis; unverified claims stay off
  timeline hits.
* `npm test`: **73 passed** (was 68). Typecheck and build clean.
* Mutation checks: 10 planted bugs (no lab expansion, sections not indexed, no highlight spans, unverified claims as
  timeline hits, scope ignored, section-matched claims dropped, All tab not limited, matches not marked, expansion
  not shown, empty query sent). 10 of 10 caught.
* Live run (real servers + Chromium): "Run the analysis first" before analysis; metformin gives 3 passages with
  Glycomet first and marked, tabs Passages 3, Claims 3, Timeline 3, Reconciliation 1; allergies, Hb and kidney give
  the expected passages and items; a reconciliation hit opens its item; 390 px mobile without horizontal overflow;
  no console errors.

### Known issues / limitations
* Keyword search only: no stemming ("allergy" does not match "allergies" except through the section label) and no
  semantic matching ("blood thinner" does not find warfarin). The lexicon expansions cover the demo vocabulary.
* The index is rebuilt in memory on each request. Fine for a few hundred passages; a larger corpus would need a
  persisted index.
* Not verified here: a real LLM call (unchanged).

### Next step
Phase 8: frontend integration. Review Queue screen (by evidence state, with review status), evidence summary
(template-generated, every line citing verified claims) and the Summary screen.

---

## Phase 6: Verification gate and evidence inspector (2026-11-25)

Version 0.6.0. Database schema v5.

### Files created
* `backend/medusa/analysis/verification.py` (V1 to V7), `analysis/gate.py` (GATE-01 to GATE-07, ported from the tested
  prototype), `analysis/evidence.py` (inspector; re-runs verification against the text as stored now),
  `schemas/evidence.py`; `tests/test_verification_gate.py`.
* `frontend/src/pages/evidence.tsx`, `lib/verification.ts`, `pages/evidence.test.tsx`.

### Files modified
* `db/schema.py`: migration v5 (`verifications` table, cascading with claims; `findings.state`, `findings.gate_rule`).
* `schemas/domain.py`: `EvidenceState` values are now the API codes (`EVIDENCE_SUPPORTED`, ...); unused prototype
  models removed. `data/demo/expected.json`: states as codes.
* `analysis/pipeline.py`: verify every claim, reconcile with verified claims only, apply the gate; run stats include
  verification and state counts. Timeline shows verified claims only (`excluded_unverified` reports the rest).
* `schemas/analysis.py`: `ClaimRecord` (claim + `verified` + `failed_checks`), returned by the claims API.
* `analysis/review.py`: priority follows the state (Review required 1, Conflicting 2, Insufficient 3); counts per state;
  finding views carry state, gate rule and rationale.
* Frontend: Reconciliation shows states, gate rule and "Why this state"; groups are "Needs attention" and
  "Evidence-supported"; Overview "Verified claims" stage is live (all six stages now come from the backend);
  **Inspect** links on claim rows, timeline entries and source cards; "Failed verification" badges.

### API
`GET /api/patients/{pid}/claims/{claim_id}/evidence`. Claims, reconciliation and timeline responses gained the
verification and state fields above.

### Tests executed
* `pytest`: **309 passed** (was 276). New: all 48 demo claims verify (and meet the advisory check); exit criterion: a
  tampered span fails V3; edited document text, shifted offsets, offsets outside the passage, unknown passage or
  document, another patient's claim, and event dates after the document date (day, month, year precision) each fail
  their check; the advisory check never blocks; the gate rule table (11 cases), rule order, "never supported with an
  issue", rationales never pick a side; **all 17 findings get the ground-truth state**; run stats; claims carry
  verification; inspector content; tampering after analysis detected by the inspector; a claim failing verification
  is excluded from the timeline and turns its finding Insufficient (VER-01); inspector 404/422.
* `npm test`: **68 passed** (was 62). Typecheck and build clean.
* Mutation checks: 15 planted bugs (V3, V5 and V6 disabled, advisory check made blocking, high-risk conflict rule
  removed, unverified claims reconciled, unverified claims on the timeline, inspector trusting the stored result,
  timeline entry for a failing claim, priority ignoring the state, inspector counting the advisory check, Inspect link
  without its label, verified count replaced by total, highlight offsets relative to the document, failed badge
  missing on source cards). 13 caught at first; two tests added and both then caught.
* Live run (real servers + Chromium): all six Overview stages from the backend (48 claims, 48 timeline entries,
  7 discrepancies as 2 review / 2 conflicting / 3 insufficient, 48 of 48 verified, 7 pending); warfarin shows
  Review required, GATE-03 and its reason; **Inspect** from a source card opens the inspector with 6 of 6 hard checks;
  editing the stored text in SQLite and reloading shows the alert, V3 failing with the stored text, and "Not on the
  timeline"; 390 px mobile without horizontal overflow; no console errors.

### Known issues / limitations
* Verification proves a claim is faithfully anchored to its source text. It does not prove the extractor read the
  sentence correctly (for example, a missed negation passes V1 to V6). The ground-truth tests cover the demo bundle only.
* High-risk classes (anticoagulant, insulin, opioid, any allergy) are a prototype setting, not a clinical standard.
* The inspector re-checks on demand; the timeline and reconciliation use the result recorded at analysis time until
  the analysis is re-run (the inspector says so when they differ).
* Not verified here: a real LLM call (unchanged).

### Next step
Phase 7: evidence search (BM25 over passages, claims, timeline and reconciliation items) and the Evidence Search screen.

---

## Phase 5: Reconciliation and review status (2026-11-25)

Version 0.5.0. Database schema v4.

### Files created
* `backend/medusa/analysis/reconciliation.py` (rules ported from the tested prototype), `analysis/retrieval.py`
  (in-memory BM25 with brand/generic expansion, used by the INV-01 missed-evidence check), `analysis/review.py`
  (views, priority, review status), `schemas/reconciliation.py`, `api/reconciliation.py`.
* `data/demo/expected.json`: ground truth for the 17 findings (planted issues and 7 decoys).
* `frontend/src/api/reconciliation.ts`, `lib/reconciliation.ts`, `components/source-card.tsx`, `components/passage.tsx`,
  `pages/reconciliation.tsx`, `pages/reconciliation.test.tsx`; `tests/test_reconciliation.py`.

### Files modified
* `db/schema.py`: migration v4 (`findings`, replaced atomically with claims on every run; `reviews`, kept across runs,
  with the finding fingerprint at review time). `db/analysis.py`: findings and review repository.
* `analysis/pipeline.py`: reconciliation runs inside each analysis; run stats include finding counts.
* `ingestion/service.py`: **Reset demo data** also clears the patient's findings and reviews.
* Frontend: Reconciliation route and sidebar link; Overview "Discrepancies" and "Needs review" stages show real counts.

### API
`GET /api/patients/{pid}/reconciliation?category=&only_issues=`, `GET /api/patients/{pid}/reconciliation/{finding_id}`,
`GET /api/patients/{pid}/review-queue`, `PUT /api/patients/{pid}/reviews/{finding_id}`.
Deviation from the plan: finding and review paths are under `/patients/{pid}/` because finding ids are per subject
(`FND-MED-warfarin`) and repeat across patients.

### Tests executed
* `pytest`: **276 passed** (was 230). New: all 17 findings match the ground truth exactly, no extra findings; exit
  criterion (warfarin, metformin, allergy, kidney disease, two missing reports); **0 conflict issues on all 7 decoys**;
  non-flagged patterns explained (MED-CHANGE-01, DX-EVOL-01, DX-FAMILY-01); conflicts cite both sides; wording never
  uses judgement words; high-risk configuration; INV-01 runs; documented restart resolves the warfarin conflict;
  an anaphoric "It was resumed" is escalated as possible missed evidence, not used to resolve; documented dose change
  becomes an observation; unverified claims excluded and reported; LLM claims not reconciled; priority table; API
  list, filters, detail with sides, review persistence across reruns, "changed since review", 404/422 cases,
  uploading the referenced report resolves the missing-record item, demo reset clears findings and reviews.
* `npm test`: **62 passed** (was 54). Typecheck and build clean.
* Mutation checks: 14 planted bugs (restart ignored, dose change ignored, evolution rule removed, family history
  merged into diagnoses, LLM claims reconciled, changed-since-review never set, high risk ignored in priority, reset
  keeping reviews, reruns deleting reviews, note not trimmed, Save always enabled, A/B labels missing, pending
  count replaced by item count, review panel on items without issues). 13 caught at first; the Overview test was
  tightened and caught the last one.
* Live run (real servers + Chromium): empty state; demo + analysis gives 7 of 17 with potential discrepancies,
  4 records-differ and 4 missing-information; warfarin shows two issues with A/B sources; flagging it with a note saves
  and the Overview "Needs review" drops from 7 to 6; metformin shows 3 sources; pantoprazole shows the documented
  regimen change; 390 px mobile without horizontal overflow; no console errors.

### Known issues / limitations
* Priority is a stand-in until the evidence gate (Phase 6) assigns the four evidence states.
* Reconciliation uses rule claims only. LLM claims have no structured fields (dose, action, list) to compare, so they
  stay visible as evidence but cannot create or resolve a discrepancy.
* Rules are tuned to the phrasing in the synthetic bundle. Different wording for holds, restarts or dose changes will be
  missed by extraction; INV-01 catches some of these as "possible evidence not extracted", not all.
* Review status has no user identity (single-user prototype, no login).
* Not verified here: a real LLM call (unchanged).

### Next step
Phase 6: deterministic claim verification (V1 to V7) and the evidence gate (GATE-01 to GATE-07) assigning
Evidence-supported, Conflicting evidence, Insufficient evidence or Review required, plus the evidence inspector.

---

## Phase 4: Clinical timeline (2026-11-25)

Version 0.4.0. No schema change: the timeline is a query over stored claims, not a table.

### Files created
* `backend/medusa/analysis/timeline.py`: ordering rules, deterministic labels, search matching.
* `backend/medusa/schemas/timeline.py`, `backend/medusa/api/timeline.py`: `GET /api/patients/{pid}/timeline?category=&q=&document_id=`.
* `frontend/src/api/timeline.ts`, `lib/timeline.ts`, `pages/timeline.tsx`, `pages/timeline.test.tsx`; `tests/test_timeline.py`.

### Files modified
* `analysis/pipeline.py` (`timeline()`), `main.py` (router), `schemas/domain.py` (unused prototype TimelineEntry removed).
* Frontend: route and sidebar link enabled; Overview "Timeline entries" stage shows real counts; Documents cards show
  claim counts; claim rows show the source sentence with the quoted words marked; the viewer opens with a claim
  highlighted from `?claim=` (used by the timeline's **View source**); empty viewer text mentions claims;
  "Show source" renamed "Show in text". `test/utils.tsx`: timeline fixtures, `calls.urls` for checking query strings.

### Ordering rules (as implemented)
1. Stated event date (including a header date for the same event, such as a lab's collection date).
2. Otherwise the document date, labelled "No event date in the passage; placed by the document date".
3. Otherwise undated, listed last.
Ties: coarser precision first, event date before document-date fallback, fixed category order, source order.
Year-only stays "2015", approximate keeps "~". Nothing is inferred.

### Tests executed
* `pytest`: **230 passed** (was 212). New: every claim appears once, chronological order, no invented dates, exit
  criteria (fever `~2026-03-07`; haemoglobin collected 2026-03-11, report 2026-03-12), year-only first,
  document-date fallback, same-day ordering, labels, undated and precision ordering, LLM labels, API filters with
  unfiltered counts, bad filters 422, empty before analysis, staleness.
* `npm test`: **54 passed** (was 45). Typecheck and build clean.
* Mutation checks: 12 planted bugs (event date ignored, precision ignored, basis tie-break dropped, year shown as a
  full date, quote not searchable, counts after filtering, collection/report wording, missing "approximate", no
  debounce, `?claim=` ignored, counts on failed cards, highlight off by one). 11 caught at first; the quote-search
  test was tightened and then caught the 12th.
* Live run (real servers + Chromium): timeline empty state; demo + analysis gives 48 entries (18 by event date, 30 by
  document date) in 8 date groups starting with `2015`; lab filter 4; search "glycomet" finds metformin;
  **View source** on haemoglobin opens the Laboratory Report with "Hemoglobin" highlighted; card counts
  15/2/4/9/3/15; 390 px mobile without horizontal overflow; no console errors.

### Known issues / limitations
* The timeline shows all stored claims. Verification (Phase 6) will add which ones pass the evidence checks; until
  then, the screen says entries are not checked for correctness.
* Several documents restating the same fact appear as separate entries (e.g. "upper gastrointestinal bleed" four
  times). Deliberate: each is a separate source. Grouping duplicates belongs with reconciliation (Phase 5).
* Year-only dates sort at the start of their year. Correct for this bundle; with several year-only events in one
  year their relative order is source order, not chronology.
* Not verified here: a real LLM call (unchanged from Phase 3).

### Next step
Phase 5: reconciliation. Discrepancy rules across documents (medication status, dose, diagnosis status, allergy
conflicts, missing referenced records), side-by-side sources, review status.

---

## Phase 3: Structured extraction (2026-11-25)

Version 0.3.0 (backend and frontend). Database schema v3.

### Files created
* `backend/medusa/analysis/`: `lexicon.py`, `dates.py`, `assertion.py` (ported from the prototype), `segmentation.py`
  (sections and sentence passages with absolute offsets), `rule_extractor.py` (8 claim categories, deterministic ids),
  `pipeline.py` (AnalysisService: run, status, claims, per-patient lock, crash recovery).
* `backend/medusa/analysis/llm/`: `provider.py` (Anthropic and OpenAI-compatible over httpx; retries on 429/5xx with
  Retry-After; stable error codes), `extractor.py` (Pydantic-validated JSON, verbatim quote verification, server-side
  offsets, dates and assertions), `check.py` (`python -m medusa.analysis.llm.check`).
* `backend/medusa/db/analysis.py`, `backend/medusa/schemas/analysis.py`, `backend/medusa/api/analysis.py`.
* `frontend/src/api/analysis.ts`, `lib/claims.ts`, `components/run-analysis-button.tsx`, `components/analysis-summary.tsx`,
  `components/claims-list.tsx`, `pages/analysis.test.tsx`.
* Tests: `tests/test_analysis_extraction.py`, `tests/test_analysis_dates_assertion.py`, `tests/test_llm.py`, `tests/test_analysis_api.py`.

### Files modified
* `db/schema.py`: migration v3 (passages, analysis_runs, claims with CHECK constraints; drops the unused v1 tables).
* `schemas/domain.py`: `Claim.extraction_method` (`rule:<id>` or `llm:<provider>/<model>`), `LlmAttrs`.
* `core/config.py`, `.env.example`: `MEDUSA_LLM_*` settings (key is a SecretStr, never logged or returned).
* `main.py`: analysis router and startup recovery. `requirements.txt`: httpx moved from dev to runtime.
* Frontend: Overview (claims stage with rule/LLM counts, Run analysis, last-run summary, stale/failure notes,
  Extraction row from `/api/analysis/config`), document viewer (claims list, source highlighting), document
  mutations and uploads now refresh analysis status. `test/utils.tsx` analysis fixtures.
* Tests updated for v3: `test_db.py` (claim constraints, cascade), `test_documents_api.py` (v1 upgrade).

### API
`POST /api/patients/{pid}/analysis`, `GET /api/patients/{pid}/analysis/latest`, `GET /api/patients/{pid}/claims?category=&document_id=`,
`GET /api/analysis/runs/{run_id}`, `GET /api/analysis/config`.

### Tests executed
* `pytest`: **212 passed** (was 114). New: extraction golden counts on the demo bundle (48 claims: diagnosis 18,
  medication 12, lab 4, procedure 4, encounter 3, symptom 3, allergy 2, record reference 2), dates and assertions,
  provider request shapes and every failure code via `httpx.MockTransport`, quote verification, pipeline and API
  (rules only, LLM ok, LLM failed, LLM partial, misconfigured, atomic replacement, staleness, cascade on delete,
  concurrent run 409, failed run keeps previous results, interrupted run recovery, key never returned).
* `npm test`: **45 passed** (was 34). `npm run typecheck` and `npm run build`: clean.
* Mutation checks: 11 planted bugs (case-insensitive quote match, no rule de-duplication, LLM label when every call
  failed, fingerprint ignoring re-uploads, non-atomic replacement, retrying 401, trusting the model's assertion,
  dropping "~", every claim labelled Rule, off-by-one highlight, missing stale marker). All 11 caught after two
  tests were tightened (exact highlight text; fingerprint on re-upload).
* Live run (real backend + Vite + Chromium): load demo, Run analysis gives 48 claims (48 rule, 0 LLM); Progress Note
  shows 9 claims, Show source highlights `pantoprazole`; uploading `endoscopy_report.pdf` marks results stale;
  390 px mobile width has no horizontal overflow; no console errors.
* `python -m medusa.analysis.llm.check` run in three configurations: disabled (exit 2), anthropic without key
  (misconfigured, exit 1), unreachable local server (unavailable, exit 1).

### Bug found and fixed during the phase
* Demo reset deletes and re-ingests identical files, which get identical content-addressed ids, so results looked
  current while no claims were stored. The fingerprint now includes each document's `updated_at`, and status also
  checks that the stored passage count matches the run.

### Known issues / limitations
* **Not verified here: a real LLM call.** This environment cannot reach provider APIs. Run
  `python -m medusa.analysis.llm.check`, then Run analysis, with your own key or a local Ollama server.
* LLM analysis is synchronous: with a provider configured, one call per document (4 in parallel) inside the POST.
  Expect seconds to a minute on the demo bundle; the button shows progress but there is no cancel.
* LLM quotes must match exactly. Models that normalise whitespace or punctuation will see those claims rejected
  (counted in the run summary). This is deliberate: an unverifiable quote is not evidence.
* Extraction accuracy is measured only against the synthetic demo bundle (golden counts), not on varied real-world
  phrasing. The lexicon is small by design.
* `EvidenceState` values in the domain module are still display strings; they become codes with the gate (Phase 6).

### Next step
Phase 4: clinical timeline built from stored claims (event date vs document date, approximate and undated
handling, ordering rules), timeline API and the Clinical Timeline screen.

---

## Phase 2: Document ingestion (2026-11-25)

Backend ingestion (upload, validation, PDF/TXT extraction, header metadata, status tracking, list, detail,
delete, demo load) was built and tested in the earlier stage. This phase added the demo reset and the React
Documents screen.

### Files created
| Path | Role |
|---|---|
| `frontend/src/pages/documents.tsx` | Documents screen: reset, drop zone, status filter tabs, document list, viewer; selection in the URL (`?doc=`) |
| `frontend/src/components/upload-dropzone.tsx` | drag-and-drop and picker; files sent one at a time; per-file progress and outcome (processed, stored-but-failed, rejected, duplicate, network error) |
| `frontend/src/components/document-viewer.tsx` | file facts, header metadata, failure explanation, warnings, extracted text with PDF page separators, status history, delete |
| `frontend/src/components/confirm-action.tsx` | inline confirmation for destructive actions (delete, reset) |
| `frontend/src/pages/documents.test.tsx` | 11 tests |

### Files modified
| Path | Change |
|---|---|
| `backend/medusa/db/documents.py` | `storage_paths_for_patient`, `delete_for_patient` |
| `backend/medusa/ingestion/service.py` | `_demo_folder`, `delete_patient_documents`, `reset_demo` (bundle checked before anything is deleted) |
| `backend/medusa/api/documents.py` | `POST /api/patients/{id}/demo/reset` |
| `backend/medusa/schemas/documents.py` | `DemoLoadResult.removed` |
| `tests/test_documents_api.py` | 3 reset tests |
| `frontend/src/lib/api.ts` | shared `interpretResponse`, so fetch and the upload (XMLHttpRequest, for progress) report errors identically |
| `frontend/src/api/documents.ts` | detail, delete, reset, `uploadDocument` with progress; hooks |
| `frontend/src/App.tsx`, `components/sidebar.tsx`, `pages/overview.tsx` | route; Documents enabled in the sidebar; Overview rows link to the document |
| `frontend/src/test/utils.tsx`, `test/setup.ts` | document fixtures, fake XMLHttpRequest with progress events |

### Tests executed
| Run | Result |
|---|---|
| `pytest` | 114 passed |
| Vitest | 32 passed (34 after the post-delivery fix) |
| Typecheck and production build | clean |
| Frontend mutation check: extension pre-check removed; delete/reset without confirmation; duplicate shown as plain rejection; uploaded document not opened | each caught (1, 3, 1, 1 failing tests) |
| Live: real backend + Vite; browser loaded the demo, uploaded all 7 files in `data/samples` at once, opened the PDF and a failed document, deleted one, reset | every sample gave its documented outcome; 11 documents, then 10, then 6 after reset with 6 stored files on disk; 390 px width without overflow |

The only browser console entry was the expected HTTP 422 for `empty_note.txt`, logged by the browser itself.

### Post-delivery fix (reported from the Windows run)
* **Symptom:** after unzipping Phase 2, the screen still showed the Phase 1 UI (sidebar "Documents P2").
* **Root cause:** the Phase 1 Vite server still held port 5173, so Phase 2's frontend exited with
  `Error: Port 5173 is already in use` and the browser kept showing the old UI. Reproduced exactly.
* **Fix:** versions are now visible and compared. Backend `__version__` and frontend `package.json` are both 0.2.0;
  the UI version is injected at build time (`vite.config.ts`, `__APP_VERSION__`). The sidebar footer shows
  `UI vX · API vY`; a different backend version gives a "Version mismatch" status and an amber banner with the fix.
  Each phase bumps both versions.
* **Tests:** 2 new Vitest cases (mismatch, matching). 34 passed. Live: Phase 2 UI against the real Phase 1 backend shows the banner and `UI v0.2.0 · API v0.1.0`.

### Known issues / limitations
* "Document processing" from the spec's API list happens during upload (synchronous, up to 5 MB). Analysis
  processing is `POST /api/patients/{id}/analysis` in Phase 3.
* The upload queue is per page visit; navigating away clears the results list (the documents themselves persist).

### Next step
Phase 3: migration v3, segmentation into passages, rule extractor, optional LLM extractor with quote verification,
analysis run endpoint, claims API, tests.

---

## Phase 1: Foundation (2026-11-25)

### Files created
| Path | Role |
|---|---|
| `docs/IMPLEMENTATION_PLAN.md` | final architecture, folder structure, schema, API contracts, sequence, risks, test strategy |
| `docs/PROGRESS.md` | this log |
| `frontend/package.json`, `package-lock.json` | dependencies and scripts (`dev`, `build`, `typecheck`, `test`) |
| `frontend/vite.config.ts` | React + Tailwind plugins, `@` alias, `/api` proxy driven by root `.env`, Vitest config |
| `frontend/tsconfig.json` | strict TypeScript |
| `frontend/index.html`, `public/favicon.svg` | entry document, brand icon |
| `frontend/src/index.css` | design tokens: colours, status palette, fonts, radii, shadows |
| `frontend/src/main.tsx`, `App.tsx` | providers (TanStack Query, workspace), route table |
| `frontend/src/lib/api.ts` | the only HTTP client; parses the error envelope; network and proxy failures become `network_error` |
| `frontend/src/lib/utils.ts` | `cn`, date and size formatting |
| `frontend/src/api/health.ts`, `api/documents.ts` | typed endpoint functions and query hooks |
| `frontend/src/context/workspace.tsx` | active patient record, persisted locally |
| `frontend/src/components/ui/{button,badge,card,skeleton}.tsx` | shadcn-style primitives |
| `frontend/src/components/{status-badge,empty-state,error-state,health-indicator,page-header,brand,sidebar,patient-switcher}.tsx` | shared components |
| `frontend/src/layouts/workspace-layout.tsx` | sidebar + top bar shell, responsive |
| `frontend/src/pages/{landing,overview,not-found}.tsx` | screens |
| `frontend/src/test/{setup.ts,utils.tsx}` | test setup, fetch router, app renderer |
| `frontend/src/**/*.test.ts(x)` | 4 test files |

### Files modified
| Path | Change |
|---|---|
| `backend/medusa/main.py` | routers mounted under `/api`; docs at `/api/docs` |
| `backend/medusa/api/documents.py` | demo route renamed to `/patients/{id}/demo/load` |
| `tests/test_app.py`, `tests/test_documents_api.py` | paths updated to `/api` |
| `requirements.txt` | removed `streamlit`, `requests` |
| `.env.example`, `.gitignore`, `pyproject.toml`, `README.md` | React workflow |

### Files removed
`frontend/app.py`, `frontend/api_client.py`, `.streamlit/config.toml`, `tests/test_frontend.py` (Streamlit UI, replaced by React).

### Features completed
* `/api`-prefixed backend; health and readiness reachable through the dev proxy.
* React workspace: landing page with real demo loading, workspace shell (sidebar with all spec screens,
  unbuilt ones disabled with their phase), patient switcher, live backend health, Overview built from
  real document data. Pipeline stages that do not exist yet show "Not available yet", never zero.
* Loading, error (with error code and request id, retry) and empty states on every data view.
* Responsive layout down to 390 px.

### Tests executed
| Run | Result |
|---|---|
| `pytest` (backend) | 111 passed |
| `npm test` (Vitest) | 18 passed (21 after the post-delivery fix) |
| `npm run typecheck` | 0 errors |
| `npm run build` | built |
| Clean copy: new Python venv from `requirements-dev.txt` + `npm ci` from lockfile, then all of the above | 111 passed / 18 passed / built; 0 npm vulnerabilities |
| Frontend mutation check: unbuilt stages show 0; unbuilt screens as links; error envelope ignored | each caught (1, 1, 3 failing tests) |
| Live: backend (`python -m medusa`) + Vite dev server; browser via Playwright: landing, enter workspace, demo load, overview, 390 px mobile | worked; no console errors or warnings |
| Live failure drill: backend stopped while UI open | UI shows "Backend offline" and a retryable `network_error`; recovers on restart |

Not executed here: anything on Windows itself. Commands are in the README.

### Bugs found and fixed during the phase
* Mobile: the documents table widened the whole page (grid column sized to content). Fixed with `minmax(0,1fr)`; page width now equals the viewport.
* Test query in the landing test matched two lists; made specific.
* A path rewrite in the backend tests changed a log-formatter fixture; expectation corrected.

### Post-delivery fix (reported from the Windows run)
* **Symptom:** UI showed "Backend offline" and "Request failed: Not Found (not_found)" on the Overview.
* **Root cause:** an older MEDUSA-X backend (stage 1/2, routes without the `/api` prefix) was still serving port 8000.
  Reproduced exactly by running the stage 2 backend behind the Phase 1 frontend.
* **UI defects it exposed:** any health error was labelled "offline", even when a server answered;
  the System panel said "unreachable" and ticked an unknown Environment green.
* **Fix:** `api/backend-status.ts` separates *nothing answered* (offline) from *a server answered without
  `/api/health`* (incompatible). A banner (`components/backend-banner.tsx`) on the landing page and workspace states
  the cause and the fix. System rows say "wrong server (HTTP 404)"; Environment shows "unknown" with no tick.
* **Tests:** 3 new Vitest cases (incompatible backend, stopped backend, healthy shows no banner). 21 passed.
  Verified live with the old backend, no backend, and the correct backend.

### VS Code support (added after Phase 1)
* `.vscode/tasks.json`: Setup (backend, frontend, everything), Run (backend, frontend, both as the default build task), Test (backend, frontend, all as the default test task), typecheck and build. Windows tasks run in Command Prompt and call `.venv\Scripts\python.exe` directly.
* `.vscode/launch.json`: FastAPI debug, Chrome and Edge debug, pytest current file, full-stack compound.
* `.vscode/settings.json`, `.vscode/extensions.json`: interpreter, pytest discovery, Pylance path, workspace TypeScript, recommended extensions.
* Verified: every task command run from a clean copy (setup, servers reach their ready text, tests 111 + 21, build); debug launch command answered `/api/health`. Not verified: VS Code on Windows itself.

### Known issues / limitations
* Documents screen does not exist yet in React (Streamlit version removed). Upload is available via `/api/docs` or `curl.exe` until Phase 2 completes.
* Overview counts beyond documents arrive with their phases.
* Evidence-state codes in the backend domain module still use display strings; switched to codes in Phase 3 (migration v3).

### Next step
Phase 2 completion: demo reset endpoint, Documents screen (drag-and-drop upload with progress, status list,
extracted-text viewer with metadata and history, delete with confirmation), tests.
