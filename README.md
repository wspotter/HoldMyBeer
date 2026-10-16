# HoldMyBeer

**Teach your assistant one repeat task at a time.**

HoldMyBeer is a local preview for organizing work by app and task. Choose or create an app, choose or create a task, describe what done means, then record or import one complete example. Review the saved video and the assistant's interpretation before explicitly approving its understanding. An app can contain many independent tasks; each task version has its own session and one primary recording.

Editing a task or restoring an earlier version creates a new draft session. The previous working version remains available, and older or working sessions are protected from ordinary edits. Restore copies the selected version's recording into the new draft; it does not copy review approval or trial evidence. Version history preserves each recording. It does not combine examples into a generalized policy.

Assistant review dispatch and generic replay of recorded tasks are not connected. Approval confirms current understanding only; it does not grant execution capability. The current supported trial is limited to the reviewed local fixture. Fixed fixture/GitHub examples and the manual workshop remain under **Advanced**.

## What works today

- Local app and task organization with separate version history.
- Screen recording or video import, playback, and explicit confirmation that the recording shows one complete example.
- Connected-agent tools for selected recording frames and review-only teaching proposals. A person reviews the proposal and explicitly approves current understanding.
- Versioned task editing and restore, with copied media and no inherited approval or run proof.
- A bounded, reviewed four-action fixture trial and a separate approved public GitHub issue brief.

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

Open <http://127.0.0.1:18940>. Choose **I’ll show you** to work through the app and task stages. Your data stays in the local workspace under `~/.local/share/holdmybeer` by default; set `HMB_DATA_DIR` to choose another private directory. Browser capture may require a secure context; use localhost as shown.

The source checkout is the contributor path. A separately installed wheel includes the web assets and MCP executable. `holdmybeer doctor` checks imports and the matching Chromium executable; it does not prove every browser system library is available. Frame inspection also requires `ffmpeg` and `ffprobe` on PATH. See [client setup](docs/CLIENTS.md) to connect an existing agent.

## Contribute

Bug reports, task ideas, documentation edits, and carefully sanitized reproduction notes are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), browse the [starter issue drafts](docs/LAUNCH.md), or choose a small task from [the roadmap](docs/ROADMAP.md).

Before sharing evidence, remove personal recordings, account names, private URLs, cookies, tokens, and customer data. Never commit captured media or runtime artifacts.

## Project status

This is an experimental preview. See [DEVELOPER.md](DEVELOPER.md) for implementation details, [SECURITY.md](SECURITY.md) for local-data boundaries, and [docs/RELEASE-CANDIDATE.md](docs/RELEASE-CANDIDATE.md) for candidate scope and current verification status.
