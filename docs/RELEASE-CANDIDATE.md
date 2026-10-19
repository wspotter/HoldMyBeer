# 0.4.0a4: recording workspace preview

This preview simplifies the recording workspace and corrects execution-status reporting. The dated `0.3.0a3` receipts below describe an earlier checkout. They do not establish acceptance of this version. No production deployment is included.

The novice path is: record in the browser or import a video, name the app and task, choose **Save recording**, then find it under **Saved tasks**. There is no Easy mode completion or ready-to-run screen. The saved recording is unverified until separately reviewed. Connected assistant review is a deliberate MCP action; automatic review dispatch and generic replay of personal recordings are unavailable. Multiple-choice answers save a template for review and do not mark a task execution-ready.

The separate hybrid file runner supports deterministic rename, organize-by-extension, and CSV-summary recipes with real sample checks and sandbox previews. Generic GUI, browser, and terminal steps require agent assistance and do not yield success receipts. The fixed browser fixture trial remains a separate Advanced capability.

Saved tasks now provides an app/task sidebar and selected recording/settings panel. Saving task settings creates a new version; viewing does not. Archive removes a task from active choices while preserving its recordings and history; Show archived and Restore task bring it back. The naming form offers existing app/task pickers and supports recovering from typos and failed loading.

## Install and use

Obtain the reviewed wheel and its SHA-256 from the retained release checkpoint. Install in a dedicated Python 3.10+ virtual environment:

```sh
python3 -m venv /absolute/path/to/hmb-env
/absolute/path/to/hmb-env/bin/python -m pip install /absolute/path/to/likethis-0.4.0a4-py3-none-any.whl
/absolute/path/to/hmb-env/bin/python -m playwright install chromium
/absolute/path/to/hmb-env/bin/holdmybeer doctor
/absolute/path/to/hmb-env/bin/holdmybeer --data-dir /absolute/private/path/to/hmb-data
```

Open the printed HTTP loopback URL and use the recording flow: record or import a video, enter the app and task names, then choose **Save recording**. It appears under **Saved tasks**. Saving does not approve understanding or authorize execution. For assistant review, connect a compatible client through MCP and explicitly ask it to inspect the recording; review proposals remain separate from execution. For the separate fixed GitHub example, open Advanced and follow [the issue-brief instructions](ISSUE-BRIEF.md). `doctor` gives recovery commands for missing dependencies; it does not install them or guarantee that every operating-system browser library is available. Frame inspection additionally needs FFmpeg/ffprobe. Use [client setup](CLIENTS.md) for the explicit isolated Hermes connection; a client restart is required to discover new tools.

## Recovery and removal

- If the port is occupied, stop the known preview or choose an explicit different port. Match `HMB_URL` in the isolated MCP configuration to that port.
- A failed, cancelled or interrupted brief never retries itself. Inspect the retained plan/report, correct the cause, prepare a new plan and approve it explicitly.
- Stop HMB before copying or restoring the entire private data directory, including SQLite, `issue-briefs`, media, proposals and artifacts. Keep the backup private; recordings and session text can contain personal information.
- To roll back, stop the preview, retain the data backup, and install the previous reviewed wheel in a separate environment. This candidate adds files alongside the existing store; an older version does not display its issue-brief history. Cross-version restoration is not a substitute for a tested backup.
- Disconnect Hermes by removing only `mcp_servers.holdmybeer` from the explicitly selected home, or restore the installer's configuration backup after checking for subsequent changes. Normal Hermes profiles are not implicitly selected.
- Uninstall with that environment's `python -m pip uninstall holdmybeer`, or remove the dedicated environment after stopping it. User data is retained. Delete personal data separately only when you deliberately intend to remove it.

## Verification and limits

Historical October 18 checks for 0.4.0a2: 158 source tests passed, with one upstream Starlette/httpx deprecation warning. Browser acceptance covered the compact 390px recording/import flow, direct save to the task library without execution, reopening and updating tasks, Admin sample-check failures, escaped metadata, and cancelled capture. Repeated recordings with the same app/task name retain separate media and append task versions without orphaned recipes; tested source tasks cannot be merged into another task. Desktop and phone layouts were also inspected directly. The separately installed wheel passed packaged-asset, retained-media/version, reviewed Chromium fixture, and eight-tool MCP protocol checks. These checks do not establish automatic assistant interpretation or arbitrary replay.

Historical receipts: October 16 acceptance covered the prior candidate and included source tests, an installed-wheel/browser/MCP smoke, native Hermes v0.22 issue-brief calls, and retained GitHub search reports. A later installed-wheel smoke from outside its checkout verified the packaged `training.js`, two independent tasks, edit/history with retained-media preservation, the reviewed Chromium fixture, and the MCP history handshake; its recorded source suite passed 107 tests. App/task browser checks covered separate tasks, import and review, approval without execution, read-only playback, edit/history restore, and preserved legacy practice and GitHub results. These receipts apply to those dated checkouts. They do not verify this staged Easy mode flow or its current hybrid runner changes.

The named GitHub procedure reads visible issue titles and links; it does not prioritize or resolve issues, compile an arbitrary recording, sign in, write to GitHub, post socially, or guarantee exhaustive repository coverage. A fixture-only working marker does not enable arbitrary replay. Independent pilot users, other platforms, automatic assistant review dispatch, Hermes recording interpretation and a general recorded-task compiler remain open work.

## Promotion draft — founder review required

Suggested audience: Hermes/MCP developers who want inspectable, human-approved browser procedures. Suggested demo: ask your connected agent for a public issue brief, inspect and approve its exact plan, show the retained source-bearing report, then repeat with new search words. Explain the fixed supported procedure before showing the fixture teaching workspace.

Draft promise: “A free, open-source experiment in browser procedures you can inspect: choose a public GitHub repository, approve a read-only search, and keep the result. Bring your own MCP agent.”

After a separate founder publication decision, invite five willing developers; aim for three completed useful briefs, two return uses, and one concrete friction report per person. Measure completion time, assistance needed, failed outcomes and repeat use before stars or impressions. These are experiment targets; adoption and virality have not been measured. No outreach, posting, tracking installation or spending has been performed.

0.4.0a4 navigation/handoff acceptance (October 18): 168 source tests passed with one upstream deprecation warning. Desktop/mobile Settings, explicit developer entry, task/session-specific clipboard requests, zero mutation during review checks, unsaved-edit guards and actual persisted proposal display passed. A fresh installed LikeThis wheel passed the packaged assets, retained media/settings/history/archive, reviewed Chromium fixture and eight-tool MCP smoke. These checks verify the interface and saved proposal path; they do not prove automatic assistant dispatch or general app replay.
