# Developer guide

LikeThis is a Python/FastAPI local application with a browser UI and an optional stdio MCP server. Python 3.10 or newer is required. The package is named `likethis`; the repository is `wspotter/LikeThis` and compatible `holdmybeer` commands/configuration names are retained.

## Development setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m playwright install chromium
likethis
```

The app binds to `127.0.0.1:18940` by default. The `likethis` CLI uses `HMB_DATA_DIR` or the compatibility default `~/.local/share/holdmybeer`. A direct web-app launch checks `LIKETHIS_DATA_DIR`, then `HMB_DATA_DIR`, then an existing `~/.local/share/holdmybeer`, and otherwise chooses `~/.local/share/likethis`. Set `HMB_DATA_DIR` explicitly for both app and MCP processes to guarantee a shared store; for example `HMB_DATA_DIR="$HOME/.local/share/likethis" likethis`, with that identical path in the MCP client environment. Runtime SQLite data, recordings, and generated evidence should stay outside the checkout. Frame extraction requires local `ffmpeg` and `ffprobe`.

## Structure

- `likethis/` contains the application, persistence, browser runners, command line, and MCP server.
- `web/` contains the primary Start, Saved tasks, Settings, and developer workshop interfaces.
- `tests/` contains the Python, API, and browser checks.
- `docs/` contains user and contributor guides. `docs/specs/` holds design specifications; proposals there are not necessarily implemented behavior.

The primary workspace organizes recordings as app → task → version. Task edits and restores create a new version; restores copy media but not approval or trial proof. Older and working versions are frozen against ordinary session edits. Task-version writes use SQLite `BEGIN IMMEDIATE` and check `base_version`; stale edits, archived-task changes, and duplicate names return HTTP 409. Archive/unarchive updates task organization while retaining recordings and history.

## Review and execution boundaries

Recording review is manual. A connected MCP client can retrieve bounded session data and selected frames, then submit a separate review proposal. The person reviews that proposal in LikeThis. Copying a review request does not contact a client, and the application does not automatically dispatch recordings. A proposal is not proof that an assistant inspected the images.

Session procedure saves also use an immediate SQLite write transaction. Re-saving identical content at the current revision is idempotent; changed content must use exactly the next revision, while stale, reused-with-different-content, or skipped revisions return HTTP 409. The revision history is retained and can be read by exact revision or in newest-first pages of up to 50. Runs snapshot the procedure revision and steps used, so later edits do not alter earlier receipts.

Teaching proposals are separate review files bound to fingerprints of current media and task context. Changes to those inputs make a proposal stale; review approval applies only to the current proposal and does not authorize execution. Proposal creation and version activation serialize through SQLite write transactions.

The supported execution paths are deliberately narrow: deterministic file recipes (`file_rename_batch`, `file_organize_by_ext`, and `csv_summary_report`) with sample checks and a before/after preview; a four-action browser procedure against the bundled local fixture; and a named public GitHub issue-search procedure. File changes require explicit approval. Generic GUI and terminal actions require agent assistance. Fixture actions cannot target arbitrary websites or run shell commands. The issue brief reads a bounded set of public issue links and requires approval of its exact plan before execution. There is no general replay of personal recordings, automatic review dispatch, or live publishing.

See [docs/CONTRACT.md](docs/CONTRACT.md) for the behavior/API boundary, [docs/CLIENTS.md](docs/CLIENTS.md) for MCP setup, and [docs/VERIFICATION.md](docs/VERIFICATION.md) for checks contributors can reproduce from a source checkout.
