# MEDUSA-X QA checklist (Phases 10 and 11)

Two parts: a Windows run-through from a fresh unzip, and six failure drills. Every drill must end with a clear
message on screen and the app working again without a code change.

**Status of this checklist.** Every drill below was executed on Linux (the build machine), both as automated tests
and live in a browser through the Vite proxy. **The Windows run-through was not executed by the builder: there is
no Windows machine in the build environment.** Run Part A on Windows and tick each box. If a step fails, note the
step number and the exact message.

Use **Command Prompt** (not PowerShell) for every command. `medusa-x` means the unzipped project folder.

---

## Part A: Windows run-through from a fresh unzip (VS Code)

### A1. Prerequisites
- [ ] `python --version` prints 3.10 to 3.13.
- [ ] `node --version` prints v20.19+ or v22.12+.
- [ ] Nothing is listening on ports 8000 or 5173: `netstat -ano | findstr ":8000 :5173"` prints no `LISTENING`
      line. If one does, `taskkill /PID <pid> /F /T`.

### A2. Unzip and open
- [ ] Unzip `medusa-x-phase11.zip` into a new folder (not on top of an older phase).
- [ ] VS Code: File, Open Folder, choose `medusa-x`. Accept the recommended extensions.

### A3. Setup (once)
- [ ] Terminal, Run Task, **Setup: everything**. Expected: the venv is created, pip and npm finish without errors,
      and `.env` is created from `.env.example`.

### A4. Automated checks
- [ ] Terminal, Run Task, **QA: everything**. Expected, in order:
  - backend: `376 passed`
  - frontend: `Tests 92 passed (92)`
  - build: `built in ...` with no TypeScript errors (a chunk-size warning is fine)
  - ground truth: `37 of 37 checks passed.`

### A5. Start the app
- [ ] Press **Ctrl+Shift+B** (task **Run: MEDUSA-X**). Two terminals open: backend on 8000, frontend on 5173.
- [ ] Open http://127.0.0.1:5173. The top right shows **Backend online**, and the sidebar footer shows
      `UI v0.11.0 · API v0.11.0`.

### A6. Demo journey (follow `docs/DEMO.md` for the full script)
- [ ] Documents: **Load synthetic demo bundle**. 7 documents, all **Processed**.
- [ ] Overview: **Run analysis**. The pipeline shows 7 documents, 51 claims, 51 timeline entries, 7 discrepancies,
      and 51 verified claims. The evidence bar shows 17 reconciled subjects.
- [ ] Clinical Timeline, Reconciliation, Evidence Search (search `coumadin` finds warfarin), Review Queue and
      Summary all load without an error panel.
- [ ] Review Queue: record one review. It appears on the Summary.

### A7. Single-process demo
- [ ] Stop the two servers from A5. Terminal, Run Task, **Demo: single process**. Expected: the build runs, then
      `MEDUSA-X demo: open http://127.0.0.1:8000  (UI and API on one port)`.
- [ ] Open http://127.0.0.1:8000. The app loads with no Vite server running. Reload on
      http://127.0.0.1:8000/workspace/review: the same screen comes back (not a 404).
- [ ] Run the 3-minute path in `docs/DEMO.md` twice in a row, with **Reset demo data** in between. Both runs end the same:
      endoscopy report Insufficient evidence before the upload, Evidence-supported after it.
- [ ] Without a build (delete `frontend\dist`, then run the task's backend step alone: `set MEDUSA_SERVE_FRONTEND=true`
      then `python -m medusa` in `backend`). Expected: **MEDUSA-X backend not started** with "npm run build" advice.

### A8. Stop
- [ ] Ctrl+C in both terminals (or the trash-can icon on each terminal). Both ports are free afterwards (re-run
      the A1 `netstat` check).

---

## Part B: failure drills

Start the app as in A5 and load the demo plus run the analysis before each drill, unless the drill says otherwise.
Restore `.env` after the LLM drills (copy `.env.example` over `.env` again, or undo your edits).

### Drill 1: no LLM key
1. In `.env` set `MEDUSA_LLM_PROVIDER=anthropic`, `MEDUSA_LLM_MODEL=claude-haiku-5-5`, and leave
   `MEDUSA_LLM_API_KEY=` empty. Restart the backend.
2. Expected on Overview, System card, Extraction row:
   **LLM misconfigured: MEDUSA_LLM_API_KEY is not set (required for anthropic).**
3. Click **Re-run analysis**. Expected: the run completes, with `extractor rules · LLM misconfigured, not used`
   and *"LLM extraction was not used (...). Rule-based claims are complete; LLM additions are missing..."*.
   51 claims, all from rules.
4. Recovery: restore `.env`, restart the backend. The Extraction row reads **rules only (LLM off)**.

- [ ] Message shown  - [ ] Run still completed  - [ ] Recovered

### Drill 2: LLM returns garbage
1. In a third terminal: `.venv\Scripts\activate.bat`, then `python scripts\fake_llm_server.py`
   (other modes: `bad-json`, `wrong-quote`).
2. In `.env` set:
   ```
   MEDUSA_LLM_PROVIDER=openai_compatible
   MEDUSA_LLM_MODEL=garbage-model
   MEDUSA_LLM_BASE_URL=http://127.0.0.1:9911/v1
   MEDUSA_LLM_MAX_RETRIES=0
   ```
   Restart the backend.
