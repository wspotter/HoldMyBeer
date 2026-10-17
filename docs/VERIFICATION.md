# Preview evidence — October 14, 2026

This is a working local prototype, not the completed AI teaching product.

| Check                | Observed result                                                                                                       |
| -------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Normal fixture trial | Real Chromium upload/fill/save; retained draft ID retrieved successfully                                              |
| Changed button       | Trial stopped with `needs_teaching`; no draft was created by the stopped step                                         |
| Reviewed repair      | Exact `Store draft` locator selected; new caption saved and retained                                                  |
| Media import         | Three-second explicitly labeled transport-test WebM decoded, duration 3 seconds, readyState 4                         |
| Timestamp note       | Retained after save and page reload                                                                                   |
| Teaching answers     | Retained after save and page reload                                                                                   |
| Trial history        | Normal, stopped and repaired attempts selectable in the interface                                                     |
| Mobile layout        | 390px viewport checked; no horizontal document overflow                                                               |
| Browser console      | No errors in the tested workspace flow                                                                                |
| Backend tests        | 3 passed, including persistence, validation, upload preservation, origin rejection, and all three real browser paths  |
| Hermes scaffold      | Read-only tool registration stub and real loopback status request passed; not loaded into a production Hermes profile |

Local browser evidence used installed Playwright 1.62 with its matching Chromium. A separate environment initially resolved a newer Playwright expecting a different browser revision. Use `python3 -m playwright install chromium` from your activated environment; do not reuse a browser cache without checking compatibility. CI installs a matching browser before tests.

The screen picker itself has not been manually exercised in this environment. The imported clip is a media-transport test, not a recorded workflow. Automatic visual questions, procedure compilation and arbitrary-app replay remain future work.

## Teaching-loop alpha checkpoint

The earlier table records the initial fixed-routine preview. The next slice now has:

- A single-page embedded practice task and workflow creation without unsupported browser prompts.
- Saved executable procedure actions with fresh inputs and immutable per-run snapshots.
- Visible-browser normal verification, changed-label stop, and a saved `Store draft` correction that verified a new retained draft.
- Four stdio MCP tools: session list/detail, timestamped recording frames, and review-only teaching proposals. Real handshake, image and proposal responses are tested.
- Actual user-recording frames inspected at 2, 12, 24, 36 and 43 seconds. The clip shows a prior saved receipt, a caption edit and a new matching receipt; initial file selection was outside the observed segment. No invented click sequence was claimed.
- A proposal with timestamped observations and a focused question loaded into the visible workbook. The new-file default was explicitly marked as a working assumption derived from existing teaching notes.
- A separately built and installed wheel, tested outside the source import path: workspace assets, reviewed Chromium trial, retained screenshot and four-tool MCP handshake passed.
- 21 tests passed across backend, MCP and proposal validation, including WebM without duration metadata, unknown actions, corrupt/outside-path media, and proposal isolation from saved procedures.

These checks establish a local fixture teaching loop with the host agent doing the reasoning. They do not establish every client's installation, general website execution or a production Hermes deployment. Private user frames and recordings are excluded from repository evidence.

Codex CLI `0.162.0-alpha.17.2` with a vision-capable model and a temporary, narrowly permitted MCP configuration interpreted actual recording images and returned a proposal. No saved client configuration or skill install was changed. Decoder checks additionally reject a disguised playlist pointing at another local recording. GitHub CI passed the first teaching-loop checkpoint, including the installed-wheel browser trial; later hardening is checked in its own run.

## Blended media checkpoint

The expanded suite passes 24 tests. Real Chromium coverage verifies new media followed by caption-only reuse with the retained filename, immutable input/procedure receipts, and batches stopping on their first failed item. Invalid reuse IDs, filename overrides and legacy upload/reuse combinations are rejected. Fixture reuse reconstructs generated bytes; original video reuse remains outside this acceptance.

Visible workspace acceptance also verified a new filename, a caption-only reuse of that filename, and a mixed two-item queue with independent retained draft IDs. Failed and unattempted items remain queued for retry, and saved-draft media choices refresh after a run.
# October 15, 2026 — saved procedure revision history

- `uv run --with 'playwright==1.62.0' --extra test pytest -q`: 29 passed. Coverage includes atomic conflict rejection, competing saves through separate app instances, restart persistence, legacy seeding, 50-entry pagination, visible browser saves/history, and preservation of unsaved edits after HTTP 409.
- A fresh wheel, installed into a separate virtual environment and exercised outside the source directory, passed a reviewed Chromium trial, retained screenshot check and five-tool stdio MCP handshake, including retrieval of the exact saved procedure revision.
- A separate browser walkthrough saved revisions 1–3, expanded their retained steps and captured a screenshot with no page exceptions. The corrected target was retained separately from the earlier revision.
- `node --check web/app.js`, `python3 -m compileall -q holdmybeer` and `git diff --check` passed.

These are local plugin/UI and installed-package receipts. No live Hermes profile installation, agent execution tool, external website workflow or publishing is claimed. Decoder/browser dependencies are unchanged. Existing setuptools license-table and Starlette TestClient deprecation notices remain.

## Unreleased first-use candidate — October 15, 2026

Candidate code `24e481c` adds the packaged launcher/doctor and a guided fixture workflow. On the Linux test workstation the combined suite passed 55 tests with one existing Starlette/httpx deprecation warning; the final CLI subset passed 25 tests. JavaScript syntax and whitespace checks passed. A fresh virtual environment installed a locally built wheel outside the source tree, launched through its installed `holdmybeer --port 0 --data-dir ...` entrypoint, completed the guided real-Chromium trial, and verified fresh filename/caption/draft ID after reload without creating default storage. The installed wheel also passed retained screenshot and five-tool MCP/procedure-history checks.

Browser tests cover dirty workflow preservation, explicit authorization, session switching, duplicate demo starts and simulated missing-browser/network failures. Actual success used the installed matching browser. Doctor checks executable availability and permissions, not all OS runtime libraries. The new UI/CLI are local unreleased changes; the existing public prerelease predates them. Native Hermes client installation, generalized websites, automatic analysis/self-repair and public adoption remain unverified. Independent artifacts and receipts are retained in an external staging directory outside the repository; that local path is operator evidence, not a portable dependency.

## Compact first-use interface — October 16, 2026

Unpublished candidate `0.3.0a2` passed 91 source tests with the existing Starlette/httpx deprecation warning. The original workshop tests now enter through Advanced. The new first-use regression covers a blank start with no session creation, consent reset after edited details, a real Chromium draft save, readable retained output and reopening after reload. A subsequent targeted run also covers a real completed save whose HTTP response is deliberately lost: direct resubmission stays blocked and Check for a saved result recovers the existing draft without an extra run.

Direct installed-browser checks completed the beginner draft and a public GitHub `browser` query on `wspotter/HoldMyBeer`, returning issues 7, 6 and 1 as readable source links. The narrow 320-pixel layout had no horizontal overflow. This is developer verification, not an independent first-time usability study; recording-derived execution by installed Hermes remains incomplete.
