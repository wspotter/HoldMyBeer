# Product and execution contract

LikeThis is a local workspace. The app and MCP server should use the same data directory. The `likethis` CLI uses `HMB_DATA_DIR` or the compatibility default `~/.local/share/holdmybeer`. A direct web-app launch checks `LIKETHIS_DATA_DIR`, then `HMB_DATA_DIR`, then an existing `~/.local/share/holdmybeer`, and otherwise uses `~/.local/share/likethis`. To guarantee a shared store, set `HMB_DATA_DIR` explicitly in both processes; for example launch with `HMB_DATA_DIR="$HOME/.local/share/likethis" likethis` and put the same path in the MCP client environment. The app binds to loopback by default.

## Saved task lifecycle

The primary workspace organizes work as app → task → version. A version has its own recording session. Saving task changes creates a new version; viewing an earlier version is read-only. Restoring a version copies it into a new version and does not copy review or execution approval. Archiving removes a task from active choices while retaining its recordings and history; unarchiving restores it to active choices.

Review is a separate human-guided flow. An MCP client may read bounded session details and timestamped frames, then submit a separate proposal. LikeThis displays the proposal for manual review. Copying a review request does not send it to a client, and the app does not dispatch recordings automatically. Proposal metadata does not prove that the assistant inspected the images. Approving understanding is not permission to execute.

## Supported execution

- **File recipes:** `file_rename_batch`, `file_organize_by_ext`, and `csv_summary_report` perform deterministic operations with sample checks and a before/after preview. Applying real file changes requires explicit approval.
- **Bundled fixture:** a reviewed procedure has exactly four actions: `select_media` (legacy `upload` remains readable), `fill`, `click`, and `verify_draft`. It runs against LikeThis's local fixture only. It does not post to a real service or replay a personal recording. See [the example](FIXTURE_EXAMPLE.md).
- **Public GitHub issue brief:** a fixed browser procedure reads a bounded number of public issue search results from one repository. A person must approve the exact plan before it runs. It does not sign in, write to GitHub, or provide an exhaustive audit. See [the guide](ISSUE-BRIEF.md).

Generic browser, GUI, and terminal actions do not produce successful execution receipts. Generic GUI and terminal work requires agent assistance. There is no general-purpose replay of recorded workflows or automatic assistant dispatch.

## Persistence and API notes

Task version changes use SQLite `BEGIN IMMEDIATE` transactions and compare the submitted `base_version` with the latest version. Stale bases, archived-task edits, and duplicate task names return HTTP 409. Session procedure saves are atomic: identical content may be retried at its current revision; changed content must advance by exactly one. Stale, skipped, or conflicting revisions return HTTP 409. Procedure history is append-only through the application, readable by exact revision or newest-first pages of up to 50. Older and working task versions reject ordinary session mutations. Each run stores a snapshot of its procedure and revision.

Review proposals carry server-generated hashes of recording media and current task context. Editing either makes the proposal stale; approval is limited to the current proposal and records understanding only. Proposal creation and task activation serialize through SQLite write transactions.

Relevant registered routes include `GET /api/training/apps`, `POST /api/training/apps`, `POST /api/training/apps/{app_id}/tasks`, `GET /api/training/tasks/{task_id}`, task archive/unarchive/settings/restore routes, `GET/POST /api/sessions`, `GET/PUT /api/sessions/{session_id}`, session media and procedure-revision routes, and the issue brief list/detail/approve/start/cancel/report routes under `/api/issue-briefs`. The API is a local application interface, not a security boundary against other processes running as the same user. See [SECURITY.md](../SECURITY.md) for data handling guidance.
