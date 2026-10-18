# Local teaching contract

The FastAPI workspace binds to loopback. Runtime media, SQLite data, proposals and screenshots stay outside the source checkout under `HMB_DATA_DIR` (default `~/.local/share/holdmybeer`). The stdio MCP process uses that same directory; it does not start the workspace.

## Workspace API

- `GET /api/status`: current capability labels.
- `GET /api/training/apps`: active app/task hierarchy; `include_archived=true` also includes archived tasks.
- `GET /api/training/tasks/{id}`: task, latest session and retained training versions.
- `PUT /api/training/tasks/{id}/settings`: `base_version`, `name`, optional `description`, `done` and `notes`; atomically creates a new version for changes. A stale version, duplicate name or archived task returns 409; a no-op retains the current version.
- `POST /api/training/tasks/{id}/archive` and `/unarchive`: reversible organization, preserving media/history. Archived tasks cannot be edited or accept new recordings until unarchived.
- `POST /api/training/tasks/{id}/restore`: `base_version` and `source_version` copy a historical version into a new one; this is separate from unarchiving.
- `GET/POST /api/sessions`: list/create workflows.
- `GET/PUT /api/sessions/{id}`: retrieve or update title, notes, answers and procedure.
- `GET /api/sessions/{id}/procedure-revisions`: latest 50 saved revisions, newest first; use `next_before_revision` as `before_revision` to page backwards.
- `GET /api/sessions/{id}/procedure-revisions/{revision}`: exact retained procedure, save time and provenance.
- `POST /api/sessions/{id}/media`: atomic bounded WebM/MP4 upload (100 MiB maximum).
- `GET /api/sessions/{id}/media`: retained video.
- `GET /api/sessions/{id}/proposal`: latest valid agent proposal, or `null`; never applies it.
- `POST /api/sessions/{id}/run`: caption, plain filename, normal/changed fixture variant, legacy repair flag, and mode `practice` (legacy default) or `procedure`.
- `GET /api/sessions/{id}/runs/{run_id}`: retained run and procedure snapshot.
- `GET /api/artifacts/{run_id}.png`: retained screenshot.
- `GET /fixture`: draft practice app; `?embedded=1` hides standalone navigation.
- `GET/POST /api/fixture/drafts`: retained fixture drafts.

Unknown fields, missing IDs and invalid targets are rejected. Origins must match the loopback request's scheme/host/port. Only one browser trial runs at a time.

## Procedure and execution

A procedure has a positive integer `revision` and at most 20 steps. Every step has bounded text `goal` and `check`. Notes-only steps remain readable for older sessions. Executable fixture mode requires exactly these four steps:

| action | target | input |
| --- | --- | --- |
| select_media (or legacy upload) | exact accessible input label | filename |
| fill | exact accessible input label | caption |
| click | exact accessible button name | absent |
| verify_draft | absent | absent |

Actions execute in saved order against the bundled fixture. No arbitrary URL, selector, JavaScript or shell command is accepted. Run inputs are substituted at execution time. `select_media` supports `media_mode: new` or `reuse`. Reuse requires an existing retained fixture draft ID and resolves its filename from storage. Legacy `upload` remains a fresh-file action. `check` documents expected evidence; it is not evaluated as executable text. Verification compares the returned draft ID and the expected filename and caption with retained API storage.

Missing targets stop with `needs_teaching`; no alternate locator is guessed. The repair flag is ignored in procedure mode. A run retains the exact procedure snapshot, mode, revision, steps, failure, draft ID and screenshot URL. Changing saved actions does not alter earlier evidence. Browser interactions have time limits; there is no mid-run cancellation interface yet.

The UI invalidates its review checkbox when actions change. Saving a changed procedure advances its revision. A user then explicitly authorizes a local trial. The API remains a local developer interface; callers can explicitly request a fixture run. The MCP bridge cannot execute a fixture procedure.

Procedure saves are atomic with session changes. The current revision may be resubmitted only with identical contents; changed contents must use exactly the next revision. An explicit new revision may also retain the same steps. Stale, reused-with-different-content and skipped revisions return HTTP 409 without saving accompanying notes or answers. Notes-only and media updates preserve the latest procedure. Saved history is append-only through the application. For upgraded stores, history begins with the known current revision, labelled `legacy_current` with its retention time; overwritten older revisions cannot be reconstructed. Previous run snapshots remain available separately.

## Agent teaching bridge

`hmb_list_sessions`, `hmb_get_session`, and `hmb_recording_frames` read bounded local evidence. Frame inspection accepts 1–6 finite timestamps and returns timestamp-labelled images scaled within 1280 × 720. Local ffprobe/ffmpeg use file/pipe protocols only and bounded subprocess work. A packet scan handles MediaRecorder WebM with missing duration metadata.

`hmb_procedure_history` reads that same persisted history through MCP. Supply `revision` for an exact snapshot, or omit it for the newest 50; `before_revision` pages backwards. It cannot approve, replace or execute procedures.

`hmb_propose_teaching` validates up to six timestamped observations, six questions and an executable procedure. It atomically writes a separate private proposal file. It cannot replace the reviewed session or execute anything. The workspace loads the latest proposal only when requested, displays observations/questions/actions, and waits for review.

User answers remain bounded strings. Agent question/observation bundles may use up to 4000 characters; individual answers remain limited to 2000. Selected frames and session text returned through MCP enter the host agent's conversation and follow that host's data handling. HoldMyBeer runs no internal model and makes no independent remote inference requests.

The native Hermes scaffold is separate and status-only. See [client configuration examples](CLIENTS.md) for the shared bridge. Client examples are not end-to-end installation receipts.

## Named public issue brief

The separate [GitHub issue brief](ISSUE-BRIEF.md) reads a public repository using a fixed, versioned browser procedure. It does not extend the recording-based action vocabulary above. `POST /api/issue-briefs` snapshots the exact repository, plain search words, limit and saved session revision. The UI approval exchange binds explicit consent to that immutable plan hash for ten minutes. `POST /api/issue-briefs/{id}/start` requires that approval and unchanged session revision; it returns the existing receipt when repeated. One shared browser lock covers both runner types.

`GET /api/issue-briefs?session_id=...` lists retained jobs; `GET /api/issue-briefs/{id}` inspects one; `POST /api/issue-briefs/{id}/cancel` requests cooperative cancellation; `GET /api/issue-briefs/{id}/report` downloads a verified retained JSON report. Running jobs become `interrupted` on application restart and never replay automatically. The MCP adapter exposes proposal, approved execution and status tools for this named procedure, with no approval tool. Approval is a trusted-local-user boundary, not a sandbox against other local processes.

## Media items

The trial defaults to one media item. Optional `items` contains one to ten items, each with a caption, filename and media mode. Reuse items require `existing_draft_id`; new items supply a filename. Items execute sequentially and each completed attempt retains its own receipt. The batch stops at the first failed item. Remaining items are not executed.

The fixture stores filenames and captions, not original file contents. Reuse reconstructs a harmless generated fixture file with the retained filename in the isolated browser. It does not inherit another browser tab's file selection or reuse real video bytes.