3. **Re-run analysis**. Expected:
   - `prose` mode: *"LLM failed, not used ... (malformed_output: Reply contained no JSON object.)"*
   - `bad-json` mode: *"Reply JSON did not match the expected schema"*
   - `wrong-quote` mode: the LLM "succeeds", but every proposal is rejected with `quote_not_in_passage`.
     Proposals: 0 kept, 7 rejected.
   
   In every mode the result is 51 claims, all from rules. Nothing invented is stored.
4. Recovery: Ctrl+C the fake server, restore `.env`, restart the backend.

- [ ] prose  - [ ] bad-json  - [ ] wrong-quote  - [ ] Recovered

### Drill 3: backend stopped mid-session
1. With the app open on any screen, press Ctrl+C in the backend terminal.
2. Expected within about 40 seconds (14 s measured), or on the next click: a red banner reading
   **The MEDUSA-X backend is not running.** *Start it in a second terminal: `cd backend`, then
   `python -m medusa`. This page reconnects automatically.* The status light shows **Backend offline**.
   Numbers already on screen stay visible (they are the last loaded values) until the backend returns.
3. Restart the backend (re-run task **Run: backend**, or `python -m medusa` in `backend`).
4. Expected: the banner disappears within about 3 seconds and every screen refetches **without a browser
   reload**.

- [ ] Banner shown  - [ ] Recovered without reload

### Drill 4: database deleted
1. With the backend running and idle, delete the database files in `data`: `del data\medusa.db*`.
   - If Windows says the file is in use, stop the backend first, then delete, then start it again. A fresh empty
     database is created at startup. Skip to step 3.
2. Expected: an amber banner reading **The database is not ready: database file does not exist**, followed by
   recovery instructions. The next action that touches data recreates an empty database and returns the message
   *"The database file was missing or replaced, so an empty one was created..."*.
3. Expected recovery: the banner clears within about 3 seconds. Documents is empty. **Load synthetic demo bundle**
   and **Run analysis** restore everything (51 claims).

- [ ] Message shown  - [ ] Recovered  - [ ] (note whether deleting while running worked on Windows)

### Drill 5: port in use
1. With the backend running, open another terminal and start a second one:
   `cd backend` then `python -m medusa`.
2. Expected: it exits at once with
   **MEDUSA-X backend not started.** *Port 8000 on 127.0.0.1 is already in use by another MEDUSA-X backend,
   version 0.11.0 (this same version: it is probably already running in another terminal).* This is followed by
   `netstat` / `taskkill` advice and the `MEDUSA_API_PORT` option.
3. Variant: stop the backend, run `python -m http.server 8000`, then start the backend. Expected: "...already in
   use by another program." Stop the http.server and start the backend normally.

- [ ] Same-app message  - [ ] Other-program message

### Drill 6: upload over 5 MB
1. Create a 6 MB synthetic file:
   `python -c "open('big.txt','w').write('x'*6000000)"`
2. Documents: choose or drop `big.txt`.
3. Expected in the upload results list: **Rejected, not stored · payload_too_large**, with
   *"The file is 5.7 MB; the limit is 5,000,000 bytes. Nothing was uploaded."* The document list is unchanged.
4. API path (bypasses the UI check):
   `curl.exe -F "file=@big.txt" http://127.0.0.1:5173/api/patients/SYN-0001/documents`
   Expected: `{"error":{"code":"payload_too_large","message":"Request body exceeds the 5,000,000 byte limit."...}}`.
   It must **not** be a 502 or a connection reset.
5. `del big.txt`.

- [ ] UI message  - [ ] API 413 (not 502)

---

## What was executed by the builder (Linux, 2026-11-25, Phase 11 build)

| Check | How | Result |
|---|---|---|
| Backend suite | `python -m pytest` | 376 passed |
| Frontend suite | `npx vitest run` | 92 passed |
| Typecheck and build | `npx tsc -b`, `npm run build` | clean |
| Ground truth | `python -m medusa.evaluate` | 37 of 37 |
| End-to-end API journey | `tests/test_e2e.py` (reset, analyse, timeline, reconciliation, verification, search, evidence, summary) | passed |
| Drills as tests | `tests/test_drills.py` (11), `frontend/src/components/recovery.test.tsx` (2), size pre-check tests (2) | passed |
| Drills live in Chromium through the Vite proxy | Playwright | all 6 show their message and recover |
| Oversized upload through the proxy | 10 raw 6 MB POSTs | 10 of 10 returned 413 (before the fix: random 502s) |
| Accessibility | axe-core on 9 screens | 0 violations |
| Mobile width | 360 px and 390 px, 8 screens | no horizontal overflow |
| Mutation checks | 9 mutants of the Phase 10 code, 9 of the Phase 11 code | 18 killed |
| Single-process demo | `MEDUSA_SERVE_FRONTEND=true`, Vite stopped, Playwright | UI, deep links and API on port 8000 |
| Demo path twice in a row | Playwright on port 8000, plus `tests/test_e2e.py` | identical results both runs, no console errors |

**Not executed:** the Windows run-through (Part A), Drill 4 deletion while running on Windows (file locking
differs), and any real LLM provider (the drills use a fake server and mocked transports).
