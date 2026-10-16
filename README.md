# HoldMyBeer

**Teach your agent by showing it.**

Local teaching alpha candidate `0.3.0a2`, not yet published. This candidate adds a launcher, guided practice task, explicit Hermes MCP setup and a read-only public GitHub issue brief. The [older prerelease](https://github.com/wspotter/HoldMyBeer/releases/tag/v0.2.0a1) predates these features.

The goal: show an app workflow, let the agent ask questions, then watch it try and improve from your corrections. This first prototype supplies the recording workspace and a reproducible trial engine. HoldMyBeer is an early plugin/skill project for teaching and checking browser workflows with the agent you already use. The shared engine is intended to support MCP-compatible clients such as Codex, Claude Code and editor integrations; Hermes is the first adapter. A stdio MCP bridge now exposes local recordings and teaching proposals; see [client setup](docs/CLIENTS.md). Individual client installations still need end-to-end verification.

## What works today

- Screen-capture controls using the browser picker (window/tab choice needs a manual compatibility check); verified video import and playback.
- Manual teaching notes, questions, and editable procedure steps.
- Reviewed executable actions drive a real Playwright trial with supplied captions and new or reused fixture files. Changed controls stop; editing the action target and saving a new revision repairs the workflow. Retained draft checks and screenshots supply evidence.
- One media item by default, with an optional queue of up to ten items. Reuse selects a retained fixture draft; each item gets its own receipt, and a failure stops the queue. The fixture reconstructs generated text files by filename; original video bytes are not retained.
- Saved procedure revision history with overwrite protection, immutable trial snapshots, and a same-page practice task. Your connected agent can read the same saved revisions through MCP.
- MCP tools return selected recording frames to your existing agent and place its observations, questions and validated procedure in a local review inbox.
- A [GitHub issue brief](docs/ISSUE-BRIEF.md) runs a fixed browser procedure against a public repository: review and approve its exact inputs, search open issues, then retain matching titles, source links and a screenshot. Each new input set requires approval.

The preview does **not** run its own AI model, automatically analyze a recording on capture, publish to social networks, or automate arbitrary websites. The recording-based trial engine supports the bundled fixture; the GitHub issue brief is a separate named procedure, not an arbitrary recording compiler. Hermes connects through the opt-in MCP adapter. The older native plugin is a separate status-only scaffold.

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

The source checkout is the contributor path. After installing a wheel built from this checkout, the same `holdmybeer` command launches it without the source tree. `python -m holdmybeer` is equivalent. Use `--port 0` for a free port or `--data-dir /path/to/private/data` to choose storage; an occupied port stops with advice instead of silently changing ports. Doctor is read-only: it checks imports and the matching Chromium executable, gives repair commands and reports optional frame tools. It does not prove every browser system library is available. Built wheels include the workspace assets and MCP executable; a clean wheel installation is checked separately. The native Hermes scaffold remains source-only. Frame inspection also requires `ffmpeg` and `ffprobe` on PATH.

Open <http://127.0.0.1:18940>. Data is stored outside the repository under `~/.local/share/holdmybeer` by default; set `HMB_DATA_DIR` to choose another private local directory. Browser capture may require a secure context; use localhost as shown.

Click **Try the example**. Choose a file name and caption, read the four steps, check the permission box, then choose **Save my practice draft**. The result shows the saved details and a screenshot link. **Saved tasks** reopens your results after refresh. Editing the details clears permission before another run. The example uses a harmless local practice app and does not publish anything.

The compact start screen also offers a public GitHub issue report. Recording, agent connection and manual teaching tools live under **Advanced**. A recording does not automatically become a runnable task. The original detailed practice walkthrough remains available there.

## Contribute

Bug reports, task ideas, documentation edits, and carefully sanitized reproduction notes are welcome. You do not need to be a programmer. Start with [CONTRIBUTING.md](CONTRIBUTING.md), browse the [starter issue drafts](docs/LAUNCH.md), or choose a small task from [the roadmap](docs/ROADMAP.md).

Before sharing evidence, remove personal recordings, account names, private URLs, cookies, tokens, and customer data. Never commit captured media or runtime artifacts.

## Project status

This is an experimental preview. See [DEVELOPER.md](DEVELOPER.md) for the current shape, [SECURITY.md](SECURITY.md) for local-data boundaries, and [LICENSE](LICENSE) for the license.

## Help build the actual teaching loop

The next substantial contributions are independent client installation tests and richer reviewed browser action contracts. The issue brief provides a useful read-only workflow beyond practice, while turning a recording into a reliable arbitrary-app procedure remains unfinished. Start with the [architecture contract](docs/CONTRACT.md) and [contribution guide](CONTRIBUTING.md). No fine-tuning is required: the reusable artifact is a tested procedure.

See [verified preview evidence](docs/VERIFICATION.md).
