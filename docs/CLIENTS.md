# Connect your existing agent

HoldMyBeer supplies local MCP tools; your chosen agent supplies vision and reasoning. It does not require a separate model API key. The agent must support image tool results to interpret recording frames. Selected frames and session text enter that agent's conversation and follow its model provider's data handling. The original video remains in your local data directory.

Install the source checkout in a virtual environment as shown in the README. `ffmpeg` and `ffprobe` must be available on PATH for frame inspection. Install them through your operating system's package manager. Start the workspace separately; MCP does not launch the web server.

Use the absolute path to your environment's `holdmybeer-mcp` executable. These configuration examples follow the clients' documented stdio interfaces. Codex CLI has an actual temporary-configuration image/proposal receipt below. Claude Code, VS Code, desktop clients and permanent profile installs still need separate checks.

## Hermes (opt-in isolated home)

The CLI can add the HoldMyBeer MCP server to an explicitly selected Hermes home. Install HoldMyBeer in a virtual environment first, then run:

```bash
holdmybeer connect hermes \
  --home /absolute/path/to/hermes-holdmybeer \
  --data-dir /absolute/private/path/to/holdmybeer-data \
  --url http://127.0.0.1:18940
```

The command prefers the `holdmybeer-mcp` executable beside its active Python environment, then falls back to `PATH`. It writes `mcp_servers.holdmybeer` with that executable, the selected data directory, and `HMB_URL` (default `http://127.0.0.1:18940`). The issue-brief tools send their requests to that local app URL, so start the HoldMyBeer app separately with the same data directory. `--url` accepts only an HTTP loopback root URL without credentials, path, query, or fragment; explicit ports must be 1–65535. The command does not start Hermes, start the workspace, or install a skill. Start Hermes with that same home when you want to use the connection, for example `HERMES_HOME=/absolute/path/to/hermes-holdmybeer hermes`.

For safe editing without adding a YAML dependency, the installer accepts a missing config or a JSON-compatible `config.yaml` (JSON is valid YAML). It merges the one entry, preserves other parsed settings, and backs up an existing file before replacing it. If the file uses other YAML syntax, it prints the entry for manual merging; if `holdmybeer` already has different settings, it reports the conflict and leaves the file unchanged. `--home` and `--data-dir` must both be absolute paths; there is no default to `~/.hermes`.

Use the Hermes server-name filter `hermes -t holdmybeer` to expose this MCP server; `-t mcp` does not select it on v0.22. On October 16, Hermes v0.22 loaded a fresh isolated home written by this installer and successfully called session listing, issue-brief proposal, approved execution and retained-result inspection. The local browser approved the exact plan between those native calls. The first search returned four issue links and a repeated installed run with new search words returned three different matching links. This verifies the shared MCP path, not the native status-only plugin, every client variant, or Hermes recording interpretation.

## Codex

Add this table to your chosen Codex configuration, replacing the placeholder path:

```toml
[mcp_servers.holdmybeer]
command = "/absolute/path/to/HoldMyBeer/.venv/bin/holdmybeer-mcp"
tool_timeout_sec = 60
```

For a custom store, add `[mcp_servers.holdmybeer.env]` with `HMB_DATA_DIR = "/absolute/private/data/path"`. The web workspace and MCP process must use the same store.

Reference: [Codex MCP documentation](https://developers.openai.com/codex/mcp).

## Claude Code

```bash
claude mcp add --transport stdio holdmybeer -- /absolute/path/to/HoldMyBeer/.venv/bin/holdmybeer-mcp
```

Reference: [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

## VS Code

A VS Code-specific `.vscode/mcp.json` example:

```json
{
  "servers": {
    "holdmybeer": {
      "type": "stdio",
      "command": "/absolute/path/to/HoldMyBeer/.venv/bin/holdmybeer-mcp"
    }
  }
}
```

Reference: [VS Code MCP documentation](https://code.visualstudio.com/docs/agent-customization/mcp-servers).

## Verify the connection

Reconnect your client after configuration changes. Ask it to list HoldMyBeer sessions. A successful handshake alone does not establish image understanding: ask it to inspect selected frames from a harmless recording and cite timestamps in its observations.

Use [the teaching skill](../skills/teach-workflow/SKILL.md) as the task instructions. It is included in the source repository; no skill or client configuration is installed automatically. The native Hermes plugin remains a separate status-only scaffold.

## Tools and boundaries

- `hmb_list_sessions`: list recent local workflows.
- `hmb_get_session`: read notes, answers, procedure and bounded recent trial summaries.
- `hmb_procedure_history`: read an exact saved `revision`, or the latest 50 with `before_revision` pagination. This uses the same history as the teaching UI and cannot replace or execute a procedure. Reconnect an already running client to discover the new tool.
- `hmb_recording_frames`: return up to six timestamped images, scaled within 1280 × 720, using bounded local decoding. MediaRecorder WebM without duration metadata is supported.
- `hmb_propose_teaching`: save observations, questions and a validated procedure to the local proposal inbox. It cannot execute a procedure or replace the reviewed session.
- `hmb_propose_issue_brief`: prepare a fixed public GitHub issue-search plan for review.
- `hmb_execute_approved_brief`: start only the exact UI-approved plan; repeated calls return its existing receipt.
- `hmb_get_issue_brief`: inspect durable job state and output. A running job is not a successful result.

For recording-based teaching, the user loads a proposal, reviews the exact actions, saves a revision and authorizes the local fixture trial. Its contract is generated text-file selection, caption entry, an exact button click and retained draft verification. MCP cannot execute that fixture procedure. The separate [issue brief](ISSUE-BRIEF.md) has a constrained execution tool and requires explicit UI approval of each immutable plan. No MCP tool can approve either workflow.

## Recorded client acceptance

On October 14, 2026, Codex CLI `0.162.0-alpha.17.2`, using Luna and a temporary per-invocation MCP configuration, successfully called session detail, received and interpreted real recording images at two timestamps, and submitted a separate validated proposal. Its report correctly distinguished visible changes from unobserved file selection and independent storage verification. This test did not install a skill or alter saved client settings.

The first noninteractive attempt stopped at the client's approval policy before reading data. The successful invocation explicitly permitted only the three tools needed by the test. Normal clients should present their own tool approval controls; the server supplies read-only/destructive/open-world annotations. This receipt proves that client's image/proposal path, not arbitrary-app execution or all client variants.
