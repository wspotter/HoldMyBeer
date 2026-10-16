# Developer guide

## Local teaching engine

FastAPI serves the same-page recording/practice workspace on loopback:

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

Run `pytest -q`, `node --check web/app.js` and `python -m compileall -q holdmybeer`. Local browser acceptance used Playwright 1.62 with its matching installed browser. CI installs a matching browser for its resolved version.

`setup.py` copies canonical `web/` assets into `holdmybeer/web/` for wheels; `MANIFEST.in` includes assets in source distributions. The app resolves package assets first and source assets otherwise. `tests/wheel_smoke.py`, run with a separately installed wheel interpreter, verifies workspace assets, an actual reviewed browser trial and the eight-tool MCP handshake including saved revision retrieval. The native Hermes scaffold and teaching skill remain source-only.

This alpha executes the bundled four-action fixture and the separately approved public GitHub issue-brief procedure. The latter has cooperative cancellation, durable history and interrupted-run recovery. Arbitrary websites, live publishing, fixture mid-run cancellation, a managed production service and independent pilot/platform acceptance are unfinished. Track those gates in [docs/STATUS.md](docs/STATUS.md).

October 16 installed candidate acceptance: Hermes v0.22 loaded the MCP entry written by `connect hermes` in a fresh isolated home, proposed a GitHub issue brief, then executed and read the verified retained job after explicit UI approval. The installed package completed separate searches for `teaching` and `browser` with different issue sets. This is shared MCP consumption, not native status-plugin acceptance or proof of recording interpretation by Hermes.

Developer README updated for the procedure, proposal, MCP clients and packaging interfaces.

## Blended media trials

`select_media` is the preferred first action and accepts new/reuse modes; legacy `upload` procedures remain valid. Reuse resolves a retained fixture draft ID, preserving its filename while reconstructing generated fixture bytes. Run input snapshots retain this distinction. Optional bounded batches run sequentially, retain individual receipts and stop on the first failed item. The workspace keeps one item as the default. This is fixture-only file reuse, not retained original media.

## Unreleased first-use slice — October 15, 2026

`holdmybeer` and `python -m holdmybeer` launch the packaged app. The CLI reserves the requested socket before importing the app or creating storage, passes that socket to Uvicorn Server.run, and prints the actual selected port. Defaults remain 127.0.0.1:18940. Explicit `--host` can expose the app; keep loopback for personal data. `--data-dir` overrides HMB_DATA_DIR. Doctor checks required imports and the matching executable without importing the app; executable presence does not prove OS libraries or arbitrary site support. Optional frame tools do not fail doctor.

The guided UI creates a dedicated fixture session, guards dirty state and recording, requires inspection plus explicit trial authorization, and reuses the existing run/history APIs. Guided state is scoped to its session; switching to a personal workflow restores ordinary controls. It does not analyze a recording automatically or install Hermes skills. The external engineering acceptance artifact records the installed-wheel/browser receipt and exact candidate revision; no published release or deployment is implied.

Verify with `python -m pytest -q tests`, `node --check web/app.js`, a clean wheel installation outside the source tree, and `tests/wheel_smoke.py` under that interpreter. CLI tests include actual subprocess HTTP launch, occupied socket, custom storage, read-only doctor and actionable module commands. Browser tests include dirty-state protection, authorization, session switching, retained draft, and simulated missing-browser/connection recovery.
