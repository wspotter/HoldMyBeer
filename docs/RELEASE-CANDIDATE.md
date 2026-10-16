# 0.3.0a1: unpublished local release candidate

This candidate adds an opt-in Hermes MCP installer and a human-approved, read-only public GitHub issue brief. It includes the launcher/doctor and guided fixture practice from the earlier engineering candidate. No public release or production deployment has occurred.

## Install and use

Obtain the reviewed wheel and its SHA-256 from the retained release checkpoint. Install in a dedicated Python 3.10+ virtual environment:

```sh
python3 -m venv /absolute/path/to/hmb-env
/absolute/path/to/hmb-env/bin/python -m pip install /absolute/path/to/holdmybeer-0.3.0a1-py3-none-any.whl
/absolute/path/to/hmb-env/bin/python -m playwright install chromium
/absolute/path/to/hmb-env/bin/holdmybeer doctor
/absolute/path/to/hmb-env/bin/holdmybeer --data-dir /absolute/private/path/to/hmb-data
```

Open the printed HTTP loopback URL, create or select a workflow, then follow [the issue-brief instructions](ISSUE-BRIEF.md). `doctor` gives recovery commands for missing dependencies; it does not install them or guarantee that every operating-system browser library is available. Frame inspection additionally needs FFmpeg/ffprobe. Use [client setup](CLIENTS.md) for the explicit isolated Hermes connection; a client restart is required to discover new tools.

## Recovery and removal

- If the port is occupied, stop the known preview or choose an explicit different port. Match `HMB_URL` in the isolated MCP configuration to that port.
- A failed, cancelled or interrupted brief never retries itself. Inspect the retained plan/report, correct the cause, prepare a new plan and approve it explicitly.
- Stop HMB before copying or restoring the entire private data directory, including SQLite, `issue-briefs`, media, proposals and artifacts. Keep the backup private; recordings and session text can contain personal information.
- To roll back, stop the preview, retain the data backup, and install the previous reviewed wheel in a separate environment. This candidate adds files alongside the existing store; an older version does not display its issue-brief history. Cross-version restoration is not a substitute for a tested backup.
- Disconnect Hermes by removing only `mcp_servers.holdmybeer` from the explicitly selected home, or restore the installer's configuration backup after checking for subsequent changes. Normal Hermes profiles are not implicitly selected.
- Uninstall with that environment's `python -m pip uninstall holdmybeer`, or remove the dedicated environment after stopping it. User data is retained. Delete personal data separately only when you deliberately intend to remove it.

## Verification and limits

The October 16 candidate passed 90 tests, a separately installed wheel/browser/MCP smoke check, native Hermes v0.22 proposal and approved-execution calls, and two live GitHub searches with distinct results and retained reports. Duplicate starts returned the same receipts. Source review and fixes were supervised by Codex with bounded Luna assistance; Ollie's native CQ/Hermes review is retained externally, including its initial contradictory verdict and clarification. These are supervised acceptance checks, not independent pilot-user evidence.

The named procedure reads visible issue titles and links; it does not prioritize or resolve issues, compile an arbitrary recording, sign in, write to GitHub, post socially, or guarantee exhaustive repository coverage. Browser cancellation is cooperative. Independent pilot users, other platforms, Hermes recording interpretation and the general teaching compiler remain open work.

## Promotion draft — founder review required

Suggested audience: Hermes/MCP developers who want inspectable, human-approved browser procedures. Suggested demo: ask Ollie for a public issue brief, inspect and approve its exact plan, show the retained source-bearing report, then repeat with new search words. Explain the fixed supported procedure before showing the fixture teaching workspace.

Draft promise: “A free, open-source experiment in browser procedures you can inspect: choose a public GitHub repository, approve a read-only search, and keep the result. Bring your own MCP agent.”

After a separate founder publication decision, invite five willing developers; aim for three completed useful briefs, two return uses, and one concrete friction report per person. Measure completion time, assistance needed, failed outcomes and repeat use before stars or impressions. These are experiment targets; adoption and virality have not been measured. No outreach, posting, tracking installation or spending has been performed.
