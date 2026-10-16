# Public GitHub issue brief

This is a named supported browser procedure in the unreleased 0.3 alpha candidate. It reads a public repository's open-issue search and saves a bounded local report. It never signs in, creates issues, comments or publishes. It does not compile arbitrary recordings or infer a new browser procedure from a video.

## Use

1. Start `holdmybeer` on loopback and create or select a workflow.
2. In **A real workflow: GitHub issue brief**, enter `owner/repository`, optional plain search words, and a maximum of 1–10 issues.
3. Choose **Prepare issue procedure**. Read the exact target, inputs, steps and session revision. Check explicit consent and choose **Approve procedure**.
4. Choose **Run approved issue brief**, or ask a connected agent to call `hmb_execute_approved_brief` with the approved job ID. Preparation is not approval and running is not success.
5. Inspect the retained result and download its JSON report. **Load issue brief history** reopens jobs after reload. Each new input set requires a new reviewed plan.

The report is a snapshot of visible matching links, not a complete repository audit, issue resolution or model-generated priority assessment. Page text and issue titles are untrusted content. Follow source links to assess the underlying issues yourself.

## Boundaries and recovery

The server binds approval to an immutable plan hash, session revision, repository, search words and limit. Consent expires after ten minutes. The UI approval exchange uses a same-site browser cookie and CSRF header; the MCP tools have no approval operation. This is a trusted-local-user application: another process with your account's file/network access is not sandboxed out.

The runner uses a fresh unauthenticated browser and a fixed GitHub issue-search path. It rejects target redirects and non-read network methods rather than following a login or guessing a different control. Changed or missing controls require review. Only a successful, settled browser read can produce a verified report; there is no hidden API fallback.

Cancellation is cooperative between bounded browser actions. A browser operation already waiting may take until its timeout to stop. It does not undo local evidence already saved. A repeated start request returns the existing job, including failed/cancelled/interrupted states; it never silently replays it. If the app restarts during a run, it records `interrupted`. Inspect that outcome and prepare another plan if needed.

Data is in `HMB_DATA_DIR/issue-briefs/` and `HMB_DATA_DIR/artifacts/`. Keep these with the SQLite store when backing up. Uninstalling the Python package does not delete user data. Stop HMB before restoring a backup. No managed service or public release is installed by this candidate.

## MCP

The three additional tools are `hmb_propose_issue_brief`, `hmb_execute_approved_brief`, and `hmb_get_issue_brief`. Set `HMB_URL` to the separately running app's HTTP loopback URL, and `HMB_DATA_DIR` to the same directory. The connected agent can prepare a proposal, then must stop for UI approval before execution. Poll the retained job with bounded calls; do not treat a queued job as a completed result.

Hermes v0.22 selects configured MCP servers by name: use `-t holdmybeer` when narrowing this connection. A generic `-t mcp` does not select it. Reconnect after adding tools. Host-agent image understanding remains separate from browser execution; source inspection or a tool list does not establish that an agent interpreted a recording.
