# Developer guide

## Current simple recording flow

The novice path is intentionally small: record in the browser or import a video, name the app and task, choose **Save recording**, then find the saved item under **Saved tasks**. Easy mode ends there. It does not show a completion or ready-to-run screen. The saved recording is evidence to review, not evidence that the task was understood or executed.

Naming a fresh recording after an existing app/task appends a version atomically, preserving earlier sessions and media. The merge removes its provisional recipe and preserves the target recipe until settings are saved. A source task with a tested working version cannot be merged into another task. Case-insensitive naming retains the existing task's spelling; conflicting quick renames return HTTP 409.

The connected assistant path is explicit: a client can retrieve bounded session data and selected frames through MCP, inspect them, and submit a review-only proposal. The web auto-review endpoint does not infer observations or approval from media metadata. Multiple-choice answers save a template with `status: saved_for_review` and `execution_ready: false`. No automatic assistant dispatch or generic replay of personal recordings is implemented. Keep verification language tied to retained evidence from the specific supported runner.

The hybrid file runner executes only deterministic operations: `file_rename_batch`, `file_organize_by_ext`, and `csv_summary_report`. These operations have real sample checks and sandbox previews; live file changes require explicit approval. Generic browser, GUI, and terminal steps return `needs_agent_assist` and do not claim successful execution. The fixed four-action browser fixture runner remains separate and is the only supported browser procedure trial. Do not describe arbitrary website replay or native pixel understanding as delivered.

The Hermes integration is the `holdmybeer-mcp` stdio server. `holdmybeer connect hermes` is an explicit-home configuration helper; exported skills and MCP configuration do not prove installation, client connection, or tool consumption. The native Hermes plugin scaffold remains status-only.

The recording naming form offers explicit existing-app and per-app task selectors beside editable names. App changes refresh task choices and clear the prior app’s selected task. Selecting an existing task saves the new recording as its next version; the saved-version hint makes this visible before saving. Native selects remain available after text typos, without relying on filtered browser datalist suggestions.

## Local teaching engine

FastAPI serves the local app → task training workspace, recording UI, and separate Advanced workshops on loopback:

```bash
holdmybeer doctor
holdmybeer
```

Runtime recordings, proposals, SQLite data and screenshots belong outside the checkout under `HMB_DATA_DIR` (default `~/.local/share/holdmybeer`). No Printery service, LAN URL or managed deployment is configured by this repo. The current interface contract is [docs/CONTRACT.md](docs/CONTRACT.md).

`holdmybeer/models.py` owns shared procedure validation. Saved executable fixture actions drive procedure trials with supplied captions and new or reused fixture media. Runs snapshot the exact procedure revision so later corrections cannot alter earlier evidence. Notes-only legacy sessions remain readable; legacy practice mode remains available through the API. The UI uses procedure mode and requires review.

`procedure_revisions` retains each saved procedure in SQLite. `Store.update_session` uses an immediate transaction to reject conflicting revision contents or skipped revision numbers with HTTP 409 before saving any accompanying fields. The UI compares edited steps against a separate saved snapshot and exposes read-only revision history. New stores retain revision 1; upgrades seed only the known current revision with `legacy_current` provenance. No older history is fabricated, and run snapshots are unchanged. Media updates patch only their own field to avoid overwriting a concurrently saved procedure. `holdmybeer/revisions.py` supplies bounded history reads for both HTTP and MCP.

`proposals.py` writes separate review-only files. `GET /api/sessions/{id}/proposal` returns the latest valid proposal without applying it. Loading, saving a reviewed revision and running are separate user actions. Agent questions/observations and user answers persist in bounded answer bundles. The original recording stays intact.

`web/fixture.html` supplies sample-file selection, validation, a readable saved receipt and a retained draft list. Embedded mode hides standalone navigation. The runner reads output JSON only after the fixture verifies retention, and independently compares the draft ID, filename and caption with storage.

## MCP and clients

`holdmybeer-mcp` launches the official Python MCP SDK over stdio. Its eight tools expose bounded session reads, recording frames, saved procedure history, review-only proposals, and an issue-brief workflow. Issue briefs can be proposed, reviewed and explicitly approved in the UI, then started through the approval-gated `hmb_execute_approved_brief`; repeat starts return the same retained job instead of redispatching it. The host agent supplies vision and reasoning. Selected images returned to that host follow its model provider's data handling. `hmb_procedure_history` reads an exact revision or pages of up to 50 from the UI's data directory. Reconnect clients to discover additional tools; source changes alone do not establish installation or client consumption.

