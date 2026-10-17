# 0.3.0a3: unpublished local release candidate

The current local candidate organizes training as app → task → version. Choose or create an app and task, describe the task and done check, then record or import one complete example. Each version has a separate session and one primary recording. Edit task and restore create a new draft; the prior working version remains available. Historical and working sessions are protected from ordinary changes. No public release or production deployment has occurred.

## Install and use

Obtain the reviewed wheel and its SHA-256 from the retained release checkpoint. Install in a dedicated Python 3.10+ virtual environment:

```sh
python3 -m venv /absolute/path/to/hmb-env
/absolute/path/to/hmb-env/bin/python -m pip install /absolute/path/to/holdmybeer-0.3.0a3-py3-none-any.whl
/absolute/path/to/hmb-env/bin/python -m playwright install chromium
/absolute/path/to/hmb-env/bin/holdmybeer doctor
/absolute/path/to/hmb-env/bin/holdmybeer --data-dir /absolute/private/path/to/hmb-data
```

Open the printed HTTP loopback URL and choose “I’ll show you”. Choose or create the app and task, describe the completion check, then record or import one complete example. Edit task starts a new version; restore copies the selected earlier version into a new draft without its approval or trial proof. A connected assistant must explicitly inspect the recording and propose its understanding through MCP; automatic review dispatch is not connected. Approval confirms understanding only. Generic replay of recordings is unavailable. A version can be marked working only with current approved understanding and a matching retained verified procedure-mode trial; current support is limited to the local fixture. For the separate fixed GitHub example, open Advanced and follow [the issue-brief instructions](ISSUE-BRIEF.md). `doctor` gives recovery commands for missing dependencies; it does not install them or guarantee that every operating-system browser library is available. Frame inspection additionally needs FFmpeg/ffprobe. Use [client setup](CLIENTS.md) for the explicit isolated Hermes connection; a client restart is required to discover new tools.

## Recovery and removal

- If the port is occupied, stop the known preview or choose an explicit different port. Match `HMB_URL` in the isolated MCP configuration to that port.
- A failed, cancelled or interrupted brief never retries itself. Inspect the retained plan/report, correct the cause, prepare a new plan and approve it explicitly.
- Stop HMB before copying or restoring the entire private data directory, including SQLite, `issue-briefs`, media, proposals and artifacts. Keep the backup private; recordings and session text can contain personal information.
- To roll back, stop the preview, retain the data backup, and install the previous reviewed wheel in a separate environment. This candidate adds files alongside the existing store; an older version does not display its issue-brief history. Cross-version restoration is not a substitute for a tested backup.
- Disconnect Hermes by removing only `mcp_servers.holdmybeer` from the explicitly selected home, or restore the installer's configuration backup after checking for subsequent changes. Normal Hermes profiles are not implicitly selected.
- Uninstall with that environment's `python -m pip uninstall holdmybeer`, or remove the dedicated environment after stopping it. User data is retained. Delete personal data separately only when you deliberately intend to remove it.

## Verification and limits

Earlier October 16 acceptance covered the prior candidate and included source tests, an installed-wheel/browser/MCP smoke, native Hermes v0.22 issue-brief calls, and retained GitHub search reports. That evidence does not verify the current app/task/version addition. A fresh installed-wheel smoke from outside the checkout now verifies the packaged `training.js`, two independent tasks, edit/history with retained-media preservation, the reviewed Chromium fixture, and the MCP history handshake. The source suite passed 107 tests. App/task browser checks cover separate tasks, import and review, approval without execution, read-only playback, edit/history restore, and preserved legacy practice and GitHub results. Retained versions also have a separate read-only view.

The named GitHub procedure reads visible issue titles and links; it does not prioritize or resolve issues, compile an arbitrary recording, sign in, write to GitHub, post socially, or guarantee exhaustive repository coverage. A fixture-only working marker does not enable arbitrary replay. Independent pilot users, other platforms, automatic assistant review dispatch, Hermes recording interpretation and a general recorded-task compiler remain open work.

## Promotion draft — founder review required

Suggested audience: Hermes/MCP developers who want inspectable, human-approved browser procedures. Suggested demo: ask your connected agent for a public issue brief, inspect and approve its exact plan, show the retained source-bearing report, then repeat with new search words. Explain the fixed supported procedure before showing the fixture teaching workspace.

Draft promise: “A free, open-source experiment in browser procedures you can inspect: choose a public GitHub repository, approve a read-only search, and keep the result. Bring your own MCP agent.”

After a separate founder publication decision, invite five willing developers; aim for three completed useful briefs, two return uses, and one concrete friction report per person. Measure completion time, assistance needed, failed outcomes and repeat use before stars or impressions. These are experiment targets; adoption and virality have not been measured. No outreach, posting, tracking installation or spending has been performed.
