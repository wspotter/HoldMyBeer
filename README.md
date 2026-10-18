# HoldMyBeer

**Show an assistant how you do a task. Keep the recording and review it when you are ready.**

<p align="center"><img src="docs/hero-demo.svg" alt="HoldMyBeer workflow overview" width="880"></p>

HoldMyBeer is a local workspace and bridge for connecting an assistant to task recordings, review tools, and a few deliberately bounded ways to execute work. It is built around a clear handoff: you demonstrate a task, save its recording with an app and task name, and find it under **Saved tasks**.

## The simple path

1. Record a task in your browser or import a video.
2. Give the recording an app and task name.
3. Choose **Save recording**. It appears under **Saved tasks**.

Saving keeps the recording for review. It does not mean HoldMyBeer or an assistant understood it, verified the task, or can replay it. A connected assistant can inspect selected recording frames and submit a separate review proposal. Review proposals and saved task templates remain unverified until a person evaluates them. HoldMyBeer does not automatically send recordings to an assistant.

For repeat work, HoldMyBeer also supports a small set of deterministic file recipes: batch renaming, organizing files by extension, and making a CSV summary. These recipes have real sample checks and can preview changes in a temporary sandbox. Generic browser, GUI, and terminal actions pause for agent assistance; they do not produce a synthetic success receipt. A separate Advanced workshop runs a fixed, reviewed browser fixture. That fixture is a bounded example, not replay of your recording or an arbitrary website.

## Start the local app

Requires Python 3.10+. In a source checkout, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[test]'
python3 -m playwright install chromium
holdmybeer doctor
holdmybeer
```

Open <http://127.0.0.1:18940>. The app stores recordings and workspace data under `~/.local/share/holdmybeer` by default. Set `HMB_DATA_DIR` or pass `--data-dir PATH` to use another location. The app binds to loopback by default; use it locally.

`holdmybeer doctor` checks required Python imports and the matching Chromium executable. It does not install dependencies or confirm every operating-system browser library is present. Recording-frame inspection also needs `ffmpeg` and `ffprobe` on `PATH`.

## Connect an assistant

The main integration is the `holdmybeer-mcp` server, which exposes bounded tools to a connected assistant. For Hermes, configure an explicit Hermes home:

```bash
holdmybeer connect hermes --home /absolute/path/to/hermes --data-dir /absolute/path/to/holdmybeer-data
```

This updates that home’s MCP configuration. It does not start the app or Hermes, install a skill, or prove the client loaded the server. Start the app separately with the same data directory, then reconnect or restart the client so it can discover the tools. See [client setup](docs/CLIENTS.md).

HoldMyBeer can export a portable skill bundle and report detected agent integrations:

```bash
holdmybeer detect-agents
holdmybeer export-skill --task-id <task-id> --output-dir ./exported-skills
```

Exports and MCP configuration are setup aids. They are not evidence that an assistant received a recording, understood a task, or executed a workflow. The separate native Hermes plugin scaffold is status-only; production loading is unverified.

## Advanced examples

The **Advanced** area includes a fixed browser fixture workshop and a constrained public GitHub issue brief. The issue brief requires a person to review and approve its exact plan before it runs. See the [fixture example](docs/FIXTURE_EXAMPLE.md) and [issue brief guide](docs/ISSUE-BRIEF.md).

## Contribute

Bug reports, task ideas, documentation edits, and carefully sanitized reproduction notes are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), browse the [starter issue drafts](docs/LAUNCH.md), or choose a small task from [the roadmap](docs/ROADMAP.md).

Before sharing evidence, remove personal recordings, account names, private URLs, cookies, tokens, and customer data. Never commit captured media or runtime artifacts.

## Project status

This is an experimental preview. See [DEVELOPER.md](DEVELOPER.md) for implementation details, [SECURITY.md](SECURITY.md) for local-data boundaries, [the release candidate](docs/RELEASE-CANDIDATE.md) for current verification status, and [the hybrid architecture spec](docs/specs/SPEC-hybrid-universal.md) for design notes.