`holdmybeer connect hermes --home ABSOLUTE_PATH --data-dir ABSOLUTE_PATH [--url LOOPBACK_URL]` opt-in merges the `holdmybeer-mcp` stdio entry into only the selected Hermes home's `config.yaml`; it requires an explicit home and does not start Hermes, launch the workspace, install skills, or edit `~/.hermes` by default. It prefers the `holdmybeer-mcp` executable beside the active `sys.executable`, then falls back to `PATH`. The MCP process receives `HMB_DATA_DIR` and `HMB_URL` (default `http://127.0.0.1:18940`); run the app separately with the same data directory for issue-brief tools. `--url` accepts only an HTTP loopback root URL with no credentials, path, query or fragment and a valid explicit port. To avoid a new YAML dependency or lossy rewrite, the command reads/writes JSON-compatible YAML only, backs up an existing config before an atomic replacement, preserves other JSON settings, and refuses a different existing `mcp_servers.holdmybeer` entry. For ordinary YAML files it prints a merge snippet and leaves the file untouched. CLI tests cover the explicit-home guard, merge/backup, idempotence, refusal, URL validation and executable selection. Hermes v0.22 native discovery and three calls were verified with `hermes -t holdmybeer`; `-t mcp` did not select the server. Loading a profile produced by this installer remains unverified.

Frame inspection requires local `ffmpeg` and `ffprobe`. Decoding uses file/pipe protocols only, dimensions within 1280 × 720, finite timestamps, subprocess deadlines and a bounded packet-duration fallback for browser WebM without metadata. [docs/CLIENTS.md](docs/CLIENTS.md) contains configuration examples. Individual client installations and image understanding require separate receipts.

`skills/teach-workflow/SKILL.md` guides frame-grounded observations, questions, proposed actions and evidence review. No skill is installed automatically. `plugin.yaml` and root `__init__.py` remain a separate native Hermes status-only scaffold. Its `HMB_URL` accepts HTTP loopback URLs, refuses redirects and never starts or installs the preview. Production Hermes loading remains unverified.

## Packaging and checks

Install dependencies in a virtual environment with `python3 -m pip install -e '.[test]'` and install matching Chromium with `python3 -m playwright install chromium`. Runtime dependencies include FastAPI, Uvicorn, Playwright and MCP; tests use pytest/httpx and generated ffmpeg media.

Run `pytest -q`, check every shipped root JavaScript asset with `for file in web/*.js; do node --check "$file" || exit 1; done`, and run `python -m compileall -q holdmybeer`. Local browser acceptance used Playwright 1.62 with its matching installed browser. CI installs a matching browser for its resolved version.

`setup.py` copies canonical `web/` assets into `holdmybeer/web/` for wheels; `MANIFEST.in` includes assets in source distributions. The app resolves package assets first and source assets otherwise. `tests/wheel_smoke.py`, run with a separately installed wheel interpreter from outside the source checkout, verifies packaged workspace assets, app/task creation and versioned edit with retained media, an actual reviewed fixture browser trial, and the eight-tool MCP handshake including saved revision retrieval. The native Hermes scaffold and teaching skill remain source-only.

This alpha executes the bundled four-action fixture and the separately approved public GitHub issue-brief procedure. The latter has cooperative cancellation, durable history and interrupted-run recovery. Arbitrary websites, live publishing, fixture mid-run cancellation, a managed production service and independent pilot/platform acceptance are unfinished. Track those gates in [docs/STATUS.md](docs/STATUS.md).

October 16 installed candidate acceptance: Hermes v0.22 loaded the MCP entry written by `connect hermes` in a fresh isolated home, proposed a GitHub issue brief, then executed and read the verified retained job after explicit UI approval. The installed package completed separate searches for `teaching` and `browser` with different issue sets. This is shared MCP consumption, not native status-plugin acceptance or proof of recording interpretation by Hermes.

Developer README updated for the procedure, proposal, MCP clients and packaging interfaces.

## Blended media trials

`select_media` is the preferred first action and accepts new/reuse modes; legacy `upload` procedures remain valid. Reuse resolves a retained fixture draft ID, preserving its filename while reconstructing generated fixture bytes. Run input snapshots retain this distinction. Optional bounded batches run sequentially, retain individual receipts and stop on the first failed item. The workspace keeps one item as the default. This is fixture-only file reuse, not retained original media.

## Unreleased first-use slice — October 15, 2026

`holdmybeer` and `python -m holdmybeer` launch the packaged app. The CLI reserves the requested socket before importing the app or creating storage, passes that socket to Uvicorn Server.run, and prints the actual selected port. Defaults remain 127.0.0.1:18940. Explicit `--host` can expose the app; keep loopback for personal data. `--data-dir` overrides HMB_DATA_DIR. Doctor checks required imports and the matching executable without importing the app; executable presence does not prove OS libraries or arbitrary site support. Optional frame tools do not fail doctor.

