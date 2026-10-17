# HoldMyBeer

**Teach your assistant one repeat task at a time — AI thinks, deterministic scripts execute.**

<p align="center"><img src="docs/hero-demo.svg" alt="HoldMyBeer 4-Stage Hybrid Workflow Demo" width="880"></p>

HoldMyBeer is a local workspace and universal agent bridge for organizing, teaching, dry-running, and exporting repeatable workflows. Choose or create an app and task — or click **`🍺 Hold My Beer (Instant Record)`** to start recording immediately with auto-inferred app and task names that you can rename inline afterward.

Every taught workflow is summarized as a human-readable **3-Line Recipe Card** (*When you give me -> I will do -> You will get*) and backed by a **Hybrid Execution Engine** (`HybridRecipe`) with an isolated **Sandbox Dry-Run** (`dry_run=True` by default) that previews a complete `Before -> After` file diff without touching your real directory.

Editing a task or restoring an earlier version creates a new draft session. The previous working version remains available, and older or working sessions are protected from ordinary edits. Restore copies the selected version's recording into the new draft; it does not copy review approval or trial evidence. Version history preserves each recording. It does not combine examples into a generalized policy.

Assistant review dispatch and generic replay of recorded tasks are not connected automatically. **Approval confirms current understanding only; it does not grant unattended execution capability.** Live hybrid execution (`dry_run=False`) requires explicit human approval (`user_approved_understanding=True`) and automatically rolls back the target directory from a pre-run snapshot if any post-assertion fails. When an unexpected file or UI state is encountered (`on_uncertainty="pause_for_agent"`), the runner pauses with a structured diagnostic snapshot instead of guessing. Fixed fixture/GitHub examples and the manual workshop remain under **Advanced**.

## What works today

- **1-Button Instant Record (`🍺 Hold My Beer`)**: Start a task session with zero setup fields, auto-infer app/task names from context, and rename inline after recording.
- **3-Line Recipe Card**: Plain-English summary (*When you give me*, *I will do*, *You will get*) plus typed parameter schema (`GET /api/tasks/{task_id}/recipe-card`).
- **Hybrid "AI Thinks, Script Executes" Engine & Sandbox Dry-Run**: Parameterized `HybridRecipe` actions (`file_rename_batch`, `file_organize_by_ext`, `csv_summary_report`, `archive_old_files`, `browser_or_fixture_action`) with isolated temporary sandbox dry-runs (`dry_run=True`), SHA-256 verified zero-mutation guarantees, `Before -> After` file diffs, and transactional rollback on live post-assertion failure (`POST /api/tasks/{task_id}/hybrid-run`). See the [Hybrid & Universal Architecture Spec](docs/specs/SPEC-hybrid-universal.md).
- **Universal Agent Interoperability**:
  - **Dynamic MCP Tools (`holdmybeer-mcp`)**: Exposes each saved hybrid workflow as a typed MCP tool (`hmb_workflow_<slug>`) alongside `hmb_list_universal_workflows` and the 8 core teaching/review tools.
  - **Portable `SKILL.md` Bundle Exporter**: `holdmybeer export-skill --task-id <id> --output-dir <dir>` (or `POST /api/tasks/{task_id}/export-skill`) exports a standalone `SKILL.md` + `recipe.json` + `run_recipe.py` bundle compatible with **Hermes**, **Octo**, **Antigravity**, **Claude Code**, **Codex**, and **Cursor**.
  - **OpenAI / Ollama Function-Calling Schema & Agent Detector**: `GET /api/tools/openai`, `GET /api/universal-agents` / `GET /api/agents/detect`, and `holdmybeer detect-agents`.
- **Local App & Task Organization**: Separate version history, screen recording or video import, playback, connected-agent frame inspection, review-only teaching proposals, and explicit human approval.
- **Bounded Browser Fixture & GitHub Issue Brief**: A reviewed four-action fixture trial (with step-specific timeout reporting) and a separate approved public GitHub issue brief. For one reviewed four-step task with a reproducible browser check, see the [fictional fixture draft example](docs/FIXTURE_EXAMPLE.md).

The preview does not run its own AI model, dispatch assistant review automatically, or replay arbitrary websites. A working badge requires current understanding approval and a matching retained verified procedure-mode fixture trial. It describes fixture support only.

## Try the local preview

Requires Python 3.10+. Use a virtual environment. From a source checkout, install its dependencies and browser:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[test]'
python3 -m playwright install chromium
holdmybeer doctor
holdmybeer
```

Open <http://127.0.0.1:18940>. Choose **I’ll show you** (or click **`🍺 Hold My Beer (Instant Record)`**) to work through the app and task stages, inspect the **3-Line Recipe Card**, and run a **Sandbox Dry-Run**. Your data stays in the local workspace under `~/.local/share/holdmybeer` by default; set `HMB_DATA_DIR` to choose another private directory. Browser capture may require a secure context; use localhost as shown.

To inspect universal agent connections or export a portable `SKILL.md` bundle from the CLI:

```bash
holdmybeer detect-agents
holdmybeer export-skill --task-id <task-id> --output-dir ./exported-skills
```

The source checkout is the contributor path. A separately installed wheel includes the web assets and MCP executable. `holdmybeer doctor` checks imports and the matching Chromium executable; it does not prove every browser system library is available. Frame inspection also requires `ffmpeg` and `ffprobe` on PATH. See [client setup](docs/CLIENTS.md) to connect an existing agent.

## Contribute

Bug reports, task ideas, documentation edits, and carefully sanitized reproduction notes are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), browse the [starter issue drafts](docs/LAUNCH.md), or choose a small task from [the roadmap](docs/ROADMAP.md).

Before sharing evidence, remove personal recordings, account names, private URLs, cookies, tokens, and customer data. Never commit captured media or runtime artifacts.

## Project status

This is an experimental preview. See [DEVELOPER.md](DEVELOPER.md) for implementation details, [SECURITY.md](SECURITY.md) for local-data boundaries, [docs/specs/SPEC-hybrid-universal.md](docs/specs/SPEC-hybrid-universal.md) for the Hybrid & Universal specification, and [docs/RELEASE-CANDIDATE.md](docs/RELEASE-CANDIDATE.md) for candidate scope and current verification status.
