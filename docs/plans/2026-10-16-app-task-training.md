# HoldMyBeer: app → task → versioned training

Stacy approved this implementation on October 16: compact, directed teaching organized by app and task, with a clear future edit/update path. Codex owns design, integration, verification and commits. Luna implements bounded slices. Paperclip's local company receives verified release facts and bounded promotion/research work after the build; public posting, outreach, spending and production deployment remain excluded.

## Product contract

- Start with an app selector and that app's tasks. One app may have many independent task training files. Each task has a name, description, completion check and a recorded example.
- One main action per stage: choose/create app → choose/create task → record/import one complete example → review understanding → explicitly agree. Show readiness in plain language.
- Edit task creates a new draft version with a separate session, recording and approvals. The previous working version remains available. Restore copies an older version into a new draft; it never silently switches the working version.
- A version is marked working only after current understanding approval and an actual matching successful supported trial. Approval alone never establishes execution capability. Unsupported apps can retain training, but cannot acquire a fake working/tested badge.
- Each version has one primary example; version history preserves prior recordings. Multiple independent tasks are the app's multiple training files. Combining examples into a generalized policy is future work and is not implied by file grouping.
- Existing fixture/GitHub examples, saved outputs and manual workshop remain accessible under Advanced. No personal recording is silently replaced by a fixture demonstration.

## API and storage contract

Add `training.py`, initialized through create_app's Store. New SQLite tables coexist with existing sessions/runs/revisions; do not rewrite or infer categories for old sessions. Apps have UUID/name; tasks have UUID/app_id/name, latest version and optional working-version pointer. Each immutable version identity refers to a distinct existing HMB session. Current draft content remains editable through existing APIs; older version sessions are retained. Capture/restore copies the media bytes to the new session so updating a draft cannot overwrite an earlier recording. UI editing always uses the new session.

Routes under `/api/training`:
- GET `/apps` → `{apps:[{id,name,tasks:[{id,name,description,latest_version,working_version,session_id}]}]}`.
- POST `/apps` `{name}` → app.
- POST `/apps/{app_id}/tasks` `{name,description,done}` → task detail.
- GET `/tasks/{task_id}` → `{id,app_id,name,latest_version,working_version,versions:[{version,session_id,created_at,parent_version}],session:<latest-session>}`.
- POST `/tasks/{task_id}/edit` `{base_version}` → new task detail; optimistic conflict protection.
- POST `/tasks/{task_id}/restore` `{base_version,source_version}` → new draft detail copied from source; no inherited review approval or trial proof.
- POST `/tasks/{task_id}/activate` `{version,run_id}` → task detail, only if the latest version's understanding is currently approved, its saved procedure matches the proposal, and a retained verified procedure-mode fixture run matches that exact procedure/version. General replay remains unsupported. Do not add arbitrary navigation/execution.

Copied sessions carry teaching_goal/teaching_done and task name, but no confirmation/approval/proposal/run inheritance. Training version metadata is returned on session detail for UI context. APIs validate UUIDs, whitespace/lengths, duplicate app names, unknown IDs, optimistic revision conflicts and proof ownership. Clarify any contract corrections between implementers before UI integration.

## Tasks and owners

1. **Foundation and versioned edits — Luna backend.** Own training.py + focused training tests. Acceptance: create two tasks under one app, edit/restore safely with previous media unchanged, stale base conflicts, no activation without real matching proof. Root integrates router.
2. **Compact app/task GUI — Luna frontend.** Own web index/simple/directed/training/styles. Acceptance: no empty session on load, app/task selection, task description, separate stages, explicit Edit task/version history/restore, working version preserved, readable failure states, keyboard/320px usability. Depends on agreed API contract.
3. **Browser acceptance and regressions — Luna tests.** Own new browser tests and update outdated expectations only where behavior intentionally changed. Acceptance: real playable import, review/correction gates, reload/reopen, edit/history restore without overwrite, no fake execution or approval. Full suite failure from interrupted earlier run must be diagnosed and repaired.
4. **Integrated ride — Codex.** Inspect source diff, run all tests once stable, build versioned wheel, install outside source, verify actual browser path and supported useful workflow. Retain exact outputs, failures and manual capture limitations. Recheck current preview owner before restarting the same temporary endpoint. No production mapping changes.
5. **Commit and release evidence — Codex.** Update README/client/developer/recovery guides, source plan/checkpoint, commit release branch, produce patch/bundle/checksums. Publish registered guide identically and submit Diary review entry. Elsinore evidence remains partial if installed recording interpretation/execution is not actually proven.
6. **Paperclip company work — Codex with local studio agents.** Inspect current company/agent/project state, update product brief and capabilities, assign Promotion an honest launch/demo/adoption packet, Otto bounded audience/source research, Ollie review/coordination, Engineer only a concrete non-overlapping follow-up. One heavy WQ job at a time; finite work, actual retained artifact/report/postback evidence, no runaway periodic loops. Revoke any temporary CLI login. Latest user authorizes bounded queued studio work; older 'leave paused' handoff rule is superseded for this requested dispatch, not for unrelated tasks.

## Checkpoints and limits

After tasks 1–3, review schema/UI integration and meaningful tests before packaging. After task 4, verify installed assets and real browser behavior before claiming completion. User has already authorized the plan/build/dispatch; no additional permission round is needed for these reversible steps. Reviewer acceptance is reserved to Stacy/authorized operator; sudo does not grant workers reviewer authority. Promotion must describe only actual supported behavior and distinguish a free local alpha from a production-ready general automation tool.

Known open capability: automatic assistant review dispatch and generic recorded-app execution are not currently connected. Preserve honest stops while building the reusable task/version foundation. Do not lower acceptance criteria or declare that gap passed merely to close a ticket.