Historical October 15 first-use slice: the guided UI created a dedicated fixture session and required inspection plus explicit trial authorization. Its acceptance receipts describe that earlier interface, not the current app/task/version flow.

Verify with `python -m pytest -q tests`, `node --check web/app.js`, a clean wheel installation outside the source tree, and `tests/wheel_smoke.py` under that interpreter. CLI tests include actual subprocess HTTP launch, occupied socket, custom storage, read-only doctor and actionable module commands. Browser tests include dirty-state protection, authorization, session switching, retained draft, and simulated missing-browser/connection recovery.

## Earlier compact interface — October 16, 2026

Candidate `0.3.0a2` used a compact Start screen and isolated fixture-practice session. This is historical interface context; the current primary flow is the app/task/version training workspace below. The fixture example remains under Advanced.

`web/briefs.js` creates its own saved session, displays readable plans and source-bearing issue results, preserves server-owned immutable approval/start gates, and offers history through Saved tasks. Old workspace reports remain reachable through their history action. Plan/result JSON is collapsed under technical details. Fixed fixture experiments and connection instructions remain under Advanced. The older guided fixture workflow is retained there; it is not the current primary training flow.

Earlier compact-interface browser checks covered the practice demo and saved-result reopening. Current app/task browser checks cover two independent tasks, recording import, understanding approval without execution, read-only working versions, edit/history restore and retained media. These checks do not establish recording-derived assistant execution.

## Directed recording-first interface — October 16, 2026

The directed recording interface introduced one task demonstration as the primary path. The current app/task model extends it: choose or create an app, choose or create a task with a name, description and done check, then create a version with a separate session and one primary recording. `web/training.js` owns app/task selection and edit/restore version actions; `web/directed.js` owns the isolated recording and review stages. Fixed fixture practice, GitHub issue briefs and the manual workshop remain under Advanced.

`/api/training/apps` lists apps and their independent tasks. Task detail returns its latest version, optional working pointer, version history and latest session. Edit and restore require `base_version` and create a distinct session; restore selects a `source_version`, copies its media bytes and inherits no approval or run proof. Older versions and the working version reject ordinary session and media mutations. Only the latest version can become working, and only after current understanding approval plus a matching retained verified procedure-mode fixture run. The resulting capability is explicitly fixture-only. Session and MCP list/detail responses include explicit optional `training_task` metadata; legacy sessions have no inferred task identity. Proposal creation and activation serialize on SQLite transactions so frozen versions cannot accept a late proposal. History can open retained versions read-only without restoring them. Task edits use the existing session PUT for task name, description and done check. `GET /api/sessions/{id}/teaching-review` reports waiting, stale, questions, ready or approved. `POST .../teaching-review/approve` requires explicit consent, a current proposal, a goal/completion check, and confirmation of the recording. It writes a separate understanding receipt; it never installs procedure steps, creates a run or authorizes execution. Recording replacement clears confirmation. Teaching proposals now carry server-derived SHA-256 snapshots of recording bytes and current task context; older unbound proposals cannot be approved in this path. Changing recording bytes, notes, task title, answers or corrections invalidates the review. The confirmation flag is excluded from the context digest. These snapshots identify inputs present at proposal submission; they do not prove an assistant actually inspected them. This remains a trusted local workspace, not a security boundary against its owner or other local processes.

Assistant review dispatch is not connected. A connected assistant must inspect frames and explicitly call `hmb_propose_teaching`; its current procedure schema remains limited to the bundled four-action fixture. The screen must explain this gap and stop while review is missing, stale or has open questions. Understanding approval is distinct from permission to act. Generic replay of recorded tasks remains unavailable. No hidden fallback executes a personal recording. The eight MCP tools and existing fixture/GitHub execution contracts remain unchanged.

A clean installed-wheel smoke now passes from outside the checkout: it confirms the imported package is outside the source tree, serves `training.js`, creates two independent tasks, edits one into a new version while preserving its media, runs the reviewed Chromium fixture, and completes the eight-tool MCP history check. The source suite passed 107 tests; focused browser checks cover app/task selection, version edits/restores, read-only playback and preserved legacy results. Browser window/tab selection still requires manual compatibility acceptance; generated media in regression tests is test input, not evidence of real recording interpretation.

The installed custom-model Hermes recording probe exposed a client capability gap: cached frame `MEDIA:` text did not prove image parts reached inference. Failed proposal attempts used `t` and `procedure.actions`; validators correctly rejected them. `hmb_propose_teaching` now exposes existing Pydantic observation/question/procedure models directly in MCP JSON Schema. The stdio/schema regression passes with all eight tools retained. No weakened validation or new execution tool was added.
